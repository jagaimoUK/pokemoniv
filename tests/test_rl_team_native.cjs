"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");
const os = require("node:os");
const vm = require("node:vm");
const root = path.resolve(__dirname, "..");
process.env.PVP_PVPOKE_SOURCE = path.join(root, "vendor/pvpoke");
const {createTeamSession, chooseTeamCpu} = require("../pvpoke_rl_team_native.js");
const {createPokemon, loadMaster} = require("../pvpoke_node_matrix.js");
const rows = require("./fixtures/strategy_rows.json");
const gt = path.join(__dirname, "fixtures", "strategy_gamemaster.json");

function handoff(left = [0, 1, 4], right = [2, 3, 5]) {
  const pick = (slots, side) => slots.map(i => ({
    ...rows[i], combatant_id: side + i, roster_clause_id: rows[i].species,
  }));
  return {schema: "rl-private-3v3-handoff-v1", ruleset_id: "great-league-v1",
    own_team: pick(left, "self"), opponent_team: pick(right, "enemy")};
}
function game(input = handoff(), options = {}) {
  return createTeamSession(input, {gamemasterPath: gt, seed: 0, ...options});
}
const wait = ["wait", "wait"];
function state(session, side = 0, slot) {
  const data = session.privateReplay().state.sides[side];
  return data.team[slot ?? data.active_slot];
}
function moves(session) {
  return session.privateReplay().events.filter(e => e.kind === "fast" || e.kind === "charged");
}

{
  // Ordinary switch preserves HP and energy, removes stages, and starts the
  // full cooldown. The original lead can act with banked energy on return.
  const s = game(handoff(), {initial: [[{hp_points: 80, energy_points: 72, buffs: [2, -1]}], []]});
  s.step(["switch_1", "wait"]);
  let own = s.observe().own;
  assert.equal(own.active_slot, 1);
  assert.equal(own.switch_timer_ms, 45000);
  assert.deepEqual(state(s, 0, 0), {species: "quagsire", hp: 80, max_hp: state(s, 0, 0).max_hp,
    energy_points: 72, buffs: [0, 0], cooldown_ms: 0});
  assert.throws(() => s.step(["switch_0", "wait"]), /Illegal action/);
  assert.equal(s.privateReplay().decisions.length, 1);
  for (let i = 0; i < 88; i++) s.step(wait);
  assert.equal(s.observe().own.switch_timer_ms, 1000);
  assert(!s.observe().legal_actions.includes("switch_0"));
  s.step(wait);
  assert.equal(s.observe().own.switch_timer_ms, 500);
  assert(s.observe().legal_actions.includes("switch_0"));
  s.step(["switch_0", "wait"]);
  own = s.observe().own;
  assert.equal(own.active_slot, 0);
  assert.equal(own.switch_timer_ms, 45000);
  assert(s.observe().legal_actions.includes("charge_1"));
}

{
  // A held turn is resumed twice when both chosen charges go to shields.
  // Neither player gets the incoming move name before committing.
  const s = game(handoff(), {initial: [[{energy_points: 100}], [{energy_points: 100}]]});
  const first = s.step(["charge_0", "charge_0"]);
  assert.equal(first.observation.phase, "shield");
  assert.equal(first.observation.turn, 1);
  assert.equal(moves(s).length, 0);
  const who = first.observation.legal_actions[0] === "shield_yes" ? 0 : 1;
  const shield = defender => defender === 0 ? ["shield_yes", "wait"] : ["wait", "shield_yes"];
  const announcement = s.observe(who).recent_events.at(-1);
  assert.equal(announcement.kind, "charge_announced");
  assert(!Object.hasOwn(announcement, "move_id"));
  const second = s.step(shield(who));
  assert.equal(second.observation.phase, "shield");
  assert.equal(second.observation.turn, 1);
  assert.equal(moves(s).length, 1);
  assert.equal(second.observation.elapsed_ms, 10000);
  assert.equal(s.privateReplay().state.sides[who].shields, 1);
  const after = s.step(shield(1 - who));
  assert.equal(after.observation.turn, 2);
  assert.equal(after.observation.elapsed_ms, 20000);
  assert.equal(moves(s).length, 2);
  assert(moves(s).every(e => e.shielded));
  assert.deepEqual(s.privateReplay().state.sides.map(side => side.shields), [1, 1]);
  assert.equal(state(s).energy_points, 65);
  assert.equal(state(s, 1).energy_points, 45);
  assert.equal(state(s).hp, state(s).max_hp - 1);
  assert(!after.observation.legal_actions.includes("fast"));
  s.step(["switch_1", "switch_1"]);
  assert.equal(s.observe().own.shields, 1);
  assert.equal(s.observe(1).own.shields, 1);
}

