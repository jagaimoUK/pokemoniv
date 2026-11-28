"use strict";

const path = require("node:path");
const {loadMaster} = require("./pvpoke_node_matrix.js");

const CP_CAP = 1500;
const MAX_LEVEL = 50;
const MAX_TURN = 500;
const MAX_INPUT_BYTES = 256 * 1024;
const ACTION_ID = /^[A-Za-z0-9_-]{1,64}$/;
const MOVE_ID = /^[A-Z0-9_]{1,100}$/;
const SPECIES_ID = /^[a-z0-9_]{1,100}$/;

class UnsupportedDynamicForm extends Error {
  constructor() {
    super("unsupported_dynamic_form");
  }
}

function boundedInteger(value, min, max) {
  return Number.isSafeInteger(value) && value >= min && value <= max;
}

function isPair(value) {
  return Array.isArray(value) && value.length === 2;
}

function preparePokemon(row, actor, battle, gameMaster) {
  if (!row || typeof row.species !== "string" || !SPECIES_ID.test(row.species) ||
      ![row.fast, row.charged1, row.charged2].every(id => typeof id === "string" && MOVE_ID.test(id)) ||
      row.charged1 === row.charged2 || ![row.atk, row.def, row.hp].every(iv => boundedInteger(iv, 0, 15)) ||
      !Number.isFinite(row.level) || !boundedInteger(row.level * 2, 2, MAX_LEVEL * 2) ||
      !boundedInteger(row.cp, 10, CP_CAP)) {
    throw Error("Invalid prepared Pokémon row");
  }

  const data = gameMaster.getPokemonById(row.species);
  if (!data) throw Error("Unknown Sandbox species");
  if (data.formChange || (data.originalFormId && data.originalFormId !== row.species) ||
      /^(aegislash|cramorant|minior)(?:_|$)/.test(row.species)) {
    throw new UnsupportedDynamicForm();
  }

  const pokemon = new Pokemon(row.species, actor, battle);
  pokemon.ivs = {atk: row.atk, def: row.def, hp: row.hp};
  pokemon.isCustom = true;
  pokemon.setLevel(row.level, false);
  pokemon.initialize(false);
  if (pokemon.cp !== row.cp || !boundedInteger(pokemon.stats.hp, 1, 10000)) {
    throw Error("Invalid prepared Pokémon stats");
  }
  if (!pokemon.fastMovePool.some(move => move.moveId === row.fast) ||
      ![row.charged1, row.charged2].every(id => pokemon.chargedMovePool.some(move => move.moveId === id))) {
    throw Error("Invalid prepared Pokémon moveset");
  }

  pokemon.selectMove("fast", row.fast);
  pokemon.selectMove("charged", row.charged1, 0);
  pokemon.selectMove("charged", row.charged2, 1);
  const [first, second] = pokemon.chargedMoves;
  if (pokemon.fastMove?.moveId !== row.fast || pokemon.fastMove.category !== "fast" ||
      first?.moveId !== row.charged1 || first.category !== "charged" ||
      second?.moveId !== row.charged2 || second.category !== "charged") {
    throw Error("Invalid initialized Pokémon moveset");
  }
  if ([pokemon.fastMove, first, second].some(move => move.formChange)) throw new UnsupportedDynamicForm();
  return pokemon;
}

function setInitial(pokemon, initial, shields, maxBuffStages) {
  if (!initial || typeof initial !== "object" || Array.isArray(initial)) throw Error("Invalid initial state");
  const {hp_points: hp = pokemon.stats.hp, energy_points: energy = 0, buffs = [0, 0]} = initial;
  if (!boundedInteger(hp, 1, pokemon.stats.hp) || !boundedInteger(energy, 0, 100) ||
      !isPair(buffs) || !buffs.every(stage => boundedInteger(stage, -maxBuffStages, maxBuffStages))) {
    throw Error("Invalid initial state");
  }
  pokemon.setStartHp(hp);
  pokemon.setStartEnergy(energy);
  pokemon.setStartBuffs([...buffs]);
  pokemon.setShields(shields);
}

