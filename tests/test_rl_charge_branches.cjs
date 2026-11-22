"use strict";
const assert = require("node:assert/strict");
const {compareChargeFork} = require("../tools/rl_charge_branches.cjs");

const fork = {baselineAction: "charge_0", view: {legal_actions: ["charge_0", "charge_1"]},
  audit: {decisions: ["fast"]}};

{
  const actions = [];
  const result = compareChargeFork(action => {
    actions.push(action);
    return {chargeFork: structuredClone(fork), reward: action === "immediate" ? 1 : -1};
  }, ["charge_0", "charge_1", "wait"]);
  assert.deepEqual(actions, ["immediate", "immediate", "charge_1"]);
  assert.equal(result.alternatives.charge_1.reward, -1);
}

{
  let calls = 0;
  assert.throws(() => compareChargeFork(() => ({chargeFork: fork, reward: calls++}), ["charge_1"]),
    /A\/A replay differs/);
  assert.throws(() => compareChargeFork(action => ({chargeFork: action === "immediate" ? fork :
    {...fork, audit: {decisions: ["wait"]}}, reward: 1}), ["charge_1"]), /histories differ/);
}
