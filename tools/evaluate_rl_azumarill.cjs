"use strict";
// Offline tournament-sourced trial. Starting shields are set on the native session.
const {readFileSync} = require("node:fs");
const {join} = require("node:path");
const {createTeamSession, chooseTeamCpu} = require("../pvpoke_rl_team_native.js");
const {compareChargeFork, publicChargeState, ownChargesFromFork, verifiedNativeReward} =
  require("./rl_charge_branches.cjs");

const GAMEMASTER = join(__dirname, "..", "tests", "fixtures", "strategy_gamemaster.json");
const WORLDS_RULESET = "play-pokemon-worlds-2026-gl";

function runArm(handoff, seed, opponentShields, targetSlot, expectedOpponentShields, choice) {
  const session = createTeamSession(handoff, {gamemasterPath: GAMEMASTER, seed,
    shields: [2, opponentShields]});
  let response = session.response();
  let chargeFork = null;
  for (let steps = 0; response.observation && steps < 2000; steps++) {
    const view = response.observation;
    let action = chooseTeamCpu(view);
    if (!chargeFork && view.own.team[targetSlot].hp === 0) {
      return {excluded: "target_fainted_before_fork"};
    }
    if (!chargeFork && view.phase === "turn" && view.own.active_slot === targetSlot) {
      const legal = view.legal_actions;
      if (legal.includes("charge_0") && legal.includes("charge_1")) {
        if (expectedOpponentShields !== null && view.opponent.shields !== expectedOpponentShields) {
          throw Error("Banking changed opponent shields");
        }
        chargeFork = {view, audit: session.privateReplay(), baselineAction: "charge_0"};
        action = choice === "immediate" ? "charge_0" : choice;
      } else {
        action = legal.includes("fast") ? "fast" : "wait";
      }
    }
    response = session.step([action, chooseTeamCpu(session.observe(1))]);
  }
  if (response.observation) throw Error("Charge study exceeded its step budget");
  if (!chargeFork) return {excluded: `${response.info.outcome}_before_fork`};
  return {chargeFork, audit: session.privateReplay(), reward: verifiedNativeReward(response),
    outcome: response.info.outcome};
}

function armSummary(rolled, requestedMove) {
  const turn = rolled.chargeFork.view.turn;
  const resolved = ownChargesFromFork(rolled).find(e => e.turn === turn && e.move_id === requestedMove);
  return {reward: rolled.reward, outcome: rolled.outcome, requested_move: requestedMove,
    move_resolved: Boolean(resolved), shielded: resolved?.shielded ?? null};
}

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
    choice => runArm(handoff, seed, opponentShields, targetSlot, expectedOpponentShields, choice),
    ["charge_1"],
  );
  const metadata = {seed, role, roster, planned_starting_opponent_shields: opponentShields};
  if (!immediate.chargeFork) return {...metadata, excluded: immediate.excluded};
  return {...metadata, public_state: publicChargeState(immediate.chargeFork.view),
    play_rough: armSummary(immediate, "PLAY_ROUGH"),
    hydro_pump: armSummary(alternatives.charge_1, "HYDRO_PUMP")};
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
