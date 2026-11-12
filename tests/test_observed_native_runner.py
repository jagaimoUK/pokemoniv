"""Native multi-turn *counterfactual* observation-policy integration tests.

Sandbox and standard PvPoke remain unchanged. The native JS runner uses the
same pinned engine with an isolated action-policy override, not a live gameplay
strategy or a recommendation source.
"""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from pvpoke_battle_service import BattleService, _canonical_json
from pvpoke_battle_store import BattleStore
from pvpoke_child_env import child_environment
from pvpoke_direct_backend import DirectMatrixClient
from pvpoke_observed_policy import propose
from pvpoke_sandbox import SandboxService
from test_battle_service import FIXTURES
from test_sandbox import scripted_spec

RUNNER = Path(__file__).resolve().parents[1] / "pvpoke_observed_native_runner.js"


class NativeObservedMultiTurnTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.client = DirectMatrixClient(
            gamemaster=FIXTURES / "strategy_gamemaster.json", log_dir=self.root)
        self.addCleanup(self.client.close)
        self.standard = BattleService(
            self.client, store=BattleStore(self.root / "battle_analysis.sqlite3"))
        self.sandbox = SandboxService(self.standard)

    def request(self, energy=0, enemy_energy=0, enemy_ivs=None,
                shield_rule="first_announcement", enemy_shield_rule="standard"):
        spec = scripted_spec(energy=energy, shield=1)
        spec["actions"] = []
        spec["shield_decisions"] = []
        spec["combatants"][1]["initial"]["energy"] = enemy_energy
        if enemy_ivs is not None:
            spec["combatants"][1]["ivs"] = enemy_ivs
        _, native = self.sandbox.prepare(spec)
        policy = {
            "own_charged_moves": [
                {"move_id": "AQUA_TAIL", "energy_cost": 35},
                {"move_id": "STONE_EDGE", "energy_cost": 55},
            ],
            "energy_reserve": 0,
            "shield_rule": shield_rule,
        }
        return {**{key: native[key] for key in ("self", "opponent", "initial", "shields")},
                "gamemaster_path": str(self.client.gamemaster),
                "policy": policy, "opponent_shield_rule": enemy_shield_rule}

    def native(self, request, *, good=True):
        process = subprocess.run(
            ["node", str(RUNNER)], input=_canonical_json(request),
            capture_output=True, timeout=20,
            env=child_environment({"PVP_PVPOKE_SOURCE": str(self.client.source)}))
        if not good:
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(process.stdout, b"")
            return process.stderr.decode("utf8")
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf8"))
        return json.loads(process.stdout)

    def test_multi_turn_native_actions_agree_with_pure_visible_policy(self):
        req = self.request(energy=0, shield_rule="first_announcement")
        # subprocess is a process-global Python module: patching its run()
        # in Sandbox also blocks this test harness's intended native Node
        # process. Instead, assert no persistent Sandbox/standard DB is made.
        data = self.native(req)
        self.assertEqual(data["schema"], "observed-native-counterfactual-v1")
        self.assertEqual(data["status"], "counterfactual_only")
        self.assertFalse(data["observation_provenance_verified"])
        self.assertFalse(data["practical_role_covered"])
        self.assertEqual(data["live_reproducibility"], "not_verified")
        decisions = data["own_proposals"]
        self.assertGreaterEqual(len(decisions), 3)
        self.assertTrue(any(row["action"]["kind"] == "fast" for row in decisions))
        self.assertTrue(any(row["action"]["kind"] == "charged" for row in decisions))
        for row in decisions:
            self.assertEqual(propose(row["visible"], req["policy"])["action"],
                             row["action"])
            self.assertEqual(set(row["visible"]), {
                "turn", "phase", "own_energy", "own_shields",
                "opponent_shields_visible", "own_can_act", "events"})
            self.assertTrue(all(set(event) <= {"turn", "kind", "move_id"}
                                for event in row["visible"]["events"]))
        self.assertFalse((self.root / "battle_analysis.sqlite3").exists())

    def test_hidden_world_pair_and_opponent_shield_branches_are_theoretical(self):
        worlds = [
            self.request(energy=100, enemy_energy=0,
                         enemy_ivs={"attack": 0, "defense": 0, "hp": 0},
                         enemy_shield_rule="never"),
            self.request(energy=100, enemy_energy=100,
                         enemy_ivs={"attack": 0, "defense": 15, "hp": 15},
                         enemy_shield_rule="always"),
        ]
        data = [self.native(world) for world in worlds]
        for row in data:
            self.assertGreaterEqual(len(row["own_proposals"]), 2)
            self.assertEqual(row["own_proposals"][0]["action"],
                             {"kind": "charged", "move_id": "AQUA_TAIL"})
            self.assertEqual(row["own_proposals"][0]["visible"]["events"], [])
            self.assertEqual(row["live_reproducibility"], "not_verified")
            self.assertFalse(row["practical_role_covered"])
        # Different hidden opponent energy/IV and opponent shield policy do
        # not change the self choice when the first visible input is equal.
        self.assertEqual(data[0]["own_proposals"][0]["visible"],
                         data[1]["own_proposals"][0]["visible"])
        for row, req in zip(data, worlds):
            for action in row["own_proposals"]:
                self.assertEqual(action["action"],
                                 propose(action["visible"], req["policy"])["action"])
            for shield in row["self_shield_audit"]:
                self.assertTrue(shield["chosen_without_move_identity"])

    def test_tampered_public_policy_or_hidden_fields_never_execute(self):
        req = self.request()
        for malformed in (
            {**req, "opponent_private_energy": 100},
            {**req, "policy": {**req["policy"], "unrevealed_opponent_move": "ICE_BEAM"}},
            {**req, "policy": {**req["policy"], "own_charged_moves": [
                {"move_id": "AQUA_TAIL", "energy_cost": 1},
                {"move_id": "STONE_EDGE", "energy_cost": 55},
            ]}},
            {**req, "policy": {**req["policy"], "shield_rule": "if_hidden_move_is_strong"}},
        ):
            with self.subTest(keys=malformed.keys()):
                error = self.native(malformed, good=False)
                self.assertTrue(error)

    def test_invalid_move_or_native_form_does_not_promote_result(self):
        req = self.request()
        req["policy"]["own_charged_moves"][0]["move_id"] = "ICE_BEAM"
        self.assertIn("equipped", self.native(req, good=False))


if __name__ == "__main__":
    unittest.main()