{
  // A fast attack already in flight hits the outgoing lead in the
  // post-charge lock. A KO invalidates the queued voluntary switch.
  for (const hp of [1, 80]) {
    const s = game(handoff(), {initial: [[{hp_points: hp, energy_points: 35}], []],
      shields: [0, 0]});
    s.step(["charge_0", "fast"]);
    assert.equal(s.observe().turn, 2);
    assert.deepEqual(moves(s).map(e => e.move_id), ["AQUA_TAIL"]);
    s.step(["switch_1", "wait"]);
    assert.deepEqual(moves(s).map(e => [e.move_id, e.turn]), [["AQUA_TAIL", 1], ["BUBBLE", 2]]);
    if (hp === 1) {
      const view = s.observe();
      assert.equal(view.phase, "replace");
      assert(!s.privateReplay().events.some(e => e.kind === "switch"));
      assert.deepEqual(view.legal_actions, ["switch_1", "switch_2"]);
      assert.equal(s.observe(1).legal_actions[0], "wait");
      s.step(["switch_2", "wait"]);
      assert.equal(s.observe().elapsed_ms, view.elapsed_ms);
      assert.equal(s.observe().turn, view.turn);
      assert.equal(s.observe().own.switch_timer_ms, 0);
      assert.equal(s.observe().own.active_slot, 2);
    } else {
      assert.equal(s.observe().own.active_slot, 1);
      assert(state(s, 0, 0).hp < hp);
      assert.equal(state(s, 0, 1).hp, state(s, 0, 1).max_hp);
      assert.deepEqual(s.privateReplay().events.slice(-2).map(e => e.kind), ["fast", "switch"]);
    }
  }
}

{
  // Forced replacement leaves the preceding voluntary switch clock intact.
  const s = game(handoff(), {initial: [[{}, {hp_points: 1}], [{energy_points: 100}]],
    shields: [0, 0]});
  s.step(["switch_1", "charge_0"]);
  const view = s.observe();
  assert.equal(view.phase, "replace");
  assert(view.own.switch_timer_ms > 0 && view.own.switch_timer_ms < 45000);
  assert.equal(state(s, 0, 1).hp, 0);
  s.step(["switch_2", "wait"]);
  assert.equal(s.observe().own.switch_timer_ms, view.own.switch_timer_ms);
  assert.equal(s.observe().elapsed_ms, view.elapsed_ms);
}

{
  // Strictly higher attack wins CMP even when the loser has a +4 attack stage.
  // No ghost shield prompt or spending energy on a cancelled charged move.
  const s = game(handoff([2, 1, 4], [0, 3, 5]), {
    initial: [[{hp_points: 1, energy_points: 100, buffs: [4, 0]}], [{energy_points: 100}]],
    shields: [0, 2],
  });
  const response = s.step(["charge_0", "charge_0"]);
  assert.equal(response.observation.phase, "replace");
  assert.deepEqual(moves(s).map(e => e.actor), [1]);
  assert.equal(state(s, 0).energy_points, 100);
  assert.equal(s.observe().opponent.shields, 2);
  assert.equal(s.privateReplay().randomness.length, 0);

  const wins = new Set();
  for (const seed of [0, 1, 2, 3, 4, 5, 6, 7]) {
    const tied = game(handoff([0, 1, 4], [0, 3, 5]), {
      initial: [[{hp_points: 1, energy_points: 100}], [{hp_points: 1, energy_points: 100}]],
      shields: [0, 0], seed,
    });
    tied.step(["charge_0", "charge_0"]);
    assert.equal(tied.observe().phase, "replace");
    assert.equal(moves(tied).length, 1);
    wins.add(moves(tied)[0].actor);
    assert.deepEqual(tied.privateReplay().randomness.map(e => e.kind), ["cmp_tie"]);
  }
  assert.deepEqual(wins, new Set([0, 1]));
}