function compileActions(actions, shieldDecisions, pokemon) {
  const byId = new Map();
  const byTurn = new Map();
  const byNativeAction = new Map();

  for (const action of actions) {
    if (!action || typeof action.id !== "string" || !ACTION_ID.test(action.id) || byId.has(action.id) ||
        !boundedInteger(action.actor, 0, 1) || !boundedInteger(action.turn, 1, MAX_TURN) ||
        !["fast", "charged", "wait"].includes(action.kind)) {
      throw Error("Invalid Sandbox action");
    }
    const {id, actor, turn, kind, move_id: moveId} = action;
    const turnKey = turn * 2 + actor;
    if (byTurn.has(turnKey)) throw Error("Duplicate Sandbox action for actor and turn");

    const combatant = pokemon[actor];
    let slot = 0;
    if (kind === "charged") {
      slot = combatant.chargedMoves.slice(0, 2).findIndex(move => move.moveId === moveId);
      if (slot < 0) throw Error("Sandbox action uses an unselected charged move");
    } else if (kind === "fast" && moveId !== combatant.fastMove.moveId) {
      throw Error("Sandbox action uses an unselected fast move");
    } else if (kind === "wait" && moveId !== undefined) {
      throw Error("Sandbox wait has a move");
    }

    const nativeAction = new TimelineAction(kind, actor, turn, slot, {
      shielded: false, buffs: false, charge: 1, priority: 0
    });
    const record = {id, nativeAction, result: null};
    byId.set(id, record);
    byTurn.set(turnKey, record);
    byNativeAction.set(nativeAction, record);
  }

  // Each decision belongs to the defender. Native Sandbox reads the flag on the
  // incoming attack, so translate once without installing a shield policy hook.
  const decisions = new Map();
  for (const decision of shieldDecisions) {
    const action = byId.get(decision?.action_id)?.nativeAction;
    if (!action || action.type !== "charged" || decision.defender !== 1 - action.actor ||
        typeof decision.use_shield !== "boolean" || decisions.has(decision.action_id)) {
      throw Error("Invalid Sandbox shield decision");
    }
    action.settings.shielded = decision.use_shield;
    decisions.set(decision.action_id, {
      action_id: decision.action_id, defender: decision.defender,
      requested: decision.use_shield, used: null, reason: "action_not_resolved"
    });
  }

  return {byTurn, byNativeAction, decisions};
}

function state(pokemon) {
  return {
    hp: pokemon.hp, max_hp: pokemon.stats.hp, energy_points: pokemon.energy,
    shields: pokemon.shields, buffs: [...pokemon.statBuffs]
  };
}

function actionResult(record, status, detail) {
  record.result = {action_id: record.id, requested_turn: record.nativeAction.turn, status, ...detail};
}

function outcomeOf(terminal) {
  const [self, opponent] = terminal;
  if (self.hp === 0 && opponent.hp === 0) return "simultaneous_ko";
  if (opponent.hp === 0) return "self_win";
  if (self.hp === 0) return "opponent_win";
  return "timeout";
}

function simulate(battle, pokemon, compiled) {
  const {byTurn, byNativeAction, decisions} = compiled;
  const snapshot = () => pokemon.map(state);
  const events = [];
  const trace = [];
  const damage = [{fast: 0, charged: 0}, {fast: 0, charged: 0}];
  let initial;
  let turnContext;
  let priorTurnHadCharged = false;
  let processingAction;
  let resolvingMove;

  function addTrace(phase, turn, action, moveId, before, after, actualDamage) {
    const record = byNativeAction.get(action);
    const entry = {sequence: trace.length, turn, phase, actor: action.actor, kind: action.type, before, after};
    if (moveId !== undefined) entry.move_id = moveId;
    if (record) entry.action_id = record.id;
    if (actualDamage !== undefined) entry.actual_damage = actualDamage;
    trace.push(entry);
  }

  function recordStart(turn, action, moveId, currentState) {
    const record = byNativeAction.get(action);
    if (record) actionResult(record, "executed", {executed_turn: turn});
    addTrace("start", turn, action, moveId, currentState, currentState);
  }

  function recordFastStarts() {
    if (turnContext.fastStartsRecorded) return;
    turnContext.fastStartsRecorded = true;
    // Native creates a tap when a fast move enters the queue, even when its
    // damage lands on a later turn or a knockout prevents damage entirely.
    const timeline = battle.getTimeline();
    for (let i = turnContext.timelineStart; i < timeline.length; i++) {
      const event = timeline[i];
      if (event.type !== "tap interaction" || event.turn !== turnContext.turn) continue;
      const action = turnContext.fastProposals[event.actor];
      recordStart(event.turn, action, pokemon[event.actor].fastMove.moveId, turnContext.before);
    }
  }

  const nativeStart = battle.start.bind(battle);
  battle.start = () => {
    nativeStart();
    initial = snapshot();
  };

  const nativeStep = battle.step.bind(battle);
  battle.step = () => {
    turnContext = {
      turn: battle.getTurns(), timelineStart: battle.getTimeline().length, before: snapshot(),
      fastProposals: [], fastStartsRecorded: false, hadCharged: false
    };
    nativeStep();
    recordFastStarts();
    priorTurnHadCharged = turnContext.hadCharged;
  };

  const nativeGetAction = battle.getTurnAction.bind(battle);
  battle.getTurnAction = (actor, opponent) => {
    const action = nativeGetAction(actor, opponent);
    if (action?.type === "fast") turnContext.fastProposals[actor.index] = action;
    const planned = byTurn.get(turnContext.turn * 2 + actor.index);
    if (planned) {
      let reason;
      if (priorTurnHadCharged) reason = "post_charged_lock";
      else if (actor.cooldown > 0) reason = "fast_move_cooldown";
      else if (planned.nativeAction.type === "charged" && action !== planned.nativeAction) reason = "insufficient_energy";
      if (reason) actionResult(planned, "rejected", {reason});
    }
    return action;
  };

  const nativeProcessAction = battle.processAction.bind(battle);
  battle.processAction = (action, actor, opponent) => {
    recordFastStarts();
    const turn = battle.getTurns();
    if (action.type === "charged") turnContext.hadCharged = true;
    if (action.type !== "fast") {
      if (action.valid && !action.processed) {
        const moveId = action.type === "charged" ? actor.chargedMoves[action.value].moveId : undefined;
        recordStart(turn, action, moveId, snapshot());
      } else if (action.type === "charged" && byNativeAction.has(action)) {
        const reason = actor.hp === 0 ? "knocked_out" : "insufficient_energy";
        actionResult(byNativeAction.get(action), "rejected", {reason});
      }
    }
    processingAction = action;
    const result = nativeProcessAction(action, actor, opponent);
    processingAction = undefined;
    return result;
  };

  const nativeUseMove = battle.useMove.bind(battle);
  battle.useMove = (attacker, defender, move, ...args) => {
    resolvingMove = {before: snapshot(), afterDamage: undefined};
    nativeUseMove(attacker, defender, move, ...args);
    addTrace("effects", battle.getTurns(), processingAction, move.moveId, resolvingMove.afterDamage, snapshot());
    resolvingMove = undefined;
  };

  battle.onMoveResolved = (attacker, defender, move, actualDamage, shielded) => {
    const turn = battle.getTurns();
    const kind = move.category;
    const record = byNativeAction.get(processingAction);
    const event = {
      index: events.length, turn, actor: attacker.index, kind, move_id: move.moveId,
      damage: actualDamage, shielded: Boolean(shielded), target_hp: defender.hp
    };
    if (record) event.action_id = record.id;
    events.push(event);
    damage[attacker.index][kind] += actualDamage;

    const decision = decisions.get(record?.id);
    if (decision) {
      decision.used = event.shielded;
      delete decision.reason;
      if (decision.requested && !decision.used) {
        decision.reason = move.hasTag("instant") ? "unshieldable" : "no_shields";
      }
    }

    resolvingMove.afterDamage = snapshot();
    addTrace("resolve", turn, processingAction, move.moveId, resolvingMove.before, resolvingMove.afterDamage, actualDamage);
  };

  battle.simulate();
  const terminal = snapshot();
  const outcome = outcomeOf(terminal);
  for (const record of byNativeAction.values()) {
    if (record.result) continue;
    if (record.nativeAction.turn < battle.getTurns()) throw Error("Unclassified native Sandbox action");
    const reason = outcome === "timeout" ? "simulation_timeout" : "battle_ended";
    actionResult(record, "not_reached", {reason});
  }

  return {
    initial, terminal, turns: battle.getTurns() - 1, elapsed_ms: battle.getDuration(), outcome,
    rating: battle.getBattleRatings()[0], damage, shields_used: initial.map((side, i) => side.shields - terminal[i].shields),
    events, action_results: [...byNativeAction.values()].map(record => record.result),
    shield_results: [...decisions.values()], trace
  };
}

