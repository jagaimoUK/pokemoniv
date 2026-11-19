"use strict";
// Offline synthetic study. No research settings are exposed in the worker RPC.
const {readFileSync} = require("node:fs");
const {join} = require("node:path");
const {isDeepStrictEqual} = require("node:util");
const {createTeamSession, chooseTeamCpu} = require("../pvpoke_rl_team_native.js");

const GAMEMASTER = join(__dirname, "..", "tests", "fixtures", "strategy_gamemaster.json");
const SLOT = 2;
const BONUSES = [8, 16];
const KO_REWARDS = {self_ko_win: 1, opponent_ko_win: -1, simultaneous_ko: 0};

const resolvedMove = e => e.kind === "fast" || e.kind === "charged";
const moveSummary = e => ({side: e.actor === 0 ? "self" : "opponent", species: e.species,
  move: e.move_id, turn: e.turn, shielded: e.shielded});

function run(handoff, seed, opening, energyBonus) {
  const session = createTeamSession(handoff, {gamemasterPath: GAMEMASTER, seed,
    entryStudy: {slot: SLOT, energyBonus}});
  let response = session.response();
  let fork = null, firstSwitch = null, secondSwiftReady = null;
  let sawKo = false, lastSeq = 0, swifts = 0, firstActive = null, lastActive = null;
  for (let steps = 0; response.observation && steps < 2000; steps++) {
    const view = response.observation;
    for (const e of view.recent_events) {
      if (e.seq <= lastSeq) continue;
      lastSeq = e.seq;
      if (e.kind === "faint") sawKo = true;
      if (sawKo && e.actor === "self" && e.species === "wigglytuff" &&
          e.kind === "charged" && e.move_id === "SWIFT" && !e.shielded) swifts++;
    }
    const legal = view.legal_actions;
    let action = chooseTeamCpu(view);
    if (!fork && steps > 0 && view.phase === "turn" && action === "fast" && legal.includes("switch_1")) {
      fork = {view, audit: session.privateReplay()};
      action = opening;
    }
    if (view.own.active_slot === SLOT && view.own.team[SLOT].hp > 0) {
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
  const {outcome, training_eligible} = response.info;
  if (response.terminated && (!training_eligible || KO_REWARDS[outcome] !== response.reward)) {
    throw Error("Native study returned an unverified terminal reward");
  }
  const entryStates = entry?.state.sides;
  const summary = {
    reward: response.terminated ? response.reward : null, outcome,
    fork_turn: fork?.view.turn ?? null, switch_at_fork: openingSwitch?.species ?? null,
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
  return {fork, audit, summary};
}

function entryPrefix(audit) {
  const {energy_added: _, ...entry} = audit.studied_entry;
  return {entry,
    decisions: audit.decisions.slice(0, entry.decision_count),
    randomness: audit.randomness.slice(0, entry.randomness_count),
    events: audit.events.slice(0, entry.event_count)};
}

function compareCase({seed, handoff}) {
  if (handoff.own_team[2].species !== "wigglytuff" || handoff.own_team[2].charged2 !== "SWIFT") {
    throw Error("Unexpected Swift study fixture");
  }
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

if (require.main === module) {
  try {
    const cases = JSON.parse(readFileSync(0, "utf8"));
    if (!Array.isArray(cases) || cases.length < 1 || cases.length > 12) throw Error("Invalid study size");
    process.stdout.write(JSON.stringify(cases.map(compareCase)));
  } catch (error) {
    process.stderr.write("Swift synthetic study failed integrity or input checks\n");
    process.exitCode = 1;
  }
}