{
  // Both sides' already-landed fast attacks count in a simultaneous KO.
  // A 3v3 episode ends only after the third member is down on both sides.
  const low = [{hp_points: 1}, {hp_points: 1}, {hp_points: 1}];
  const s = game(handoff([0, 1, 4], [0, 1, 4]), {initial: [low, low], shields: [0, 0]});
  let result;
  for (const slot of [0, 1, 2]) {
    s.step(["fast", "fast"]);
    result = s.step(wait);
    assert.equal(moves(s).length, (slot + 1) * 2);
    if (slot < 2) {
      assert.equal(result.observation.phase, "replace");
      const next = "switch_" + (slot + 1);
      s.step([next, next]);
    }
  }
  assert.equal(result.reward, 0);
  assert.equal(result.info.outcome, "simultaneous_ko");
  assert.equal(result.info.training_eligible, true);
  assert.equal(result.terminated, true);
  assert.equal(s.privateReplay().events.filter(e => e.kind === "faint").length, 6);
  assert.throws(() => s.step(wait), /Illegal action/);
}

{
  // One side wins with remaining bench. Forced replacement cannot take a
  // fainted slot and attacking does not escape replacement.
  const s = game(handoff([0, 1, 4], [0, 1, 4]), {
    initial: [[], [{hp_points: 1}, {hp_points: 1}, {hp_points: 1}]], shields: [0, 0],
  });
  let result;
  for (let slot = 0; slot < 3; slot++) {
    s.step(["fast", "wait"]);
    result = s.step(wait);
    if (slot < 2) {
      assert.equal(result.reward, null);
      assert(!s.observe(1).legal_actions.includes("switch_0"));
      assert.throws(() => s.step(["wait", "fast"]), /Illegal action/);
      s.step(["wait", "switch_" + (slot + 1)]);
    }
  }
  assert.equal(result.reward, 1);
  assert.equal(result.info.outcome, "self_ko_win");
  assert.equal(result.observation, null);
}

{
  // Two worlds with the same visible players and different hidden bench and
  // moves produce the same observation, including at the shield frontier.
  const inputs = [handoff(), handoff([0, 1, 4], [2, 1, 4])];
  inputs[1].opponent_team[0] = {...inputs[1].opponent_team[0], charged1: "PLAY_ROUGH", charged2: "ICE_BEAM"};
  const left = game(inputs[0], {initial: [[], [{energy_points: 100}]]});
  const right = game(inputs[1], {initial: [[], [{energy_points: 100}]]});
  const changedPlayerBench = game(handoff([0, 3, 5]), {initial: [[], [{energy_points: 100}]]});
  const cpuViews = [left.observe(1), changedPlayerBench.observe(1)];
  assert.deepEqual(cpuViews[0], cpuViews[1]);
  assert.equal(chooseTeamCpu(cpuViews[0]), chooseTeamCpu(cpuViews[1]));
  assert.deepEqual(left.observe(), right.observe());
  assert.deepEqual(left.step(["wait", "charge_0"]), right.step(["wait", "charge_0"]));
  const enemy = left.observe().opponent;
  assert.deepEqual(Object.keys(enemy).sort(), ["active_species", "revealed", "shields"]);
  assert.deepEqual(Object.keys(enemy.revealed[0]).sort(), ["fainted", "hp_bucket_5pct", "seen_moves", "species"]);
  assert.deepEqual(enemy.revealed[0].seen_moves, []);
  const l = left.step(["shield_yes", "wait"]).observation;
  const r = right.step(["shield_yes", "wait"]).observation;
  assert.deepEqual(l.opponent.revealed[0].seen_moves, ["ICE_BEAM"]);
  assert.deepEqual(r.opponent.revealed[0].seen_moves, ["PLAY_ROUGH"]);
}

