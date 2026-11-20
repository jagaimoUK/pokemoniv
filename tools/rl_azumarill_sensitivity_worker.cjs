#!/usr/bin/env node
"use strict";
/* Bounded JSONL worker for Azumarill non-fixed opponent shielding sensitivity.
 * Public views only reach policies; privateReplay stays trusted-audit-only.
 */
const path = require("node:path");
const readline = require("node:readline");
const {createTeamSession, chooseTeamCpu} = require("../pvpoke_rl_team_native.js");

const GAMEMASTER = path.join(__dirname, "..", "tests", "fixtures", "strategy_gamemaster.json");
const MAX_INPUT = 128 * 1024;
const MAX_OUTPUT = 1024 * 1024;
const WORLDS_RULESET = "play-pokemon-worlds-2026-gl";
const OPPONENT_POLICIES = new Set(["cpu_always", "save_high_hp", "seeded_mixed_50"]);

let session = null;
let oppPolicy = null;
let oppRng = null;

function exact(value, allowed) {
  return value !== null && typeof value === "object" && !Array.isArray(value) &&
    Object.keys(value).every(k => allowed.includes(k));
}

function respond(value) {
  const line = JSON.stringify(value);
  if (Buffer.byteLength(line) > MAX_OUTPUT) throw Error("Output budget exceeded");
  process.stdout.write(line + "\n");
}

function makePolicyRng(seed) {
  let state = (seed ^ 0x9e3779b9) >>> 0;
  return () => {
    state = (state + 0x6D2B79F5) >>> 0;
    let n = Math.imul(state ^ (state >>> 15), state | 1);
    n ^= n + Math.imul(n ^ (n >>> 7), n | 61);
    return ((n ^ (n >>> 14)) >>> 0) / 4294967296;
  };
}

function chooseOpponentAction(view, policyName, rng) {
  if (view.legal_actions.includes("shield_yes")) {
    const active = view.own.team[view.own.active_slot];
    const ratio = active.hp / active.max_hp;
    if (policyName === "cpu_always") return ratio >= 0.25 ? "shield_yes" : "shield_no";
    if (policyName === "save_high_hp") {
      return (ratio >= 0.25 && ratio < 0.60) ? "shield_yes" : "shield_no";
    }
    if (policyName === "seeded_mixed_50") {
      if (ratio < 0.25) return "shield_no";
      return rng() < 0.5 ? "shield_yes" : "shield_no";
    }
    throw Error("Unknown opponent shielding policy");
  }
  return chooseTeamCpu(view);
}

async function main() {
  const reader = readline.createInterface({input: process.stdin, crlfDelay: Infinity});
  for await (const line of reader) {
    try {
      if (Buffer.byteLength(line) > MAX_INPUT) throw Error("Input budget exceeded");
      const input = JSON.parse(line);
      if (!input || typeof input.op !== "string") throw Error("Missing operation");
      if (input.op === "reset") {
        if (!exact(input, ["op", "handoff", "seed", "shields", "opponent_policy"]) ||
            typeof input.opponent_policy !== "string" ||
            !OPPONENT_POLICIES.has(input.opponent_policy) ||
            input.handoff?.ruleset_id !== WORLDS_RULESET) {
          throw Error("Invalid sensitivity reset");
        }
        session = createTeamSession(input.handoff, {
          gamemasterPath: GAMEMASTER, seed: input.seed, shields: input.shields,
        });
        oppPolicy = input.opponent_policy;
        oppRng = makePolicyRng(input.seed);
        respond({ok: true, result: session.response()});
      } else if (input.op === "step") {
        if (!session || !exact(input, ["op", "action"]) || typeof input.action !== "string") {
          throw Error("Invalid sensitivity step");
        }
        const oppView = session.observe(1);
        if (!oppView) throw Error("No active sensitivity episode");
        const oppAction = chooseOpponentAction(oppView, oppPolicy, oppRng);
        respond({ok: true, result: session.step([input.action, oppAction])});
      } else if (input.op === "replay") {
        if (!session || !exact(input, ["op"])) throw Error("Invalid sensitivity replay");
        respond({ok: true, replay: session.privateReplay()});
      } else if (input.op === "close") {
        if (!exact(input, ["op"])) throw Error("Invalid sensitivity close");
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
module.exports = {chooseOpponentAction};
