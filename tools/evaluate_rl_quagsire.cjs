"use strict";
// Offline 3v3 worker. Only the public fork state and verified outcomes leave it.
const {readFileSync} = require("node:fs");
const {createTeamSession, chooseTeamCpu} = require("../pvpoke_rl_team_native.js");
const {compareChargeFork, publicChargeState, runBankedChargeArm, summarizeChargeArm} =
  require("./rl_charge_branches.cjs");

const RULESETS = new Set(["play-pokemon-worlds-2026-gl", "play-pokemon-cs-2026-11-16-gl"]);

function compareCase({handoff, seed, roster, opponent_shields: opponentShields}, gamemasterPath) {
  const lead = handoff.own_team[0];
  if (!RULESETS.has(handoff.ruleset_id) || !["quagsire", "quagsire_shadow"].includes(lead.species) ||
      lead.roster_clause_id !== "quagsire" || lead.fast !== "MUD_SHOT" ||
      lead.charged1 !== "AQUA_TAIL" || !["MUD_BOMB", "STONE_EDGE"].includes(lead.charged2) ||
      ![0, 1, 2].includes(opponentShields)) {
    throw Error("Unexpected Quagsire study fixture");
  }
  const metadata = {
    ruleset_id: handoff.ruleset_id, seed, roster, species: lead.species,
    second_move: lead.charged2, starting_opponent_shields: opponentShields,
  };
  const {immediate, alternatives} = compareChargeFork(
    choice => runBankedChargeArm(
      createTeamSession(handoff, {gamemasterPath, seed, shields: [2, opponentShields]}),
      chooseTeamCpu, 0, opponentShields, choice,
    ),
    ["charge_1"],
  );
  if (!immediate.chargeFork) return {...metadata, excluded: immediate.excluded};
  return {...metadata, public_state: publicChargeState(immediate.chargeFork.view),
    aqua_tail: summarizeChargeArm(immediate, lead.charged1),
    second_charge: summarizeChargeArm(alternatives.charge_1, lead.charged2)};
}

try {
  const cases = JSON.parse(readFileSync(0, "utf8"));
  const gamemasterPath = process.argv[2];
  if (!gamemasterPath || !Array.isArray(cases) || cases.length < 1 || cases.length > 144) {
    throw Error("Invalid study input");
  }
  process.stdout.write(JSON.stringify(cases.map(row => compareCase(row, gamemasterPath))));
} catch (error) {
  process.stderr.write(`Quagsire study failed: ${error.message}\n`);
  process.exitCode = 1;
}
