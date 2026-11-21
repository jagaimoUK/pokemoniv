"use strict";
// Offline synthetic study. No research settings are exposed in the worker RPC.
const {readFileSync} = require("node:fs");
const {join} = require("node:path");
const {isDeepStrictEqual} = require("node:util");
const {createTeamSession, chooseTeamCpu} = require("../pvpoke_rl_team_native.js");
const {compareChargeFork, publicChargeState, ownChargesFromFork, verifiedNativeReward} =
  require("./rl_charge_branches.cjs");

const GAMEMASTER = join(__dirname, "..", "tests", "fixtures", "strategy_gamemaster.json");
const SLOT = 2;
const BONUSES = [8, 16];
const TARGET_SWITCH = `switch_${SLOT}`;
const SECOND_SWIFT = {slot: SLOT, move: "SWIFT", ordinal: 2};
const CHARGE_ALTERNATIVES = ["fast", "charge_0", "wait"];

const resolvedMove = e => e.kind === "fast" || e.kind === "charged";
const moveSummary = e => ({side: e.actor === 0 ? "self" : "opponent", species: e.species,
  move: e.move_id, turn: e.turn, shielded: e.shielded});

function readyCharge(view, resolvedCount, {slot, move, ordinal}) {
  if (view.phase !== "turn" || view.own.active_slot !== slot || resolvedCount !== ordinal - 1) {
    return null;
  }
  const index = view.own.team[slot].charged_moves.findIndex(m => m.move_id === move);
  const action = `charge_${index}`;
  return index >= 0 && view.legal_actions.includes(action) ? action : null;
}

