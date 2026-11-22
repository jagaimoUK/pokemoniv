#!/usr/bin/env node
"use strict";
/* Internal, experimental single-worker RL transport. Not an HTTP endpoint.
 * One JSON request/response per line, with bounded I/O and no private data in
 * observations. Keep the native Battle.js instance alive between steps.
 */
const readline = require("node:readline");
const {createStatefulSession} = require("./pvpoke_rl_stateful_native.js");
const {createTeamSession, chooseTeamCpu} = require("./pvpoke_rl_team_native.js");
const MAX_INPUT = 128 * 1024;
const MAX_OUTPUT = 1024 * 1024;
let session = null;
let team = null;

function exact(value, allowed) {
  return value !== null && typeof value === "object" && !Array.isArray(value) &&
    Object.keys(value).every(k => allowed.includes(k));
}
function respond(value) {
  const line = JSON.stringify(value);
  if (Buffer.byteLength(line) > MAX_OUTPUT) throw Error("Output budget exceeded");
  process.stdout.write(line + "\n");
}
async function main() {
  const reader = readline.createInterface({input: process.stdin, crlfDelay: Infinity});
  for await (const line of reader) {
    try {
      if (Buffer.byteLength(line) > MAX_INPUT) throw Error("Input budget exceeded");
      const input = JSON.parse(line);
      if (!input || typeof input.op !== "string") throw Error("Missing operation");
      if (input.op === "reset") {
        if (!exact(input, ["op", "prepared", "horizon"])) throw Error("Invalid reset request");
        team = null;
        session = createStatefulSession(input.prepared, {horizon: input.horizon ?? 500});
        respond({ok: true, observation: session.observe(),
          info: {experimental: true, information_fairness: "not_established",
            live_reproducibility: "not_verified"}});
      } else if (input.op === "step") {
        if (!session || !exact(input, ["op", "action"]) || typeof input.action !== "string") {
          throw Error("Invalid step request");
        }
        respond({ok: true, result: session.step(input.action)});
      } else if (input.op === "team_reset") {
        if (!exact(input, ["op", "handoff", "gamemaster_path", "seed", "horizon"]) ||
            typeof input.gamemaster_path !== "string") throw Error("Invalid team reset");
        session = null;
        team = createTeamSession(input.handoff, {
          gamemasterPath: input.gamemaster_path, seed: input.seed, horizon: input.horizon,
        });
        respond({ok: true, result: team.response()});
      } else if (input.op === "team_step") {
        if (!team || !exact(input, ["op", "action"]) || typeof input.action !== "string") {
          throw Error("Invalid team step");
        }
        const cpuView = team.observe(1);
        if (!cpuView) throw Error("No active team episode");
        let result = team.step([input.action, chooseTeamCpu(cpuView)]);
        while (result.observation?.phase === "shield" &&
            result.observation.legal_actions[0] === "wait") {
          result = team.step(["wait", chooseTeamCpu(team.observe(1))]);
        }
        respond({ok: true, result});
      } else if (input.op === "team_replay") {
        if (!team || !exact(input, ["op"])) throw Error("Invalid team replay");
        respond({ok: true, replay: team.privateReplay()});
      } else if (input.op === "stats") {
        if ((!session && !team) || !exact(input, ["op"])) throw Error("Invalid stats request");
        respond({ok: true, rss_bytes: process.memoryUsage().rss,
          peak_rss_kib: process.resourceUsage().maxRSS});
      } else if (input.op === "close") {
        if (!exact(input, ["op"])) throw Error("Invalid close request");
        respond({ok: true});
        return;
      } else {
        throw Error("Unsupported operation");
      }
    } catch (error) {
      // Do not leak local paths, private battle state or JS stack traces.
      respond({ok: false, error: "invalid_or_unsupported_request"});
      process.exitCode = 1;
      return; // Fail closed; native battle may have partially advanced.
    }
  }
}
main().catch(() => { process.exitCode = 1; });
