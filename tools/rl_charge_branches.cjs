"use strict";
// Shared audit for one legal action from the same native battle history.
const {isDeepStrictEqual} = require("node:util");

const KO_REWARDS = {self_ko_win: 1, opponent_ko_win: -1, simultaneous_ko: 0};

function compareChargeFork(run, alternatives) {
  const immediate = run("immediate");
  const fork = immediate.chargeFork;
  const compared = {};
  if (fork) {
    if (!isDeepStrictEqual(immediate, run("immediate"))) {
      throw Error("Immediate charge A/A replay differs");
    }
    for (const action of alternatives) {
      if (action === fork.baselineAction || !fork.view.legal_actions.includes(action)) continue;
      const result = run(action);
      if (!isDeepStrictEqual(fork, result.chargeFork)) {
        throw Error("Charge study histories differ before the fork");
      }
      compared[action] = result;
    }
  }
  return {immediate, alternatives: compared};
}

function publicChargeState(view) {
  const enemy = view.opponent.revealed.find(p => p.species === view.opponent.active_species);
  if (!enemy || enemy.fainted) throw Error("Missing public target at charge fork");
  return {turn: view.turn, hp_bucket_5pct: enemy.hp_bucket_5pct,
    opponent_shields: view.opponent.shields, elapsed_ms: view.elapsed_ms};
}

function ownChargesFromFork(rolled) {
  const {view, audit} = rolled.chargeFork;
  const species = view.own.team[view.own.active_slot].species;
  return rolled.audit.events.slice(audit.events.length).filter(e =>
    e.kind === "charged" && e.actor === 0 && e.species === species);
}

function verifiedNativeReward(response) {
  if (!response.terminated) return null;
  const {outcome, training_eligible} = response.info;
  if (response.truncated || !training_eligible || !Object.hasOwn(KO_REWARDS, outcome) ||
      KO_REWARDS[outcome] !== response.reward) {
    throw Error("Native study returned an unverified terminal reward");
  }
  return response.reward;
}

function runBankedChargeArm(session, chooseAction, targetSlot, expectedOpponentShields, choice, {
  chooseOpponentAction = chooseAction, onStep,
} = {}) {
  let response = session.response();
  let chargeFork = null;
  for (let steps = 0; response.observation && steps < 2000; steps++) {
    const view = response.observation;
    let action = chooseAction(view);
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
    response = session.step([action, chooseOpponentAction(session.observe(1))]);
    onStep?.(view, response);
  }
  if (response.observation) throw Error("Charge study exceeded its step budget");
  if (!chargeFork) return {excluded: `${response.info.outcome}_before_fork`};
  return {chargeFork, audit: session.privateReplay(), reward: verifiedNativeReward(response),
    outcome: response.info.outcome};
}

function summarizeChargeArm(rolled, requestedMove) {
  const turn = rolled.chargeFork.view.turn;
  const resolved = ownChargesFromFork(rolled).find(e => e.turn === turn && e.move_id === requestedMove);
  return {reward: rolled.reward, outcome: rolled.outcome, requested_move: requestedMove,
    move_resolved: Boolean(resolved), shielded: resolved?.shielded ?? null};
}

module.exports = {compareChargeFork, publicChargeState, ownChargesFromFork, verifiedNativeReward,
  runBankedChargeArm, summarizeChargeArm};
