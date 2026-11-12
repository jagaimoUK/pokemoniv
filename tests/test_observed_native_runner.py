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
                shield_rule="first_announcement", enemy_shield_rule="standard",
                opponent_attack_rule="standard", shields=(1, 1)):
        spec = scripted_spec(energy=energy, shield=1)
        spec["actions"] = []
        spec["shield_decisions"] = []
        spec["combatants"][0]["initial"]["shields"] = shields[0]
        spec["combatants"][1]["initial"]["shields"] = shields[1]
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
                "policy": policy, "opponent_shield_rule": enemy_shield_rule,
                "opponent_attack_rule": opponent_attack_rule}

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

    def test_native_charge_announcement_precedes_self_shield_commit_and_reveal(self):
        for shields, rule in (((0, 0), "always"), ((1, 1), "never"),
                              ((1, 2), "first_announcement"),
                              ((2, 1), "always"), ((2, 2), "first_announcement")):
            with self.subTest(shields=shields, rule=rule):
                req = self.request(energy=100, enemy_energy=100, shields=shields,
                                   shield_rule=rule, opponent_attack_rule="charge_if_ready")
                data = self.native(req)
                self.assertEqual(data["live_reproducibility"], "not_verified")
                self.assertFalse(data["practical_role_covered"])
                enemy_charge_events = [
                    item for item in data["native_move_events"]
                    if item["actor"] == 1 and item["kind"] == "charged"
                ]
                # Both actions were declared for the same native turn.
                self.assertTrue(enemy_charge_events)
                consumed = sum(item["shielded"] for item in enemy_charge_events)
                self.assertEqual(consumed, sum(
                    prompt["action"]["use_shield"]
                    for prompt in data["self_shield_prompts"]))
                self.assertLessEqual(consumed, shields[0])
                for prompt in data["self_shield_prompts"]:
                    visible = prompt["visible"]
                    self.assertEqual(visible["events"][-1]["kind"],
                                     "opponent_charge_announced")
                    self.assertFalse("move_id" in visible["events"][-1])
                    self.assertEqual(
                        propose(visible, req["policy"])["action"],
                        prompt["action"])
                # Fixed rules never turn this hypothetical opponent script into
                # a verified player strategy, regardless of the native winner.
                self.assertEqual(data["status"], "counterfactual_only")

    def test_native_cmp_and_cooldown_distinguish_requested_from_resolved(self):
        req = self.request(energy=100, enemy_energy=100, shields=(2, 2),
                           shield_rule="always",
                           opponent_attack_rule="charge_if_ready")
        data = self.native(req)
        first = data["own_proposals"][0]
        self.assertEqual(first["action"]["kind"], "charged")
        self.assertEqual(first["native_process"]["turn"], 1)
        self.assertTrue(first["native_process"]["valid"])
        self.assertIsNotNone(first["native_resolution"])
        self.assertEqual(first["native_resolution"]["turn"], 1)
        own_and_enemy_charges = [
            event for event in data["native_move_events"]
            if event["kind"] == "charged" and event["turn"] == 1]
        self.assertEqual({event["actor"] for event in own_and_enemy_charges}, {0, 1})
        self.assertGreaterEqual(
            data["native_cmp_audit"]["simultaneous_charge_turns_checked"], 1)
        self.assertTrue(all(event["move_id"] for event in own_and_enemy_charges))
        self.assertEqual(data["self_fast_move_turns"], 2)
        self.assertTrue(any(row["action"]["kind"] == "fast"
                            for row in data["own_proposals"]))
        # An ignored post-charge proposal and a queued fast attack should
        # not masquerade as a same-turn resolved move.
        for row in data["own_proposals"]:
            if row["native_resolution"]:
                self.assertIsNotNone(row["native_process"])
                self.assertTrue(row["native_process"]["valid"])
                self.assertEqual(row["native_resolution"]["kind"],
                                 row["action"]["kind"])
            if row["native_process"] is None:
                self.assertIsNone(row["native_resolution"])
            if row["action"]["kind"] == "fast" and row["native_resolution"]:
                self.assertGreaterEqual(row["native_resolution"]["turn"],
                                        row["turn"])
        self.assertEqual(data["live_reproducibility"], "not_verified")

    def test_never_reveal_opponent_move_id_during_shield_prompt(self):
        for enemy_energy in (0, 100):
            req = self.request(energy=0, enemy_energy=enemy_energy,
                               opponent_attack_rule="charge_if_ready",
                               shield_rule="first_announcement", shields=(2, 2))
            data = self.native(req)
            for prompt in data["self_shield_prompts"]:
                text = json.dumps(prompt["visible"], sort_keys=True)
                self.assertNotIn('"opponent_energy"', text)
                self.assertNotIn('"opponent_ivs"', text)
                self.assertEqual(propose(prompt["visible"], req["policy"])["action"],
                                 prompt["action"])
                # Charge IDs may exist from PREVIOUS resolutions, but not
                # on the charge announcement being answered now.
                self.assertNotIn("move_id", prompt["visible"]["events"][-1])
            for index, row in enumerate(data["own_proposals"]):
                self.assertEqual(row["action"],
                                 propose(row["visible"], req["policy"])["action"])
                if index > 0:
                    self.assertGreater(row["turn"],
                                       data["own_proposals"][index - 1]["turn"])
    def test_three_turn_fast_move_resolves_with_native_cooldown(self):
        # Swap the fixture roles: Azumarill's Bubble lasts three 500ms turns.
        # A future adapter must not treat a fast-move tap as damage already
        # resolved on the same turn.
        req = self.request(energy=0, enemy_energy=0, shields=(1, 1),
                           shield_rule="never")
        req["self"], req["opponent"] = req["opponent"], req["self"]
        req["initial"].reverse()
        req["shields"].reverse()
        req["policy"]["own_charged_moves"] = [
            {"move_id": "ICE_BEAM", "energy_cost": 55},
            {"move_id": "PLAY_ROUGH", "energy_cost": 60},
        ]
        result = self.native(req)
        self.assertEqual(result["self_fast_move_turns"], 3)
        self.assertEqual(result["live_reproducibility"], "not_verified")
        fasts = [row for row in result["own_proposals"]
                 if row["action"]["kind"] == "fast"
                 and row["native_process"] is not None
                 and row["native_process"]["valid"]]
        self.assertGreaterEqual(len(fasts), 2)
        self.assertGreaterEqual(fasts[1]["turn"] - fasts[0]["turn"], 3)
        self.assertEqual(fasts[0]["native_resolution"]["move_id"], "BUBBLE")
        self.assertGreaterEqual(fasts[0]["native_resolution"]["turn"],
                                fasts[0]["turn"] + 2)
        for row in result["own_proposals"]:
            self.assertEqual(propose(row["visible"], req["policy"])["action"],
                             row["action"])

    def test_fast_move_native_1_4_5_turn_boundaries_without_user_data(self):
        # WATER_GUN is genuinely legal on Quagsire. The other two are
        # synthetic move combinations in a disposable copy of the *fixture*
        # GameMaster to exercise the native 4/5-turn timing code. They do NOT
        # represent legal GO matchups or practical role recommendations.
        original = json.loads((FIXTURES / "strategy_gamemaster.json").read_text())
        for move, turns, synthetic in (
                ("WATER_GUN", 1, False),
                ("CONFUSION", 4, True),
                ("INCINERATE", 5, True)):
            with self.subTest(fast=move, turns=turns):
                req = self.request(energy=0, enemy_energy=0, shields=(1, 1),
                                   shield_rule="never")
                req["self"]["fast"] = move
                if synthetic:
                    copied = copy.deepcopy(original)
                    species = next(p for p in copied["pokemon"]
                                   if p["speciesId"] == "quagsire")
                    self.assertNotIn(move, species["fastMoves"])
                    species["fastMoves"].append(move)
                    master = self.root / ("synthetic-" + move + ".json")
                    master.write_text(json.dumps(copied, sort_keys=True))
                    req["gamemaster_path"] = str(master)
                result = self.native(req)
                self.assertEqual(result["self_fast_move_turns"], turns)
                self.assertFalse(result["practical_role_covered"])
                self.assertEqual(result["live_reproducibility"], "not_verified")
                fasts = [row for row in result["own_proposals"]
                         if row["action"]["kind"] == "fast"
                         and row["native_resolution"] is not None]
                self.assertGreaterEqual(len(fasts), 2)
                self.assertEqual(fasts[0]["native_resolution"]["move_id"], move)
                self.assertEqual(fasts[0]["native_resolution"]["turn"],
                                 fasts[0]["turn"] + turns - 1)
                self.assertGreaterEqual(fasts[1]["turn"] - fasts[0]["turn"], turns)
                for row in result["own_proposals"]:
                    self.assertEqual(propose(row["visible"], req["policy"])["action"],
                                     row["action"])

    def test_equal_attack_cmp_cannot_prove_random_tie_win(self):
        req = self.request(energy=100, enemy_energy=100, shields=(2, 2),
                           shield_rule="always",
                           opponent_attack_rule="charge_if_ready")
        req["opponent"] = copy.deepcopy(req["self"])
        req["initial"][1] = copy.deepcopy(req["initial"][0])
        result = self.native(req)
        audit = result["native_cmp_audit"]
        self.assertGreater(audit["simultaneous_charge_turns_checked"], 0)
        self.assertGreater(audit["equal_stat_turns_with_no_priority_claim"], 0)
        self.assertTrue(audit["compared_using_private_native_stats_only"])
        self.assertEqual(result["status"], "counterfactual_only")
        self.assertFalse(result["practical_role_covered"])
        self.assertEqual(result["live_reproducibility"], "not_verified")
        # The same native tie order in a deterministic engine is NOT proof
        # of either side winning GO's random CMP tie.

    def test_ko_before_charged_execution_is_not_called_a_success(self):
        req = self.request(energy=100, enemy_energy=100, shields=(0, 0),
                           shield_rule="never",
                           opponent_attack_rule="charge_if_ready")
        # Low-HP Azumarill loses CMP against Quagsire, which can knock it
        # out before the selected ICE_BEAM actually resolves.
        req["self"], req["opponent"] = req["opponent"], req["self"]
        req["initial"].reverse()
        req["shields"].reverse()
        req["initial"][0]["hp_points"] = 1
        req["policy"]["own_charged_moves"] = [
            {"move_id": "ICE_BEAM", "energy_cost": 55},
            {"move_id": "PLAY_ROUGH", "energy_cost": 60},
        ]
        result = self.native(req)
        first = result["own_proposals"][0]
        self.assertEqual(first["action"],
                         {"kind": "charged", "move_id": "ICE_BEAM"})
        self.assertIsNone(first["native_resolution"])
        self.assertFalse(first["native_resolved_same_turn"])
        self.assertFalse(result["practical_role_covered"])
        self.assertEqual(result["live_reproducibility"], "not_verified")
        self.assertEqual(propose(first["visible"], req["policy"])["action"],
                         first["action"])


if __name__ == "__main__":
    unittest.main()
