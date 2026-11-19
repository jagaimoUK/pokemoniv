"use strict";
// Headless 3v3 coordinator. The pinned Battle still queues, orders and
// resolves moves. This session supplies team resources and policy decisions.
const vm = require("node:vm");
const {createPokemon, loadMaster} = require("./pvpoke_node_matrix.js");

const TURN_MS = 500;
const SWITCH_MS = 45000;
const CHARGE_MS = 10000;
const BATTLE_MS = 240000;
const MAX_TURNS = 500;
const RECENT_EVENTS = 24;
const VERSION = "rl-native-3v3-v1";

class UnsupportedMechanic extends Error {}
class BattleClockExpired extends Error {}

function integer(value, min, max) {
  return Number.isSafeInteger(value) && value >= min && value <= max;
}

function makeSeededRandom(seed) {
  let state = seed;
  return () => {
    state = (state + 0x6D2B79F5) >>> 0;
    let n = Math.imul(state ^ (state >>> 15), state | 1);
    n ^= n + Math.imul(n ^ (n >>> 7), n | 61);
    return ((n ^ (n >>> 14)) >>> 0) / 4294967296;
  };
}

function identifier(value) {
  return typeof value === "string" && /^[A-Za-z0-9_:\-]{1,100}$/.test(value);
}

function validateHandoff(handoff, seed, horizon) {
  if (handoff?.schema !== "rl-private-3v3-handoff-v1" ||
      !identifier(handoff.ruleset_id) ||
      !integer(seed, 0, 0xffffffff) || !integer(horizon, 1, MAX_TURNS)) {
    throw Error("Invalid team battle settings");
  }
  for (const team of [handoff.own_team, handoff.opponent_team]) {
    if (!Array.isArray(team) || team.length !== 3 ||
        team.some(row => !row || !identifier(row.species) ||
          !identifier(row.combatant_id) || !identifier(row.roster_clause_id) ||
          !integer(row.atk, 0, 15) || !integer(row.def, 0, 15) || !integer(row.hp, 0, 15) ||
          !integer(row.level * 2, 2, 100) || typeof row.level !== "number" ||
          !integer(row.cp, 10, 1500) || row.charged1 === row.charged2) ||
        ["species", "combatant_id", "roster_clause_id"].some(key =>
          new Set(team.map(row => row[key])).size !== 3)) {
      throw Error("Invalid prepared team");
    }
  }
}

