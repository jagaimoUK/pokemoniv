"use strict";
// Offline tournament-sourced trial. Starting shields are set on the native session.
const {readFileSync} = require("node:fs");
const {join} = require("node:path");
const {createTeamSession, chooseTeamCpu} = require("../pvpoke_rl_team_native.js");
const {compareChargeFork, publicChargeState, runBankedChargeArm, summarizeChargeArm} =
  require("./rl_charge_branches.cjs");

const GAMEMASTER = join(__dirname, "..", "tests", "fixtures", "strategy_gamemaster.json");
const WORLDS_RULESET = "play-pokemon-worlds-2026-gl";

function compareCase({
  handoff, seed, role, target_slot: targetSlot, opponent_shields: opponentShields,
  expected_opponent_shields: expectedOpponentShields, roster,
}) {
  const studied = handoff?.own_team?.[targetSlot];
  if (handoff?.ruleset_id !== WORLDS_RULESET || !["lead", "closer"].includes(role) ||
      targetSlot !== (role === "lead" ? 0 : 2) ||
      studied?.species !== "azumarill" || studied?.fast !== "BUBBLE" ||
      studied?.charged1 !== "PLAY_ROUGH" || studied?.charged2 !== "HYDRO_PUMP" ||
      ![0, 1, 2].includes(opponentShields) ||
      (expectedOpponentShields !== null && expectedOpponentShields !== opponentShields)) {
    throw Error("Unexpected Azumarill study fixture");
  }
  const {immediate, alternatives} = compareChargeFork(
    choice => runBankedChargeArm(
      createTeamSession(handoff, {gamemasterPath: GAMEMASTER, seed, shields: [2, opponentShields]}),
      chooseTeamCpu, targetSlot, expectedOpponentShields, choice,
    ),
    ["charge_1"],
  );
  const metadata = {seed, role, roster, planned_starting_opponent_shields: opponentShields};
  if (!immediate.chargeFork) return {...metadata, excluded: immediate.excluded};
  return {...metadata, public_state: publicChargeState(immediate.chargeFork.view),
    play_rough: summarizeChargeArm(immediate, "PLAY_ROUGH"),
    hydro_pump: summarizeChargeArm(alternatives.charge_1, "HYDRO_PUMP")};
}

if (require.main === module) {
  try {
    const cases = JSON.parse(readFileSync(0, "utf8"));
    if (!Array.isArray(cases) || cases.length < 1 || cases.length > 24) throw Error("Invalid study size");
    process.stdout.write(JSON.stringify(cases.map(compareCase)));
  } catch (error) {
    process.stderr.write("Azumarill tournament charge study failed integrity or input checks\n");
    process.exitCode = 1;
  }
}
