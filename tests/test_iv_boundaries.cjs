"use strict";

const assert = require("node:assert/strict");
const {spawnSync} = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const {test} = require("node:test");

const root = path.resolve(__dirname, "..");
process.env.PVP_PVPOKE_SOURCE = path.join(root, "vendor/pvpoke");
const {profileBoundaries} = require("../pvpoke_iv_boundaries.js");
const {strategyRunner} = require("../pvpoke_node_matrix.js");
const [quagsire, clodsire, azumarill] = require("./fixtures/strategy_rows.json");
const gamemaster_path = path.join(__dirname, "fixtures/strategy_gamemaster.json");
const conditions = [
  {opponent: clodsire, buffs: [[0, 0], [0, 0]]},
  {opponent: clodsire, buffs: [[2, 1], [-1, -1]]},
  {opponent: clodsire, buffs: [[0, 0], [0, 0]]}
];
const request = {gamemaster_path, candidates: [quagsire, clodsire, azumarill], conditions};

test("matches the pinned battle runner's initial HP, fast hits and unshielded charged hits", () => {
  const profiles = profileBoundaries(request);
  assert.deepEqual(profiles.map(row => row[0].slice(0, 2)), [[164, 1], [213, 0], [196, -1]]);
  assert.deepEqual(profiles[0][0], [164, 1, 4, 2, 62, 37, 34, 78]);
  assert.deepEqual(profiles.map(row => row[2]), profiles.map(row => row[0]));

  for (const [index, {opponent, buffs}] of conditions.entries()) {
    const profile = profiles[0][index];
    const setup = {self: quagsire, opponent, shields: [0, 0]};
    const fast = strategyRunner().run({...setup, attack_policies: ["fast_only", "fast_only"],
      initial: buffs.map(stages => ({buffs: stages}))});
    assert.equal(profile[0], fast.initial[0].max_hp);
    assert.equal(profile[2], fast.events.find(event => event.kind === "fast" && event.actor === 0).damage);
    assert.equal(profile[3], fast.events.find(event => event.kind === "fast" && event.actor === 1).damage);

    for (const actor of [0, 1]) {
      for (const slot of [0, 1]) {
        const runner = strategyRunner({ActionLogic: {decideAction(battle, pokemon) {
          const turn = battle.getTurns();
          const charged = turn === 1 && pokemon.index === actor;
          return new TimelineAction(charged ? "charged" : "fast", pokemon.index, turn, slot,
            {priority: pokemon.priority});
        }}});
        const result = runner.run({...setup, boundary_after_turns: 1,
          initial: buffs.map((stages, side) => ({buffs: stages, energy_points: side === actor ? 100 : 0}))});
        const hit = result.events.find(event => event.kind === "charged" && event.actor === actor);
        assert.equal(hit.damage, profile[4 + actor * 2 + slot]);
      }
    }
  }
});

test("CMP compares unmodified Attack when stat stages reverse effective Attack ordering", () => {
  const buffs = [[-4, 0], [4, 0]];
  const req = {...request, candidates: [quagsire], conditions: [{opponent: clodsire, buffs}]};
  assert.equal(profileBoundaries(req)[0][0][1], 1);
  const runner = strategyRunner({ActionLogic: {decideAction(battle, pokemon) {
    const turn = battle.getTurns();
    return new TimelineAction(turn === 1 ? "charged" : "fast", pokemon.index, turn, 0,
      {priority: pokemon.priority});
  }}});
  const result = runner.run({self: quagsire, opponent: clodsire, shields: [0, 0], boundary_after_turns: 1,
    initial: buffs.map(stages => ({buffs: stages, energy_points: 100}))});
  assert.equal(result.events.find(event => event.kind === "charged").actor, 0);
});

test("rejects inconsistent CP, unsupported forms and out-of-bounds conditions", () => {
  assert.throws(() => profileBoundaries({...request, candidates: [{...quagsire, cp: 1499}]}), /CP mismatch/);
  assert.throws(() => profileBoundaries({...request, conditions: Array(7).fill(conditions[0])}), /Invalid boundary profiler request/);
  assert.throws(() => profileBoundaries({...request, conditions: [{opponent: clodsire, buffs: [[5, 0], [0, 0]]}]}), /Invalid initial stat stages/);
  assert.throws(() => profileBoundaries({...request, candidates: [{...quagsire, charged1: "BUBBLE"}]}), /Unsupported moveset/);

  const temp = fs.mkdtempSync(path.join(os.tmpdir(), "pvpoke-boundaries-"));
  try {
    const filename = path.join(temp, "gamemaster.json");
    const gameMaster = JSON.parse(fs.readFileSync(gamemaster_path, "utf8"));
    gameMaster.pokemon.find(entry => entry.speciesId === "quagsire").formChange = {trigger: "activate_charged"};
    fs.writeFileSync(filename, JSON.stringify(gameMaster));
    assert.throws(() => profileBoundaries({...request, gamemaster_path: filename}), /Unsupported dynamic form: quagsire/);
  } finally {
    fs.rmSync(temp, {recursive: true, force: true});
  }
});

test("CLI accepts one request and emits only the nested profile array", () => {
  const expected = profileBoundaries(request);
  const run = spawnSync(process.execPath, [path.join(root, "pvpoke_iv_boundaries.js")],
    {input: JSON.stringify(request), encoding: "utf8"});
  assert.equal(run.status, 0, run.stderr);
  assert.deepEqual(JSON.parse(run.stdout), expected);
});