function createTeamSession(handoff, {gamemasterPath, seed, horizon = MAX_TURNS,
  initial = [[], []], shields = [2, 2], entryStudy = null} = {}) {
  validateHandoff(handoff, seed, horizon);
  handoff = structuredClone(handoff);
  initial = structuredClone(initial);
  shields = structuredClone(shields);
  if (entryStudy !== null) {
    if (!integer(entryStudy.slot, 1, 2) || !integer(entryStudy.energyBonus, 0, 16)) {
      throw Error("Invalid entry study settings");
    }
    entryStudy = {slot: entryStudy.slot, energyBonus: entryStudy.energyBonus};
  }
  let studiedEntry = null;
  if (!Array.isArray(shields) || shields.length !== 2 ||
      shields.some(count => !integer(count, 0, 2))) {
    throw Error("Invalid starting team shields");
  }
  const dataHash = loadMaster(gamemasterPath);
  const {Battle, TimelineAction} = vm.runInThisContext("({Battle, TimelineAction})");
  const battle = new Battle();
  battle.setCP(1500);
  battle.setBuffChanceModifier(0);
  const unsupportedForms = new WeakSet();
  const sides = [handoff.own_team, handoff.opponent_team].map((rows, index) => ({
    team: rows.map((row, slot) => {
      const poke = createPokemon(row, index, battle, {prepareSpecialForms: false, strictPreparation: true});
      if (poke.formChange || poke.hasTag("mega") || /^minior(?:$|[_-])/i.test(poke.speciesId)) {
        unsupportedForms.add(poke);
        // Avoid running a form reset before it becomes an active matchup.
        poke.formChange = null;
      }
      const state = initial[index]?.[slot] ?? {};
      const hp = state.hp_points ?? poke.stats.hp;
      const energy = state.energy_points ?? 0;
      const buffs = state.buffs ?? [0, 0];
      if (!integer(hp, 1, poke.stats.hp) || !integer(energy, 0, 100) ||
          !Array.isArray(buffs) || buffs.length !== 2 ||
          buffs.some(stage => !integer(stage, -4, 4))) {
        throw Error("Invalid initial Pokemon state");
      }
      poke.setStartHp(hp);
      poke.setStartEnergy(energy);
      poke.setStartBuffs(buffs.slice());
      poke.setShields(shields[index]);
      poke.priority = 0;
      poke.reset();
      return poke;
    }),
    rows, activeSlot: 0, switchTimer: 0, shields: shields[index],
    revealed: new Set([0]), seenMoves: Array.from({length: 3}, () => new Set()),
  }));
  const pokemon = battle.getPokemon();
  const players = sides.map(side => ({
    getTeam: () => side.team,
    getSwitchTimer: () => side.switchTimer,
    startSwitchTimer: () => { side.switchTimer = SWITCH_MS; },
    decrementSwitchTimer: ms => { side.switchTimer = Math.max(0, side.switchTimer - ms); },
    useShield: () => { side.shields--; },
    reset: () => {}, // Each team is already initialized once for this session.
  }));
  battle.setPlayers(players);
  sides.forEach((side, index) => battle.setNewPokemon(side.team[0], index, false));

  const random = makeSeededRandom(seed);
  const events = [], decisions = [], randomness = [];
  let elapsed = 0, chargesThisTurn = 0, lastCharged = false;
  let shieldPrompt = null, selected = null, result = null;
  function draw(kind) {
    const roll = random();
    randomness.push({turn: battle.getTurns(), kind, roll});
    return roll;
  }
  function emit(kind, actor, fields = {}) {
    events.push({seq: events.length + 1, turn: battle.getTurns(), kind, actor, ...fields});
  }
  function requireSupported(poke) {
    if (unsupportedForms.has(poke)) throw new UnsupportedMechanic();
  }
  function supportsMove(move) {
    return !move.formChange && !["instant", "ignoresFaint"].some(tag => move.hasTag(tag)) &&
      (!move.buffs || (Number.isFinite(move.buffApplyChance) &&
        move.buffApplyChance >= 0 && move.buffApplyChance <= 1));
  }

  // PvPoke preserves its actual fast queue, damage, shields and buffs. The
  // coordinator only resolves equal-attack CMP and inserts the shield frontier.
  battle.teamStepRules = {
    orderActions(actions) {
      const first = actions.findIndex(action => action.type === "charged");
      const second = actions.findIndex((action, i) => i > first && action.type === "charged");
      if (first >= 0 && second >= 0 && pokemon[0].stats.atk === pokemon[1].stats.atk &&
          draw("cmp_tie") < 0.5) {
        [actions[first], actions[second]] = [actions[second], actions[first]];
      }
    },
    beforeAction(action, actor, defender) {
      if (!action.valid || action.processed) return true;
      if (action.type === "switch" && actor.hp === 0) {
        // A pending fast hit can KO a voluntary switch in the post-charge
        // window. Require a separate forced-replacement decision after the KO.
        action.valid = false;
      }
      if (action.type === "fast" && !supportsMove(actor.fastMove)) {
        throw new UnsupportedMechanic();
      }
      if (action.type !== "charged") return true;
      if (elapsed + CHARGE_MS > BATTLE_MS) throw new BattleClockExpired();
      const move = actor.chargedMoves[action.value];
      if (!supportsMove(move)) throw new UnsupportedMechanic();
      if (shieldPrompt?.action === action) return shieldPrompt.useShield !== undefined;
      emit("charge_announced", actor.index, {species: actor.speciesId});
      if (sides[defender.index].shields === 0) return true;
      shieldPrompt = {action, defender: defender.index, useShield: undefined};
      return false;
    },
    rollBuff(move) {
      return move.buffApplyChance === 1 ? 0 : draw("move_buff");
    },
  };
  battle.actionPolicy = (native, actor) => {
    const action = selected[actor.index];
    const [kind, value] = action.split("_");
    return new TimelineAction(kind === "charge" ? "charged" : kind, actor.index,
      native.getTurns(), Number(value ?? 0), {priority: actor.priority, charge: 1});
  };
  battle.shieldPolicy = index =>
    shieldPrompt?.defender === index && shieldPrompt.useShield === true;
  battle.onMoveResolved = (actor, defender, move, _damage, shielded) => {
    if (move.category === "charged") {
      const extra = chargesThisTurn++ === 0 ? CHARGE_MS - TURN_MS : CHARGE_MS;
      elapsed += CHARGE_MS;
      players.forEach(player => player.decrementSwitchTimer(extra));
    }
    const side = sides[actor.index];
    side.seenMoves[side.activeSlot].add(move.moveId);
    emit(move.category, actor.index, {species: actor.speciesId,
      move_id: move.moveId, shielded: Boolean(shielded)});
  };

  const nativeProcess = battle.processAction.bind(battle);
  battle.processAction = (action, actor, defender) => {
    const switched = action.type === "switch" && action.valid && !action.processed;
    const forced = switched && actor.hp === 0;
    if (switched) requireSupported(sides[actor.index].team[action.value]);
    nativeProcess(action, actor, defender);
    if (shieldPrompt?.action === action) shieldPrompt = null;
    if (!switched) return;
    const index = actor.index;
    const side = sides[index];
    const incoming = pokemon[index];
    side.activeSlot = action.value;
    side.revealed.add(action.value);
    incoming.shields = side.shields;
    actor.cooldown = 0;
    if (forced) actor.statBuffs = [0, 0];
    const queue = battle.getQueuedActions();
    for (let i = queue.length - 1; i >= 0; i--) {
      if (queue[i].actor === index) queue.splice(i, 1);
    }
    emit("switch", index, {species: incoming.speciesId,
      previous_species: actor.speciesId, forced});
    // A returning Pokemon's move metadata must refer to its current target.
    pokemon.forEach(poke => poke.resetMoves());
    // Offline-only intervention. Capture the resolved entry before any later
    // move in this step and before adding energy to the incoming Pokémon.
    if (entryStudy && index === 0 && action.value === entryStudy.slot && !studiedEntry) {
      const energyAdded = Math.min(entryStudy.energyBonus, 100 - incoming.energy);
      studiedEntry = {action_turn: battle.getTurns(), elapsed_ms: elapsed, forced,
        state: snapshot(), event_count: events.length, decision_count: decisions.length,
        randomness_count: randomness.length, energy_added: energyAdded};
      incoming.energy += energyAdded;
    }
  };

  battle.start();
  const initialState = snapshot();
  try {
    pokemon.forEach(requireSupported);
  } catch (error) {
    if (!(error instanceof UnsupportedMechanic)) throw error;
    finish("unsupported");
  }

  function member(poke) {
    return {species: poke.speciesId, hp: poke.hp, max_hp: poke.stats.hp,
      energy_points: poke.energy, buffs: poke.statBuffs.slice(), cooldown_ms: poke.cooldown};
  }
  function sideState(index) {
    const side = sides[index];
    return {team: side.team.map(member), active_slot: side.activeSlot,
      shields: side.shields, switch_timer_ms: side.switchTimer};
  }
  function snapshot() {
    return {turn: battle.getTurns(), sides: [sideState(0), sideState(1)]};
  }
  function phase() {
    if (result) return "done";
    if (shieldPrompt) return "shield";
    return pokemon.some(poke => poke.hp === 0) ? "replace" : "turn";
  }
  function legalActions(index) {
    const own = pokemon[index];
    const side = sides[index];
    const currentPhase = phase();
    if (currentPhase === "done") return [];
    if (currentPhase === "shield") {
      return shieldPrompt.defender === index ? ["shield_yes", "shield_no"] : ["wait"];
    }
    const switches = side.team.flatMap((poke, slot) =>
      slot !== side.activeSlot && poke.hp > 0 ? ["switch_" + slot] : []);
    if (currentPhase === "replace") return own.hp === 0 ? switches : ["wait"];
    if (own.cooldown > TURN_MS) return ["wait"];
    const available = ["wait"];
    if (side.switchTimer <= TURN_MS) available.push(...switches);
    if (!lastCharged) {
      available.push("fast");
      own.chargedMoves.forEach((move, slot) => {
        if (own.energy >= move.energy) available.push("charge_" + slot);
      });
    }
    return available;
  }
  function observe(index = 0) {
    if (result) return null;
    if (index !== 0 && index !== 1) throw Error("Invalid side");
    const own = sideState(index);
    own.team.forEach((entry, slot) => {
      const poke = sides[index].team[slot];
      const row = sides[index].rows[slot];
      entry.combatant_id = row.combatant_id;
      entry.fast_move = poke.fastMove.moveId;
      entry.charged_moves = poke.chargedMoves.map(
        move => ({move_id: move.moveId, energy_cost: move.energy}));
    });
    const enemy = sides[1 - index];
    const observed = Array.from(enemy.revealed).map(slot => {
      const poke = enemy.team[slot];
      return {species: poke.speciesId, fainted: poke.hp === 0,
        hp_bucket_5pct: Math.round(poke.hp / poke.stats.hp * 20),
        seen_moves: Array.from(enemy.seenMoves[slot])};
    });
    return {schema: VERSION, phase: phase(), ruleset_id: handoff.ruleset_id,
      turn: battle.getTurns(), elapsed_ms: elapsed, own,
      opponent: {active_species: pokemon[1 - index].speciesId,
        shields: enemy.shields, revealed: observed},
      legal_actions: legalActions(index),
      recent_events: events.slice(-RECENT_EVENTS).map(event =>
        ({...event, actor: event.actor === index ? "self" : "opponent"}))};
  }
  function response() {
    return {observation: observe(), reward: result?.reward ?? null,
      terminated: Boolean(result?.terminated), truncated: Boolean(result?.truncated),
      info: {schema: VERSION, outcome: result?.outcome ?? null,
        turns: battle.getTurns() - 1, elapsed_ms: elapsed,
        training_eligible: Boolean(result?.terminated), live_reproducibility: "not_verified"}};
  }
  function finish(outcome, reward = null) {
    result = {outcome, reward, terminated: reward !== null, truncated: reward === null};
    return response();
  }
  function concludeTurn() {
    if (chargesThisTurn === 0) elapsed += TURN_MS;
    lastCharged = chargesThisTurn > 0;
    const remaining = sides.map(side => side.team.some(poke => poke.hp > 0));
    pokemon.forEach(poke => {
      if (poke.hp === 0) emit("faint", poke.index, {species: poke.speciesId});
    });
    // Only a resolved KO can award a result; ending on the clock by itself
    // cannot supply a training label.
    if (!remaining[0] || !remaining[1]) {
      if (!remaining[0] && !remaining[1]) return finish("simultaneous_ko", 0);
      return remaining[0] ? finish("self_ko_win", 1) : finish("opponent_ko_win", -1);
    }
    if (elapsed === BATTLE_MS || battle.getTurns() - 1 >= horizon) return finish("timeout");
    if (pokemon.some(poke => poke.hp === 0)) {
      battle.getQueuedActions().length = 0;
      pokemon.forEach(poke => { poke.cooldown = 0; });
    }
    return response();
  }
  function step(actions) {
    const currentPhase = phase();
    if (result || !Array.isArray(actions) || actions.length !== 2 ||
        ![0, 1].every(index => legalActions(index).includes(actions[index]))) {
      throw Error("Illegal action for current team decision");
    }
    decisions.push({turn: battle.getTurns(), phase: currentPhase, actions: actions.slice()});
    try {
      if (currentPhase === "replace") {
        actions.forEach((action, index) => {
          if (action === "wait") return;
          const native = new TimelineAction("switch", index, battle.getTurns(),
            Number(action.at(-1)), {priority: 0});
          native.valid = true;
          battle.processAction(native, pokemon[index], pokemon[1 - index]);
        });
        pokemon.forEach(poke => { poke.cooldown = 0; });
        return response();
      }
      if (currentPhase === "shield") {
        shieldPrompt.useShield = actions[shieldPrompt.defender] === "shield_yes";
      } else {
        selected = actions.slice();
        chargesThisTurn = 0;
      }
      battle.step();
      return shieldPrompt ? response() : concludeTurn();
    } catch (error) {
      if (error instanceof BattleClockExpired) {
        elapsed = BATTLE_MS;
        return finish("timeout");
      }
      if (error instanceof UnsupportedMechanic) return finish("unsupported");
      throw error;
    }
  }
  // Trusted replay/audit output includes both sides. Never pass this to a
  // selector, tactical policy or public step response.
  function privateReplay() {
    return structuredClone({schema: VERSION, ruleset_id: handoff.ruleset_id,
      game_data_sha256: dataHash, seed, horizon,
      handoff, initial_conditions: initial, starting_shields: shields, initial: initialState,
      decisions, randomness, events, state: snapshot(), result,
      ...(entryStudy === null ? {} : {studied_entry: studiedEntry})});
  }
  return Object.freeze({observe, step, response, privateReplay});
}

function chooseTeamCpu(view) {
  const legal = view.legal_actions;
  if (legal.includes("shield_yes")) {
    const active = view.own.team[view.own.active_slot];
    return active.hp / active.max_hp >= 0.25 ? "shield_yes" : "shield_no";
  }
  const switches = legal.filter(action => action.startsWith("switch_"));
  if (view.phase === "replace") return switches[0] ?? "wait";
  const charge = legal.find(action => action.startsWith("charge_"));
  if (charge) return charge;
  const active = view.own.team[view.own.active_slot];
  if (active.hp / active.max_hp < 0.25 && switches.length) return switches[0];
  return legal.includes("fast") ? "fast" : "wait";
}

module.exports = {createTeamSession, chooseTeamCpu};
