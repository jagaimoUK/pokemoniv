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

test("profileBoundaries includes 3rd charged move damage for Mega candidate and opponent", () => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), "pvpoke-mega-c3-"));
  try {
    const filename = path.join(temp, "gamemaster.json");
    const gameMaster = JSON.parse(fs.readFileSync(gamemaster_path, "utf8"));
    gameMaster.moves.push(
      {moveId: "MEGA_LOW", name: "Mega Low", type: "water", power: 50, energy: 35, energyGain: 0, cooldown: 500, turns: 1},
      {moveId: "MEGA_MID", name: "Mega Mid", type: "ground", power: 70, energy: 45, energyGain: 0, cooldown: 500, turns: 1},
      {moveId: "MEGA_EXTRA_PLUS", name: "Mega Extra+", type: "dragon", power: 95, energy: 65, energyGain: 0, cooldown: 500, turns: 1, isMegaMove: true}
    );
    const baseStats = {atk: 141, def: 136, hp: 137};
    gameMaster.pokemon.push({
      speciesId: "sableye_mega",
      speciesName: "Sableye (Mega)",
      dex: 302,
      types: ["dark", "ghost"],
      baseStats,
      fastMoves: ["SHADOW_CLAW"],
      chargedMoves: ["MEGA_LOW", "MEGA_MID"],
      extraChargedMoves: ["MEGA_EXTRA_PLUS"],
      tags: ["mega"]
    });
    fs.writeFileSync(filename, JSON.stringify(gameMaster));

    const megaRow = {
      species: "sableye_mega",
      fast: "SHADOW_CLAW",
      charged1: "MEGA_LOW",
      charged2: "MEGA_MID",
      charged3: "MEGA_EXTRA_PLUS",
      mega_level: 4,
      atk: 0, def: 15, hp: 15,
      level: 49.5, cp: 1499
    };
    const profiles = profileBoundaries({
      gamemaster_path: filename,
      candidates: [megaRow],
      conditions: [
        {opponent: clodsire, buffs: [[0, 0], [0, 0]]},
        {opponent: megaRow, buffs: [[0, 0], [0, 0]]}
      ]
    });
    assert.equal(profiles[0][0].length, 9);
    assert.equal(profiles[0][1].length, 10);

    const megaLv1 = {...megaRow, mega_level: 1};
    const profilesLv1 = profileBoundaries({
      gamemaster_path: filename,
      candidates: [megaLv1],
      conditions: [{opponent: clodsire, buffs: [[0, 0], [0, 0]]}]
    });
    assert.ok(profiles[0][0][8] > profilesLv1[0][0][8], "mega_level=4 should deal more isMegaMove damage than mega_level=1");
  } finally {
    fs.rmSync(temp, {recursive: true, force: true});
  }
});

test("ActionLogic.decideRandomAction handles CHARGED_MOVE_2 for 3rd charged move", () => {
  const vm = require("node:vm");
  const pvpokeDir = path.join(root, "vendor/pvpoke/src/js");
  const context = {console, Math, Array, Object, Number, String, Boolean};
  vm.createContext(context);
  for (const rel of [
    "battle/timeline/TimelineAction.js",
    "training/DecisionOption.js",
    "battle/DamageCalculator.js",
    "battle/actions/ActionLogic.js"
  ]) {
    vm.runInContext(fs.readFileSync(path.join(pvpokeDir, rel), "utf8"), context, {filename: rel});
  }
  const ActionLogic = vm.runInContext("ActionLogic", context);
  const origChoose = ActionLogic.chooseOption;
  ActionLogic.chooseOption = options => {
    const opt = options.find(o => o.name === "CHARGED_MOVE_2");
    assert.ok(opt, "CHARGED_MOVE_2 option must be offered");
    return opt;
  };
  try {
    const m0 = {moveId: "M0", energy: 35, power: 50, type: "water", category: "charged", stab: 1, damageMethod: "default"};
    const m1 = {moveId: "M1", energy: 45, power: 70, type: "ground", category: "charged", stab: 1, damageMethod: "default"};
    const m2 = {moveId: "M2", energy: 65, power: 95, type: "dragon", category: "charged", stab: 1, damageMethod: "default", isMegaMove: true};
    const poke = {
      index: 0, energy: 100, priority: 0, megaLevel: 4,
      chargedMoves: [m2, m0, m1],
      activeChargedMoves: [m0, m1, m2],
      bestChargedMove: m2,
      hasTag: t => t === "mega",
      getEffectiveStat: () => 150
    };
    const opp = {
      hp: 160, shields: 0,
      typeEffectiveness: {water: 1, ground: 1, dragon: 1},
      getEffectiveStat: () => 120
    };
    const battle = {getTurns: () => 5};
    const action = ActionLogic.decideRandomAction(battle, poke, opp);
    assert.ok(action, "decideRandomAction must return a TimelineAction for CHARGED_MOVE_2");
    assert.equal(action.type, "charged");
    assert.equal(action.value, 0, "action.value must resolve to index of activeChargedMoves[2] in chargedMoves");
  } finally {
    ActionLogic.chooseOption = origChoose;
  }
});

