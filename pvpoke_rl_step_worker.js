#!/usr/bin/env node
"use strict";
/* Internal, experimental single-worker 1v1 RL transport. Not an HTTP endpoint.
 * One JSON request/response per line, with bounded I/O and no private data in
 * observations. Keep the native Battle.js instance alive between steps.
 */
const readline = require("node:readline");
const {createStatefulSession} = require("./pvpoke_rl_stateful_native.js");
const MAX_INPUT = 128 * 1024;
const MAX_OUTPUT = 1024 * 1024;
let session = null;

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
        session = createStatefulSession(input.prepared, {horizon: input.horizon ?? 500});
        respond({ok: true, observation: session.observe(),
          info: {experimental: true, information_fairness: "not_established",
            live_reproducibility: "not_verified"}});
      } else if (input.op === "step") {
        if (!session || !exact(input, ["op", "action"]) || typeof input.action !== "string") {
          throw Error("Invalid step request");
        }
        respond({ok: true, result: session.step(input.action)});
      } else if (input.op === "stats") {
        if (!session || !exact(input, ["op"])) throw Error("Invalid stats request");
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
