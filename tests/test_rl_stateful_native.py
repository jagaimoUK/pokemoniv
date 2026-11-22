"""Native in-memory step vs unmodified fast-only PvPoke calculation.

This tests an experimental 1v1 baseline, not full 3v3 or human-realistic play.
"""
import json
from pathlib import Path
import subprocess
import unittest

import test_observed_native_runner as fixtures
from pvpoke_child_env import child_environment

ROOT = Path(__file__).resolve().parents[1]
DRIVER = r"""
const fs = require('node:fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const {loadMaster, strategyRunner} = require('./pvpoke_node_matrix.js');
const {createStatefulSession} = require('./pvpoke_rl_stateful_native.js');
const prepared = input.prepared;
const battle = {self: prepared.self, opponent: prepared.opponent,
    initial: prepared.initial, shields: prepared.shields,
    public_moves: false, bait: [false, false],
    attack_policies: ['fast_only', 'standard'],
    shield_policies: [{kind:'manual',decisions:Array(512).fill(false)},
                       {kind:'standard'}]};
let nativeAudit = null;
const session = createStatefulSession(prepared, {
  horizon: 500, _testTerminalAudit: record => { nativeAudit = record; },
});
const publicInitial = session.observe();
let result = null, steps = 0, charged = false, chargedSeen = false;
while (steps++ < 500) {
  const view = session.observe();
  if (!view) throw Error('Ended without result');
  let action = view.legal_actions.includes('fast') ? 'fast' : 'wait';
  if (input.attempt_charge && !charged && view.legal_actions.includes('charge_0')) {
    action = 'charge_0'; charged = true;
  }
  result = session.step(action);
  if (result.observation?.observed_moves.some(e => e.actor === 0 && e.kind === 'charged')) {
    chargedSeen = true;
  }
  if (result.terminated || result.truncated) break;
}
if (!result || (!result.terminated && !result.truncated)) throw Error('No episode end');
let baseline = null;
if (!input.attempt_charge) {
  loadMaster(prepared.gamemaster_path);
  baseline = strategyRunner().run(battle);
}
process.stdout.write(JSON.stringify({first:publicInitial, result,
  step_count:steps, charge_requested:charged, charge_seen:chargedSeen,
  native_audit: nativeAudit,
  baseline:baseline && {outcome:baseline.outcome, turns:baseline.turns,
     terminal:baseline.terminal,
     events:baseline.events.map(({turn,actor,kind,move_id,shielded}) =>
       ({turn,actor,kind,move_id,shielded}))}}));
"""


class StatefulNativeTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.NativeObservedMultiTurnTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture

    def run_native(self, *, shields=(0, 0), energy=0,
                   enemy_energy=0, charge=False):
        prepared = self.fixture.request(
            energy=energy, enemy_energy=enemy_energy, shields=shields)
        proc = subprocess.run(
            ["node", "-e", DRIVER],
            input=json.dumps({"prepared": prepared,
                              "attempt_charge": charge}).encode(),
            capture_output=True, cwd=ROOT, timeout=25,
            env=child_environment({"PVP_PVPOKE_SOURCE": str(self.fixture.client.source)}))
        self.assertEqual(proc.returncode, 0, proc.stderr.decode(errors="replace"))
        return json.loads(proc.stdout)

    def test_same_native_result_as_unmodified_fast_only(self):
        scenarios = (
            ((0, 0), 0, 0),
            ((1, 1), 0, 0),
            ((2, 0), 0, 100),
            ((1, 2), 35, 50),
        )
        for shields, energy, enemy_energy in scenarios:
            with self.subTest(shields=shields, energy=energy,
                              enemy_energy=enemy_energy):
                data = self.run_native(shields=shields, energy=energy,
                                       enemy_energy=enemy_energy)
                self.assertFalse(data["result"]["truncated"])
                self.assertEqual(data["result"]["info"]["outcome"], data["baseline"]["outcome"])
                self.assertEqual(data["result"]["info"]["turns"], data["baseline"]["turns"])
                self.assertEqual(data["native_audit"]["terminal"],
                                 data["baseline"]["terminal"])
                self.assertEqual(data["native_audit"]["events"],
                                 data["baseline"]["events"])
                self.assertEqual(data["result"]["reward"],
                    1 if data["baseline"]["outcome"] == "self_ko_win" else
                    -1 if data["baseline"]["outcome"] == "opponent_ko_win" else 0)
                self.assertLessEqual(data["step_count"], 500)

    def test_initial_observation_does_not_include_hidden_energy_or_moveset(self):
        data = self.run_native()
        view = data["first"]
        self.assertEqual(view["turn"], 1)
        self.assertEqual(view["opponent"]["shields"], 0)
        self.assertEqual(view["observed_moves"], [])
        self.assertNotIn("energy", view["opponent"])
        self.assertNotIn("charged", view["opponent"])
        self.assertFalse(view["capabilities"]["switching"])
        self.assertFalse(view["capabilities"]["manual_shield"])

    def test_charged_action_can_be_delivered_from_new_decision(self):
        data = self.run_native(energy=100, charge=True)
        self.assertTrue(data["charge_requested"])
        self.assertTrue(data["charge_seen"])
        self.assertIn(data["result"]["info"]["outcome"],
                      ("self_ko_win", "opponent_ko_win", "simultaneous_ko", "timeout"))


if __name__ == "__main__":
    unittest.main()
