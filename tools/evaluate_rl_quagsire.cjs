"use strict";
// Offline 3v3 worker. Private audits stay inside matching and replay projection.
const {readFileSync} = require("node:fs");
const {isDeepStrictEqual} = require("node:util");
const {createTeamSession, chooseTeamCpu} = require("../pvpoke_rl_team_native.js");
const {chooseOpponentAction} = require("./rl_azumarill_sensitivity_worker.cjs");
const {createPublicReplayRecorder} = require("./rl_public_replay.cjs");
const {compareMirrorForks} = require("./rl_azumarill_mirror.cjs");
const {compareChargeFork, publicChargeState, runBankedChargeArm, summarizeChargeArm} =
  require("./rl_charge_branches.cjs");

const RULESETS = new Set(["play-pokemon-worlds-2026-gl", "play-pokemon-cs-2026-11-16-gl"]);

function compareCase({handoff, seed, roster, opponent_shields: opponentShields}, gamemasterPath, mode) {
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
  const newSession = () => createTeamSession(handoff, {gamemasterPath, seed, shields: [2, opponentShields]});
  if (mode === "mirror") {
    return {...metadata, mirror_forks: compareMirrorForks(newSession, opponentShields, lead)};
  }

  const withReplay = mode !== "charges";
  function fork(policy) {
    return compareChargeFork(choice => {
      const replay = withReplay ? createPublicReplayRecorder() : null;
      const session = newSession();
      const rolled = runBankedChargeArm(session, chooseTeamCpu, 0, opponentShields, choice, {
        chooseOpponentAction: view => chooseOpponentAction(view, policy),
        onStep: replay?.onStep,
      });
      if (replay && rolled.chargeFork) rolled.replay = replay.summarize(rolled.audit.events);

      return rolled;
    }, ["charge_1"]);
  }

  const baseline = fork("cpu_always");
  const other = mode === "shielding" ? fork("save_high_hp") : null;
  if (other && (!isDeepStrictEqual(baseline.immediate.chargeFork, other.immediate.chargeFork) ||
      !isDeepStrictEqual(baseline.immediate.excluded, other.immediate.excluded) ||
      (opponentShields === 0 && !isDeepStrictEqual(baseline, other)))) {
    throw Error("Shield policies changed a shared history or a zero-shield replay");
  }
  if (!baseline.immediate.chargeFork) return {...metadata, excluded: baseline.immediate.excluded};

  function summarizePair({immediate, alternatives}) {
    const second = alternatives.charge_1;
    return {
      aqua_tail: {...summarizeChargeArm(immediate, lead.charged1),
        ...(withReplay && {replay: immediate.replay})},
      second_charge: {...summarizeChargeArm(second, lead.charged2),
        ...(withReplay && {replay: second.replay})},
    };
  }
  const state = {...metadata, public_state: publicChargeState(baseline.immediate.chargeFork.view)};
  if (!withReplay) return {...state, ...summarizePair(baseline)};
  return {...state, by_policy: {cpu_always: summarizePair(baseline),
    ...(other && {save_high_hp: summarizePair(other)})}};
}

try {
  const cases = JSON.parse(readFileSync(0, "utf8"));
  const [, , gamemasterPath, mode = "charges"] = process.argv;
  if (!gamemasterPath || !["charges", "historical", "shielding", "mirror"].includes(mode) ||
      !Array.isArray(cases) || cases.length < 1 || cases.length > 144) {
    throw Error("Invalid study input");
  }
  process.stdout.write(JSON.stringify(cases.map(row => compareCase(row, gamemasterPath, mode))));
} catch (error) {
  process.stderr.write(`Quagsire study failed: ${error.message}\n`);
  process.exitCode = 1;
}
