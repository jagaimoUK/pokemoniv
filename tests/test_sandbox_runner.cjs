"use strict";

const assert = require("node:assert/strict");
const {spawnSync} = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
process.env.PVP_PVPOKE_SOURCE = path.join(root, "vendor/pvpoke");
const {runSandbox} = require("../pvpoke_sandbox_runner.js");
const [quagsire, , azumarill, , , wigglytuff] = require("./fixtures/strategy_rows.json");
const fixture = path.join(__dirname, "fixtures/strategy_gamemaster.json");

function request(overrides = {}) {
  return {
    gamemaster_path: fixture, self: quagsire, opponent: azumarill, shields: [0, 0],
    initial: [{}, {}], actions: [], shield_decisions: [], ...overrides
  };
}

function action(id, actor, turn, kind, moveId) {
  return {id, actor, turn, kind, ...(moveId === undefined ? {} : {move_id: moveId})};
}

function shield(actionId, defender = 1, useShield = true) {
  return {action_id: actionId, defender, use_shield: useShield};
}

function traces(result, id) {
  return result.trace.filter(entry => entry.action_id === id);
}

test("an explicit fast move starts before its native damage turn", () => {
  const result = runSandbox(request({
    initial: [{hp_points: 72, energy_points: 10, buffs: [2, -1]}, {}],
    actions: [action("fast", 0, 1, "fast", "MUD_SHOT"), action("busy", 0, 2, "wait")]
  }));

  assert.deepEqual(result.initial[0], {hp: 72, max_hp: 164, energy_points: 10, shields: 0, buffs: [2, -1]});
  assert.deepEqual(result.action_results, [
    {action_id: "fast", requested_turn: 1, status: "executed", executed_turn: 1},
    {action_id: "busy", requested_turn: 2, status: "rejected", reason: "fast_move_cooldown"}
  ]);
  const [start, resolve, effects] = traces(result, "fast");
  assert.deepEqual([start, resolve, effects].map(entry => [entry.phase, entry.turn]),
    [["start", 1], ["resolve", 2], ["effects", 2]]);
  assert.deepEqual(start.before, result.initial);
  assert.deepEqual(start.after, start.before);
  assert.equal(resolve.before[0].energy_points, 10);
  assert.ok(resolve.after[0].energy_points > 10);
  assert.deepEqual(effects.before, resolve.after);
  assert.equal(result.events.find(entry => entry.action_id === "fast").damage, resolve.actual_damage);
  assert.ok(result.trace.every((entry, i) => entry.sequence === i && (i === 0 || result.trace[i - 1].turn <= entry.turn)));
});

test("a rejected charged move keeps the native fallback fast move separate", () => {
  const result = runSandbox(request({
    shields: [0, 1], actions: [action("too-early", 0, 1, "charged", "AQUA_TAIL")],
    shield_decisions: [shield("too-early")]
  }));
  assert.deepEqual(result.action_results, [
    {action_id: "too-early", requested_turn: 1, status: "rejected", reason: "insufficient_energy"}
  ]);
  assert.deepEqual(result.shield_results, [
    {action_id: "too-early", defender: 1, requested: true, used: null, reason: "action_not_resolved"}
  ]);
  const fallback = result.events.find(entry => entry.actor === 0);
  assert.equal(fallback.move_id, "MUD_SHOT");
  assert.equal(fallback.turn, 2);
  assert.equal(fallback.action_id, undefined);
  assert.equal(result.events.some(entry => entry.kind === "charged"), false);
  assert.equal(traces(result, "too-early").length, 0);
});

test("wait and the native post-charged turn lock preserve scripted turns", () => {
  const result = runSandbox(request({
    initial: [{energy_points: 100}, {}],
    actions: [
      action("wait", 0, 1, "wait"), action("first", 0, 2, "charged", "AQUA_TAIL"),
      action("locked", 0, 3, "charged", "AQUA_TAIL"), action("second", 0, 4, "charged", "AQUA_TAIL")
    ]
  }));
  assert.deepEqual(result.action_results.map(item => [item.status, item.executed_turn ?? item.reason]),
    [["executed", 1], ["executed", 2], ["rejected", "post_charged_lock"], ["executed", 4]]);
  assert.deepEqual(traces(result, "wait").map(entry => entry.phase), ["start"]);
  assert.deepEqual(result.events.filter(entry => entry.kind === "charged").map(entry => [entry.action_id, entry.turn]),
    [["first", 2], ["second", 4]]);
});

test("per-attack shield decisions distinguish use, exhaustion and opting out", () => {
  const result = runSandbox(request({
    shields: [0, 1], initial: [{energy_points: 100}, {}],
    actions: [
      action("skip", 0, 1, "charged", "AQUA_TAIL"), action("use", 0, 3, "charged", "AQUA_TAIL"),
      action("empty", 0, 9, "charged", "AQUA_TAIL")
    ],
    shield_decisions: [shield("skip", 1, false), shield("use"), shield("empty")]
  }));
  assert.deepEqual(result.shield_results, [
    {action_id: "skip", defender: 1, requested: false, used: false},
    {action_id: "use", defender: 1, requested: true, used: true},
    {action_id: "empty", defender: 1, requested: true, used: false, reason: "no_shields"}
  ]);
  assert.deepEqual(result.shields_used, [0, 1]);
  assert.equal(result.events.find(entry => entry.action_id === "use").damage, 1);
});