function runSandbox(request) {
  if (!request || typeof request.gamemaster_path !== "string" ||
      !path.isAbsolute(request.gamemaster_path) || request.gamemaster_path.length > 4096 ||
      !isPair(request.shields) || !request.shields.every(value => boundedInteger(value, 0, 2)) ||
      !isPair(request.initial) || !Array.isArray(request.actions) || request.actions.length > MAX_TURN * 2 ||
      !Array.isArray(request.shield_decisions) || request.shield_decisions.length > request.actions.length) {
    throw Error("Invalid Sandbox request");
  }

  loadMaster(request.gamemaster_path);
  const gameMaster = GameMaster.getInstance();
  const {maxBuffStages} = gameMaster.data.settings;
  if (!Number.isSafeInteger(maxBuffStages) || maxBuffStages < 0) throw Error("Invalid PvPoke buff settings");
  const battle = new Battle();
  battle.setCP(CP_CAP);
  const pokemon = [request.self, request.opponent].map((row, actor) => preparePokemon(row, actor, battle, gameMaster));
  pokemon.forEach((combatant, actor) => {
    battle.setNewPokemon(combatant, actor, false);
    setInitial(combatant, request.initial[actor], request.shields[actor], Math.min(maxBuffStages, 4));
  });
  const compiled = compileActions(request.actions, request.shield_decisions, pokemon);
  battle.setSandboxMode(true);
  battle.setActions([...compiled.byNativeAction.keys()]);
  return simulate(battle, pokemon, compiled);
}

async function main() {
  const chunks = [];
  let bytes = 0;
  for await (const chunk of process.stdin) {
    bytes += chunk.length;
    if (bytes > MAX_INPUT_BYTES) throw Error("Sandbox request is too large");
    chunks.push(chunk);
  }
  const request = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  process.stdout.write(JSON.stringify(runSandbox(request)) + "\n");
}

module.exports = {runSandbox, UnsupportedDynamicForm};
if (require.main === module) {
  main().catch(error => {
    console.error(error.message);
    process.exitCode = error instanceof UnsupportedDynamicForm ? 3 : 2;
  });
}
