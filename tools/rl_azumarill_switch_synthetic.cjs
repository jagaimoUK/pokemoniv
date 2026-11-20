"use strict";
// Isolated synthetic mirror with the native engine's existing start-state inputs.
const {readFileSync} = require("node:fs");
const {isDeepStrictEqual} = require("node:util");
const {createTeamSession, chooseTeamCpu} = require("../pvpoke_rl_team_native.js");
const {compareChargeFork, publicChargeState, verifiedNativeReward} = require("./rl_charge_branches.cjs");
const {createPublicReplayRecorder} = require("./rl_public_replay.cjs");

const AZUMARILL_START = Object.freeze({hp_points: 120, energy_points: 55});
const WAIT_TURNS = 300;
const FORK_CLOCK_MS = 150000;
const SWITCH_SKARMORY = "switch_2";
const SWITCH_QUAGSIRE = "switch_1";

function runArm(session, choice) {
  let response = session.response();
  const replay = createPublicReplayRecorder();
  function step(action, opponentAction) {
    const before = response.observation;
    response = session.step([action, opponentAction]);
    replay.onStep(before, response);
  }

  // Tick the ordinary clock with no battle actions or resource changes.
  for (let i = 0; i < WAIT_TURNS; i++) step("wait", "wait");
  const view = response.observation;
  if (view?.phase !== "turn" || view.elapsed_ms !== FORK_CLOCK_MS ||
      view.own.team[view.own.active_slot].species !== "azumarill" ||
      view.opponent.active_species !== "azumarill" ||
      !["charge_0", SWITCH_SKARMORY, SWITCH_QUAGSIRE].every(action => view.legal_actions.includes(action))) {
    throw Error("Synthetic mirror did not reach the fixed decision");
  }
  const audit = session.privateReplay();
  if (audit.events.length !== 0 || audit.randomness.length !== 0 ||
      !isDeepStrictEqual(audit.initial.sides, audit.state.sides)) {
    throw Error("Waiting changed the synthetic battle state");
  }
  const chargeFork = {view, audit, baselineAction: SWITCH_SKARMORY};
  const action = choice === "immediate" ? SWITCH_SKARMORY : choice;
  step(action, chooseTeamCpu(session.observe(1)));

  for (let i = 0; response.observation && i < 1000; i++) {
    step(chooseTeamCpu(response.observation), chooseTeamCpu(session.observe(1)));
  }
  if (response.observation) throw Error("Synthetic switch exceeded its step budget");
  const terminal = session.privateReplay();
  return {chargeFork, action, audit: terminal, reward: verifiedNativeReward(response),
    outcome: response.info.outcome, replay: replay.summarize(terminal.events)};
}

function summarizeArm(rolled, target) {
  const {view} = rolled.chargeFork;
  const actionResolved = rolled.replay.events.some(event => event.kind === "switch" &&
    event.side === "self" && !event.forced && event.turn === view.turn &&
    event.species === target && event.previous_species === "azumarill");
  return {action_resolved: actionResolved, reward: rolled.reward, outcome: rolled.outcome,
    elapsed_ms: rolled.replay.elapsed_ms, replay: rolled.replay};
}

function compareCase({handoff, seed, roster, hp_percent: hpPercent, own_shields: ownShields}, gamemasterPath) {
  const [azumarill, quagsire, skarmory] = handoff.own_team;
  if (handoff.ruleset_id !== "play-pokemon-worlds-2026-gl" ||
      azumarill.species !== "azumarill" || azumarill.charged1 !== "ICE_BEAM" ||
      handoff.opponent_team[0].species !== "azumarill" || handoff.opponent_team[0].charged1 !== "ICE_BEAM" ||
      !["quagsire", "quagsire_shadow"].includes(quagsire.species) || skarmory.species !== "skarmory" ||
      ![20, 40, 60, 85].includes(hpPercent) || ![0, 1, 2].includes(ownShields) ||
      (ownShields !== 0 && hpPercent !== 20)) {
    throw Error("Unexpected synthetic switch condition");
  }
  const options = {gamemasterPath, seed, shields: [ownShields, 0]};
  const maxHp = createTeamSession(handoff, options).observe().own.team[1].max_hp;
  const hp = Math.floor(maxHp * hpPercent / 100);
  const initial = [[AZUMARILL_START, {hp_points: hp}], [AZUMARILL_START]];
  const {immediate, alternatives} = compareChargeFork(
    choice => runArm(createTeamSession(handoff, {...options, initial}), choice),
    [SWITCH_QUAGSIRE],
  );
  const {view} = immediate.chargeFork;
  return {seed, roster, species: quagsire.species, second_move: quagsire.charged2,
    hp_percent: hpPercent, own_shields: view.own.shields, public_state: publicChargeState(view),
    reserve_hp_bands: {skarmory: 3, quagsire: Math.floor(4 * hp / maxHp)},
    switch_targets: {switch_skarmory: skarmory.species, switch_quagsire: quagsire.species},
    after_event_seq: 0, switch_skarmory: summarizeArm(immediate, skarmory.species),
    switch_quagsire: summarizeArm(alternatives[SWITCH_QUAGSIRE], quagsire.species)};
}

try {
  const cases = JSON.parse(readFileSync(0, "utf8"));
  const gamemasterPath = process.argv[2];
  if (!gamemasterPath || !Array.isArray(cases) || cases.length < 1 || cases.length > 144) {
    throw Error("Invalid synthetic study input");
  }
  process.stdout.write(JSON.stringify(cases.map(row => compareCase(row, gamemasterPath))));
} catch (error) {
  process.stderr.write(`Synthetic switch study failed: ${error.message}\n`);
  process.exitCode = 1;
}