function run(handoff, seed, opening, energyBonus, timingMode = null, chargeChoice = null) {
  const session = createTeamSession(handoff, {gamemasterPath: GAMEMASTER, seed,
    entryStudy: {slot: SLOT, energyBonus}});
  let response = session.response();
  let fork = null, firstSwitch = null, secondSwiftReady = null;
  let sawKo = false, lastSeq = 0, swifts = 0, allSwifts = 0, firstActive = null, lastActive = null;
  let secondResolvedSwiftReady = null;
  let timingFork = null, timingAttempt = null, blockedAt = null, pendingDelay = false, chargeFork = null;
  for (let steps = 0; response.observation && steps < 2000; steps++) {
    const view = response.observation;
    for (const e of view.recent_events) {
      if (e.seq <= lastSeq) continue;
      lastSeq = e.seq;
      if (e.kind === "faint") sawKo = true;
      if (sawKo && e.actor === "self" && e.species === "wigglytuff" &&
          e.kind === "charged" && e.move_id === "SWIFT") {
        allSwifts++;
        if (!e.shielded) swifts++;
      }
    }
    const legal = view.legal_actions;
    let action = chooseTeamCpu(view);
    if (!fork && steps > 0 && view.phase === "turn" && action === "fast" && legal.includes("switch_1")) {
      fork = {view, audit: session.privateReplay()};
      action = opening;
    }
    if (chargeChoice && !chargeFork && fork && sawKo) {
      const swiftAction = readyCharge(view, allSwifts, SECOND_SWIFT);
      if (swiftAction) {
        chargeFork = {view, audit: session.privateReplay(), baselineAction: swiftAction};
        action = chargeChoice === "immediate" ? swiftAction : chargeChoice;
        if (!legal.includes(action)) throw Error("Charge study action is not legal at the fork");
      }
    }
    // The worker consumes an opponent-only shield decision internally. All
    // other returned views, including forced wait and replacement, count.
    const ownDecision = view.phase !== "shield" || legal[0] !== "wait";
    if (timingMode && ownDecision) {
      if (pendingDelay) {
        pendingDelay = false;
        if (view.phase === "turn" && legal.includes(TARGET_SWITCH)) {
          action = TARGET_SWITCH;
          timingAttempt = {turn: view.turn, event_count: lastSeq};
        } else {
          blockedAt = {turn: view.turn, phase: view.phase, fallback_action: action,
            cooldown_ms: view.own.team[view.own.active_slot].cooldown_ms,
            switch_timer_ms: view.own.switch_timer_ms};
        }
      } else if (!timingFork && sawKo && fork && !firstActive &&
          view.phase === "turn" && action === TARGET_SWITCH) {
        timingFork = {view, audit: session.privateReplay()};
        if (timingMode === "immediate") {
          timingAttempt = {turn: view.turn, event_count: lastSeq};
        } else {
          if (!legal.includes(timingMode)) throw Error("Delay action is not legal at the fork");
          action = timingMode;
          pendingDelay = true;
        }
      }
    }
    if ((!timingMode || ownDecision) && view.own.active_slot === SLOT && view.own.team[SLOT].hp > 0) {
      const {hp, energy_points} = view.own.team[SLOT];
      lastActive = {turn: view.turn, elapsed_ms: view.elapsed_ms, hp, energy_points,
        opponent: view.opponent.active_species, action, switch_timer_ms: view.own.switch_timer_ms,
        live_bench: view.own.team.filter((member, slot) => slot !== SLOT && member.hp > 0).length};
      firstActive ??= {view: lastActive, event_count: lastSeq};
      if (!firstSwitch && view.phase === "turn" && legal.some(a => a.startsWith("switch_"))) {
        firstSwitch = {turn: view.turn, elapsed_ms: view.elapsed_ms};
      }
      if (!secondSwiftReady && swifts === 1 && legal.includes("charge_1")) {
        secondSwiftReady = {...lastActive};
      }
      if (!secondResolvedSwiftReady && allSwifts === 1 && legal.includes("charge_1")) {
        secondResolvedSwiftReady = {...lastActive};
      }
    }
    response = session.step([action, chooseTeamCpu(session.observe(1))]);
  }
  if (response.observation) throw Error("Native study exceeded its step budget");
  const audit = session.privateReplay();
  const entry = audit.studied_entry;
  const firstKo = audit.events.find(e => e.kind === "faint");
  const isSwift = e => e.kind === "charged" && e.actor === 0 && e.species === "wigglytuff" &&
    e.move_id === "SWIFT" && firstKo && e.seq > firstKo.seq;
  const wigglyFaint = audit.events.find(e => e.kind === "faint" && e.actor === 0 && e.species === "wigglytuff");
  const lastOpponentMove = wigglyFaint && audit.events.findLast(e =>
    e.seq < wigglyFaint.seq && e.actor === 1 && resolvedMove(e));
  const openingSwitch = fork && audit.events.find(e => e.seq > fork.audit.events.length &&
    e.kind === "switch" && e.actor === 0 && e.turn === fork.view.turn && !e.forced);
  const final = audit.state.sides[0].team[SLOT];
  const entryStates = entry?.state.sides;
  const summary = {
    reward: verifiedNativeReward(response), outcome: response.info.outcome,
    [timingMode ? "opening_fork_turn" : "fork_turn"]: fork?.view.turn ?? null,
    switch_at_fork: openingSwitch?.species ?? null,
    entry: entry ? {turn: entry.action_turn, elapsed_ms: entry.elapsed_ms, forced: entry.forced,
      hp: entryStates[0].team[SLOT].hp, energy_points: entryStates[0].team[SLOT].energy_points,
      energy_added: entry.energy_added, self_shields: entryStates[0].shields,
      opponent_shields: entryStates[1].shields, switch_timer_ms: entryStates[0].switch_timer_ms} : null,
    first_voluntary_switch: firstSwitch, second_swift_ready: secondSwiftReady,
    first_active: firstActive?.view ?? null,
    moves_before_first_active: entry && firstActive ? audit.events
      .slice(entry.event_count, firstActive.event_count).filter(resolvedMove).map(moveSummary) : [],
    last_active: lastActive, final_hp: final.hp, final_energy_points: final.energy_points,
    faint_turn: wigglyFaint ? wigglyFaint.turn - 1 : null,
    last_opponent_move_before_faint: lastOpponentMove ? moveSummary(lastOpponentMove) : null,
    resolved_wigglytuff_moves: audit.events.filter(e => resolvedMove(e) && e.actor === 0 &&
      e.species === "wigglytuff").map(moveSummary),
    swift: audit.events.filter(isSwift).map(e => ({turn: e.turn, shielded: e.shielded})),
  };
  if (timingMode && timingFork) {
    const resolved = timingAttempt && audit.events.some(e => e.seq > timingAttempt.event_count &&
      e.turn === timingAttempt.turn && e.kind === "switch" && e.actor === 0 &&
      e.species === "wigglytuff" && !e.forced);
    summary.timing = {
      status: blockedAt ? "next_switch_illegal" : pendingDelay ? "terminal_before_next_decision" :
        resolved ? "voluntary_switch_resolved" : "voluntary_switch_cancelled",
      attempted_turn: timingAttempt?.turn ?? null,
      blocked_at: blockedAt,
    };
    summary.entry_hp_lost = entry && firstActive ? entryStates[0].team[SLOT].hp - firstActive.view.hp : null;
    summary.second_resolved_swift_ready = secondResolvedSwiftReady;
  }
  return {fork, timingFork, chargeFork, audit, summary};
}

function entryPrefix(audit) {
  const {energy_added: _, ...entry} = audit.studied_entry;
  return {entry,
    decisions: audit.decisions.slice(0, entry.decision_count),
    randomness: audit.randomness.slice(0, entry.randomness_count),
    events: audit.events.slice(0, entry.event_count)};
}

