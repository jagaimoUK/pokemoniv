"use strict";

const REPLAY_FIELDS = new Map([
  ["switch", ["previous_species", "forced"]],
  ["charge_announced", []],
  ["charged", ["move_id", "shielded"]],
  ["faint", []],
]);
// The native clock charges 10 seconds per resolved charged move, including shields.
const CHARGE_MS = 10000;

function publicReplay(events, clock) {
  let step = 0;
  let chargedMs = 0;
  const timeline = [];
  for (const event of events) {
    const fields = REPLAY_FIELDS.get(event.kind);
    if (!fields) continue;
    while (clock[step].through < event.seq) step++;
    const {kind, seq, turn, species} = event;
    // Multiple events can share one step interval; these are not per-event timestamps.
    const {start_ms, end_ms} = clock[step];
    if (kind === "charged") chargedMs += CHARGE_MS;
    timeline.push({kind, seq, turn, species, side: event.actor === 0 ? "self" : "opponent",
      start_ms, end_ms, ...Object.fromEntries(fields.map(key => [key, event[key]]))});
  }
  const {start_ms, end_ms} = clock.at(-1);
  if (chargedMs > end_ms) throw Error("Resolved charges exceed the observed clock");
  return {elapsed_ms: end_ms, charged_ms: chargedMs, clock_remainder_ms: end_ms - chargedMs,
    terminal_step: {start_ms, end_ms}, events: timeline};
}

function createPublicReplayRecorder() {
  const clock = [];
  return {
    onStep(before, after) {
      // Terminal observations are null; project the remaining audit events
      // through the same public field allowlist at the final step.
      const through = after.observation
        ? (after.observation.recent_events.at(-1)?.seq ?? 0)
        : Infinity;
      clock.push({through, start_ms: before.elapsed_ms, end_ms: after.info.elapsed_ms});
    },
    summarize(events) {
      return publicReplay(events, clock);
    },
  };
}

module.exports = {createPublicReplayRecorder, CHARGE_MS};