{
  // Differential check: exact native resources and actual move order with
  // the same inputs and shield decisions, including charged-move effects.
  const match = handoff([5, 0, 1], [4, 2, 3]);
  loadMaster(gt);
  const {Battle, TimelineAction} = vm.runInThisContext("({Battle, TimelineAction})");
  const native = new Battle();
  const active = [match.own_team[0], match.opponent_team[0]].map((row, index) => {
    const poke = createPokemon(row, index, native);
    poke.setStartEnergy(100);
    poke.setShields(2);
    native.setNewPokemon(poke, index, false);
    return poke;
  });
  const events = [];
  let nativeChoice = "charged";
  native.onMoveResolved = (actor, target, move, damage, shielded) => events.push(
    [native.getTurns(), actor.index, move.moveId, Boolean(shielded)]);
  native.actionPolicy = (battle, actor) =>
    new TimelineAction(nativeChoice, actor.index, battle.getTurns(), 0, {priority: 0, charge: 1});
  native.shieldPolicy = index => index === 0;
  native.start();
  native.step();

  const team = game(match, {initial: [[{energy_points: 100}], [{energy_points: 100}]]});
  team.step(["charge_0", "charge_0"]);
  while (team.observe().phase === "shield") {
    team.step(team.observe().legal_actions[0] === "wait" ? ["wait", "shield_no"] : ["shield_yes", "wait"]);
  }
  nativeChoice = "fast";
  for (let n = 0; n < 8; n++) {
    native.step();
    const actions = [0, 1].map(index => team.observe(index).legal_actions.includes("fast") ? "fast" : "wait");
    team.step(actions);
  }
  assert.deepEqual(moves(team).map(e => [e.turn, e.actor, e.move_id, e.shielded]), events);
  for (const i of [0, 1]) {
    const p = active[i];
    assert.deepEqual(state(team, i), {species: p.speciesId, hp: p.hp, max_hp: p.stats.hp,
      energy_points: p.energy, buffs: p.statBuffs, cooldown_ms: p.cooldown});
    assert.equal(team.observe(i).own.shields, p.shields);
  }
}

{
  // A real stochastic move uses a local recorded RNG, and a complete replay
  // reconstructs the same result on a clean engine with the same data.
  const roster = handoff();
  roster.own_team[0] = {...roster.own_team[0], species: "primeape",
    fast: "KARATE_CHOP", charged1: "NIGHT_SLASH", charged2: "RAGE_FIST",
    atk: 5, def: 15, hp: 15, level: 24, cp: 1498};
  for (const seed of [4, 42]) {
    const original = game(roster, {initial: [[{energy_points: 100}], []],
      shields: [0, 0], horizon: 4, seed});
    original.step(["charge_0", "fast"]);
    original.step(wait);
    original.step(wait);
    const end = original.step(wait);
    assert.equal(end.reward, null);
    assert.equal(end.info.outcome, "timeout");
    assert.equal(end.truncated, true);
    assert.equal(end.info.training_eligible, false);
    const audit = original.privateReplay();
    assert.deepEqual(audit.randomness.map(e => e.kind), ["move_buff"]);
    assert.equal(state(original, 0).buffs[0], seed === 4 ? 1 : 0);
    const replay = game(audit.handoff, {seed: audit.seed, horizon: audit.horizon,
      shields: audit.starting_shields, initial: audit.initial_conditions});
    audit.decisions.forEach(row => replay.step(row.actions));
    assert.deepEqual(replay.privateReplay(), audit);
  }
}

{
  // An unknown dynamic form is ignored on a hidden bench and stops a
  // trajectory without a match reward if it enters the battle.
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "team-pvpoke-"));
  try {
    const master = JSON.parse(fs.readFileSync(gt));
    master.pokemon.find(p => p.speciesId === "fearow").formChange =
      {trigger: "activate_charged", alternativeFormId: "fearow"};
    const file = path.join(dir, "gamemaster.json");
    fs.writeFileSync(file, JSON.stringify(master));
    const s = game(handoff(), {gamemasterPath: file});
    assert.deepEqual(s.observe(), game().observe());
    s.step(wait);
    const final = s.step(["wait", "switch_1"]);
    assert.equal(final.info.outcome, "unsupported");
    assert.equal(final.reward, null);
    assert.equal(final.truncated, true);
    assert.equal(final.info.training_eligible, false);
  } finally {
    fs.rmSync(dir, {recursive: true});
  }
}

{
  // The 240s budget truncates idle play, and a charge that cannot finish
  // within it never opens a shield decision or emits a resolved move.
  const idle = game();
  for (let i = 0; i < 479; i++) idle.step(wait);
  assert.equal(idle.step(wait).info.elapsed_ms, 240000);
  assert.equal(idle.response().info.outcome, "timeout");

  const late = game(handoff(), {initial: [[{energy_points: 35}], []]});
  for (let i = 0; i < 461; i++) late.step(wait);
  const result = late.step(["charge_0", "wait"]);
  assert.equal(result.info.outcome, "timeout");
  assert.equal(result.info.elapsed_ms, 240000);
  assert.equal(result.reward, null);
  assert.equal(result.truncated, true);
  assert.equal(state(late).energy_points, 35);
  assert.equal(late.privateReplay().events.length, 0);
}
