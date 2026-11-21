"use strict";
// Offline synthetic trial. Starting shields are set on the native session.
const {readFileSync} = require("node:fs");
const {join} = require("node:path");
const {createTeamSession, chooseTeamCpu} = require("../pvpoke_rl_team_native.js");
const {compareChargeFork, publicChargeState, ownChargesFromFork, verifiedNativeReward} =
  require("./rl_charge_branches.cjs");

const GAMEMASTER = join(__dirname, "..", "tests", "fixtures", "strategy_gamemaster.json");

function runArm(handoff, seed, opponentShields, choice) {
  const session = createTeamSession(handoff, {gamemasterPath: GAMEMASTER, seed,
    shields: [2, opponentShields]});
  let response = session.response();
  let chargeFork = null;
  for (let steps = 0; response.observation && steps < 2000; steps++) {
    const view = response.observation;
    let action = chooseTeamCpu(view);
    if (!chargeFork && view.own.team[0].hp === 0) return {excluded: "lead_fainted_before_fork"};
    if (!chargeFork && view.phase === "turn" && view.own.active_slot === 0) {
      const legal = view.legal_actions;
      if (legal.includes("charge_0") && legal.includes("charge_1")) {
        if (view.opponent.shields !== opponentShields) throw Error("Banking changed opponent shields");
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

function compareCase({handoff, seed, opponent_shields: opponentShields, roster}) {
  const lead = handoff.own_team[0];
  if (lead.species !== "skarmory" || lead.charged1 !== "SKY_ATTACK" || lead.charged2 !== "BRAVE_BIRD" ||
      ![1, 2].includes(opponentShields)) throw Error("Unexpected Skarmory study fixture");
  const {immediate, alternatives} = compareChargeFork(
    choice => runArm(handoff, seed, opponentShields, choice), ["charge_1"]);
  const metadata = {seed, roster, planned_opponent_shields: opponentShields};
  if (!immediate.chargeFork) return {...metadata, excluded: immediate.excluded};
  return {...metadata, public_state: publicChargeState(immediate.chargeFork.view),
    sky_attack: armSummary(immediate, "SKY_ATTACK"),
    brave_bird: armSummary(alternatives.charge_1, "BRAVE_BIRD")};
}

if (require.main === module) {
  try {
    const cases = JSON.parse(readFileSync(0, "utf8"));
    if (!Array.isArray(cases) || cases.length < 1 || cases.length > 12) throw Error("Invalid study size");
    process.stdout.write(JSON.stringify(cases.map(compareCase)));
  } catch (error) {
    process.stderr.write("Skarmory synthetic study failed integrity or input checks\n");
    process.exitCode = 1;
  }
}
