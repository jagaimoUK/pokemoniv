#!/usr/bin/env node
"use strict";
/* Bounded JSONL worker for fixed-150s synthetic switch evaluation under frozen RL policies. */
const readline = require("node:readline");
const {isDeepStrictEqual} = require("node:util");
const {createTeamSession, chooseTeamCpu} = require("../pvpoke_rl_team_native.js");
const {createPublicReplayRecorder} = require("./rl_public_replay.cjs");

const MAX_INPUT = 128 * 1024;
const MAX_OUTPUT = 1024 * 1024;
const WORLDS_RULESET = "play-pokemon-worlds-2026-gl";
const AZUMARILL_START = Object.freeze({hp_points: 120, energy_points: 55});

let session = null;
let replay = null;

function exact(value, allowed) {
  return value !== null && typeof value === "object" && !Array.isArray(value) &&
    Object.keys(value).every(k => allowed.includes(k));
}

function respond(value) {
  const line = JSON.stringify(value);
  if (Buffer.byteLength(line) > MAX_OUTPUT) throw Error("Output budget exceeded");
  process.stdout.write(line + "\n");
}

function stepPair(action) {
  const before = session.response().observation;
  const oppAction = chooseTeamCpu(session.observe(1));
  const result = session.step([action, oppAction]);
  replay.onStep(before, result);
  return result;
}

async function main() {
  const reader = readline.createInterface({input: process.stdin, crlfDelay: Infinity});
  for await (const line of reader) {
    try {
      if (Buffer.byteLength(line) > MAX_INPUT) throw Error("Input budget exceeded");
      const input = JSON.parse(line);
      if (!input || typeof input.op !== "string") throw Error("Missing operation");
      if (input.op === "reset") {
        if (!exact(input, ["op", "gamemaster_path", "handoff", "seed", "shields", "hp_percent", "wait_turns"]) ||
            typeof input.gamemaster_path !== "string" ||
            input.handoff?.ruleset_id !== WORLDS_RULESET) {
          throw Error("Invalid synthetic RL reset");
        }
        const options = {gamemasterPath: input.gamemaster_path, seed: input.seed, shields: input.shields};
        if (input.hp_percent !== undefined) {
          if (![20, 40, 60, 85].includes(input.hp_percent)) throw Error("Invalid hp_percent");
          const probe = createTeamSession(input.handoff, options);
          const ownTeam = probe.observe().own.team;
          const oppTeam = probe.observe(1).own.team;
          const hp = Math.floor(ownTeam[1].max_hp * input.hp_percent / 100);
          const ownLead = {
            hp_points: Math.min(AZUMARILL_START.hp_points, ownTeam[0].max_hp),
            energy_points: AZUMARILL_START.energy_points,
          };
          const oppLead = {
            hp_points: Math.min(AZUMARILL_START.hp_points, oppTeam[0].max_hp),
            energy_points: AZUMARILL_START.energy_points,
          };
          options.initial = [[ownLead, {hp_points: hp}], [oppLead]];
        }
        session = createTeamSession(input.handoff, options);
        replay = createPublicReplayRecorder();
        let res = session.response();
        const waitTurns = input.wait_turns ?? 0;
        if (!Number.isInteger(waitTurns) || waitTurns < 0 || waitTurns > 400) {
          throw Error("Invalid wait_turns");
        }
        if (waitTurns > 0) {
          for (let i = 0; i < waitTurns; i++) {
            const before = res.observation;
            res = session.step(["wait", "wait"]);
            replay.onStep(before, res);
          }
          const audit = session.privateReplay();
          if (res.observation?.phase !== "turn" || res.observation.elapsed_ms !== waitTurns * 500 ||
              audit.events.length !== 0 || audit.randomness.length !== 0 ||
              !isDeepStrictEqual(audit.initial.sides, audit.state.sides)) {
            throw Error("Waiting altered the synthetic state");
          }
        }
        respond({ok: true, result: res});
      } else if (input.op === "step") {
        if (!session || !exact(input, ["op", "action"]) || typeof input.action !== "string") {
          throw Error("Invalid synthetic RL step");
        }
        if (!session.observe(1)) throw Error("No active synthetic RL episode");
        respond({ok: true, result: stepPair(input.action)});
      } else if (input.op === "public_replay") {
        if (!session || !exact(input, ["op"])) throw Error("Invalid synthetic RL public_replay");
        respond({ok: true, public_replay: replay.summarize(session.privateReplay().events)});
      } else if (input.op === "close") {
        if (!exact(input, ["op"])) throw Error("Invalid synthetic RL close");
        respond({ok: true});
        return;
      } else {
        throw Error("Unsupported operation");
      }
    } catch (error) {
      respond({ok: false, error: "invalid_or_unsupported_request"});
      process.exitCode = 1;
      return;
    }
  }
}

if (require.main === module) {
  main().catch(() => { process.exitCode = 1; });
}