function validateFixture(handoff) {
  if (handoff.own_team[2].species !== "wigglytuff" || handoff.own_team[2].charged2 !== "SWIFT") {
    throw Error("Unexpected Swift study fixture");
  }
}

function compareCase({seed, handoff}) {
  validateFixture(handoff);
  const stay = run(handoff, seed, "fast", 0);
  const switched = run(handoff, seed, "switch_1", 0);
  const control = run(handoff, seed, "switch_1", 0);
  if (!stay.fork || !isDeepStrictEqual(stay.fork, switched.fork) || !isDeepStrictEqual(switched, control)) {
    throw Error("Native opening or A/A history differs");
  }
  const interventions = {};
  if (switched.audit.studied_entry) {
    const before = entryPrefix(switched.audit);
    for (const bonus of BONUSES) {
      const candidate = run(handoff, seed, "switch_1", bonus);
      if (!candidate.audit.studied_entry || !isDeepStrictEqual(before, entryPrefix(candidate.audit))) {
        throw Error("Native history or conditions differ before the entry intervention");
      }
      if (candidate.summary.entry.energy_added !== Math.min(bonus, 100 - switched.summary.entry.energy_points)) {
        throw Error("Entry intervention did not apply the intended energy");
      }
      interventions[bonus] = candidate.summary;
    }
  }
  return {seed, stay: stay.summary, switch: switched.summary, interventions};
}

function compareTiming({seed, handoff}) {
  validateFixture(handoff);
  const immediate = run(handoff, seed, "switch_1", 0, "immediate");
  if (!immediate.timingFork) {
    return {seed, excluded: immediate.summary.entry?.forced ? "forced_entry" : "no_voluntary_fork"};
  }
  const control = run(handoff, seed, "switch_1", 0, "immediate");
  if (!isDeepStrictEqual(immediate, control)) throw Error("Immediate switch A/A replay differs");
  const delayed = {};
  for (const action of ["wait", "fast"]) {
    if (!immediate.timingFork.view.legal_actions.includes(action)) continue;
    const result = run(handoff, seed, "switch_1", 0, action);
    if (!isDeepStrictEqual(immediate.timingFork, result.timingFork)) {
      throw Error("Voluntary switch histories differ before the fork");
    }
    delayed[action] = result.summary;
  }
  return {seed, fork_turn: immediate.timingFork.view.turn,
    opponent_at_fork: immediate.timingFork.view.opponent.active_species,
    immediate: immediate.summary, delayed};
}

function chargeOutcome(rolled) {
  const {view} = rolled.chargeFork;
  const resolved = ownChargesFromFork(rolled);
  return {reward: rolled.summary.reward, outcome: rolled.summary.outcome,
    charge_resolved_at_fork: resolved.filter(e => e.turn === view.turn).map(moveSummary),
    first_charge_from_fork: resolved.length ? moveSummary(resolved[0]) : null,
    second_swift_resolved: rolled.summary.swift.length >= 2,
    second_unshielded_swift_resolved: rolled.summary.swift.filter(e => !e.shielded).length >= 2};
}

function compareChargeHistory(handoff, seed, opening) {
  const {immediate, alternatives} = compareChargeFork(
    choice => run(handoff, seed, opening, 0, null, choice), CHARGE_ALTERNATIVES);
  if (!immediate.chargeFork) {
    return {excluded: immediate.summary.swift.length ? "second_swift_not_legal" : "no_first_swift"};
  }
  const {view, baselineAction} = immediate.chargeFork;
  return {public_state: publicChargeState(view), immediate_action: baselineAction,
    immediate: chargeOutcome(immediate), alternatives: Object.fromEntries(
      Object.entries(alternatives).map(([action, result]) => [action, chargeOutcome(result)]))};
}

function compareSecondSwift({seed, handoff}) {
  validateFixture(handoff);
  return {seed, histories: {
    stay: compareChargeHistory(handoff, seed, "fast"),
    switch: compareChargeHistory(handoff, seed, "switch_1"),
  }};
}

if (require.main === module) {
  try {
    const cases = JSON.parse(readFileSync(0, "utf8"));
    if (!Array.isArray(cases) || cases.length < 1 || cases.length > 12) throw Error("Invalid study size");
    const modes = {"--switch-timing": compareTiming, "--second-swift": compareSecondSwift};
    const mode = process.argv[2];
    const compare = Object.hasOwn(modes, mode) ? modes[mode] : compareCase;
    process.stdout.write(JSON.stringify(cases.map(compare)));
  } catch (error) {
    process.stderr.write("Swift synthetic study failed integrity or input checks\n");
    process.exitCode = 1;
  }
}