test("simultaneous charges follow native attack priority and an equal attack can draw", () => {
  const initial = Array.from({length: 2}, () => ({hp_points: 1, energy_points: 100}));
  const result = runSandbox(request({
    self: azumarill, opponent: quagsire, initial,
    actions: [
      action("lower", 0, 1, "charged", "ICE_BEAM"), action("higher", 1, 1, "charged", "AQUA_TAIL"),
      action("later", 1, 4, "wait")
    ],
    shield_decisions: [shield("lower")]
  }));
  assert.equal(result.outcome, "opponent_win");
  assert.deepEqual(result.action_results.map(item => [item.status, item.executed_turn ?? item.reason]),
    [["rejected", "knocked_out"], ["executed", 1], ["not_reached", "battle_ended"]]);
  assert.deepEqual(result.events.map(entry => [entry.action_id, entry.damage]), [["higher", 1]]);
  assert.equal(result.shield_results[0].used, null);

  const draw = runSandbox(request({
    opponent: quagsire, initial,
    actions: [action("self", 0, 1, "charged", "AQUA_TAIL"), action("opponent", 1, 1, "charged", "AQUA_TAIL")]
  }));
  assert.equal(draw.outcome, "simultaneous_ko");
  assert.deepEqual(draw.events.map(entry => [entry.action_id, entry.target_hp]), [["self", 0], ["opponent", 0]]);
  assert.equal(draw.rating, 500);
});

test("a guaranteed buff is visible after native damage resolution", () => {
  const result = runSandbox(request({
    self: wigglytuff, initial: [{energy_points: 100}, {}],
    actions: [action("debuff", 0, 1, "charged", "ICY_WIND")]
  }));
  const [start, resolve, effects] = traces(result, "debuff");
  assert.deepEqual(start.before[1].buffs, [0, 0]);
  assert.ok(resolve.after[1].hp < start.before[1].hp);
  assert.deepEqual(resolve.after[1].buffs, [0, 0]);
  assert.deepEqual(effects.before, resolve.after);
  assert.deepEqual(effects.after[1].buffs, [-1, 0]);
  assert.equal(effects.after[1].hp, resolve.after[1].hp);
});

test("the native time limit leaves later turns unreached", () => {
  const actions = [];
  for (let turn = 1; turn <= 482; turn++) {
    for (const actor of [0, 1]) actions.push(action(`${actor}-${turn}`, actor, turn, "wait"));
  }
  const result = runSandbox(request({actions}));
  assert.equal(result.outcome, "timeout");
  assert.equal(result.turns, 481);
  assert.equal(result.elapsed_ms, 240500);
  assert.deepEqual(result.initial, result.terminal);
  assert.equal(result.events.length, 0);
  assert.deepEqual(result.action_results.slice(-2).map(item => [item.status, item.reason]),
    [["not_reached", "simulation_timeout"], ["not_reached", "simulation_timeout"]]);
});

test("the CLI rejects dynamic forms and returns one JSON result on success", t => {
  const runner = path.join(root, "pvpoke_sandbox_runner.js");
  const execute = input => spawnSync(process.execPath, [runner], {input: JSON.stringify(input), encoding: "utf8"});
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "sandbox-fixture-"));
  t.after(() => fs.rmSync(directory, {recursive: true, force: true}));
  const gameMasterPath = path.join(directory, "gamemaster.json");
  const gameMaster = JSON.parse(fs.readFileSync(fixture, "utf8"));
  const aquaTail = gameMaster.moves.find(move => move.moveId === "AQUA_TAIL");
  aquaTail.tags = ["instant"];
  fs.writeFileSync(gameMasterPath, JSON.stringify(gameMaster));
  const input = request({
    gamemaster_path: gameMasterPath, shields: [0, 1], initial: [{energy_points: 100}, {}],
    actions: [action("instant", 0, 1, "charged", "AQUA_TAIL")], shield_decisions: [shield("instant")]
  });
  const success = execute(input);
  assert.equal(success.status, 0, success.stderr);
  assert.equal(success.stdout.trim().split("\n").length, 1);
  assert.deepEqual(JSON.parse(success.stdout).shield_results, [
    {action_id: "instant", defender: 1, requested: true, used: false, reason: "unshieldable"}
  ]);

  aquaTail.formChange = {alternativeFormId: "azumarill"};
  fs.writeFileSync(gameMasterPath, JSON.stringify(gameMaster));
  const unsupported = execute(input);
  assert.equal(unsupported.status, 3);
  assert.equal(unsupported.stdout, "");
  assert.equal(unsupported.stderr.trim(), "unsupported_dynamic_form");
});

test("a shield decision cannot refer to a friendly, fast, or duplicate action", () => {
  const actions = [action("fast", 0, 1, "fast", "MUD_SHOT"), action("charged", 0, 4, "charged", "AQUA_TAIL")];
  for (const decisions of [[shield("fast")], [shield("charged", 0)], [shield("charged"), shield("charged")]]) {
    assert.throws(() => runSandbox(request({actions, shield_decisions: decisions})), /Invalid Sandbox shield decision/);
  }
});
