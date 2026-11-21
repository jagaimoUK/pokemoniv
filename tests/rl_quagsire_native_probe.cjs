"use strict";
// Called by the Python test with its isolated overlaid GameMaster and a prepared team.
const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const {createTeamSession} = require("../pvpoke_rl_team_native.js");

const handoff = JSON.parse(readFileSync(0, "utf8"));
const gamemasterPath = process.argv[2];

function stoneEdgeDamage(species, actor) {
  const input = structuredClone(handoff);
  input.own_team[0].species = species;
  const defender = 1 - actor;
  const session = createTeamSession(input, {gamemasterPath, seed: 17,
    initial: actor === 0 ? [[{energy_points: 55}], []] : [[], [{energy_points: 55}]],
    shields: [0, 0]});
  const before = session.observe(defender).own.team[0].hp;
  const choice = actor === 0 ? ["charge_1", "wait"] : ["wait", "charge_0"];
  assert.ok(session.observe(actor).legal_actions.includes(choice[actor]));
  session.step(choice);
  const {events} = session.privateReplay();
  assert.ok(events.some(event => event.kind === "charged" && event.actor === actor &&
    event.move_id === "STONE_EDGE" && !event.shielded));
  return before - session.observe(defender).own.team[0].hp;
}

assert.deepEqual(["quagsire", "quagsire_shadow"].map(species => stoneEdgeDamage(species, 0)), [37, 44]);
assert.deepEqual(["quagsire", "quagsire_shadow"].map(species => stoneEdgeDamage(species, 1)), [34, 41]);
