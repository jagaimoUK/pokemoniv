"""Stage-5 read-only observed-policy integration, entirely synthetic fixtures."""
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pvpoke_battle_service import BattleService
from pvpoke_battle_store import BattleStore
from pvpoke_direct_backend import DirectMatrixClient
from pvpoke_missing_analysis import MissingAnalysis
from pvpoke_observed_evidence import compare_observed, _policy_condition
from pvpoke_observed_search import ObservedSearch
from pvpoke_role_evaluation import RoleEvaluation, condition_id
from pvpoke_sandbox import SandboxService
from test_battle_service import FIXTURES
from test_sandbox import scripted_spec


class MissingObservedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = BattleStore(self.root / "analysis.sqlite3")
        self.client = DirectMatrixClient(gamemaster=FIXTURES / "strategy_gamemaster.json",
                                         log_dir=self.root)
        self.addCleanup(self.client.close)
        self.service = BattleService(self.client, store=self.store)
        self.sandbox = SandboxService(self.service)
        self.world = scripted_spec(energy=0, shield=1)
        self.world["actions"] = []
        self.world["shield_decisions"] = []
        self.controllers = [{"attack": "standard", "shield": "never"}]
        self.branches = [{"fast_delay": 0, "miss_first_fast": False,
                          "reverse_fast_batch": False}]
        self.roles = [{"id": "win", "priority": 3, "outcomes": ["self_ko_win"],
                       "minimum": {"hp": 0, "energy": 0, "shields": 0}}]

    def evaluation(self, requirement=None):
        request = {"schema": self.world["schema"], "mode": "standard",
                   "rules": self.world["rules"], "combatants": self.world["combatants"]}
        analysis = MissingAnalysis(self.store)
        analysis_id = analysis.save_plan(self.service, [request])
        normalized, _ = self.service._prepare(request)
        role = {"role_id": "win", "revision": 1, "meta_snapshot": "a" * 64,
                "priority": 3, "requirements": {
                    condition_id(normalized, full_hp=True):
                        requirement or {"outcomes": ["self_win"]}}}
        return RoleEvaluation(self.store).evaluate(
            analysis_id, role, active_versions=self.service.versions, normalizer=self.service)

    def observed(self, *, world=None, horizon=1, roles=None):
        return ObservedSearch(self.sandbox).start(
            [self.world if world is None else world], self.controllers,
            self.branches, horizon, roles=self.roles if roles is None else roles)["search_id"]

    def test_policy_scenario_counts_are_not_combined_across_opponents(self):
        policy = {"policy_hash": "e" * 64,
                  "outcomes": ["self_ko_win", "opponent_ko_win", None, "timeout"],
                  "roles": [{"id": "win", "scenario_meets": [True, False, None, False]}]}
        left = _policy_condition(policy, [0, 2], ["win"])
        right = _policy_condition(policy, [1, 3], ["win"])
        self.assertEqual(left["outcomes"]["self_ko_win"], 1)
        self.assertEqual(left["outcomes"]["opponent_ko_win"], 0)
        self.assertEqual(left["outcomes"]["unknown"], 1)
        self.assertIsNone(left["aligned_roles"][0]["meets"])
        self.assertEqual(right["outcomes"]["opponent_ko_win"], 1)
        self.assertEqual(right["outcomes"]["timeout"], 1)
        self.assertEqual(right["outcomes"]["self_ko_win"], 0)
        self.assertIs(right["aligned_roles"][0]["meets"], False)

    def test_link_matches_only_exact_build_and_starting_conditions_without_writes(self):
        role = self.evaluation()
        search_id = self.observed()
        old = hashlib.sha256(self.store.path.read_bytes()).hexdigest()
        with patch.object(self.sandbox.standard.client, "strategy",
                          side_effect=AssertionError("no native calculations")):
            result = compare_observed(self.service, role["evaluation_id"], [search_id])
        self.assertEqual(result["schema"], "missing-observed-evidence-v1")
        self.assertEqual(result["new_battles"], 0)
        self.assertTrue(result["standard_assessment_unchanged"])
        self.assertFalse(result["practical_role_covered"])
        self.assertEqual(result["information_fairness"], "not_established")
        self.assertEqual(result["live_reproducibility"], "not_verified")
        self.assertEqual(len(result["links"]), 1)
        linked = result["links"][0]
        self.assertEqual(linked["matching_worlds"], 1)
        self.assertEqual(linked["additional_worlds"], 0)
        self.assertEqual(len(linked["conditions"]), 1)
        self.assertEqual(linked["conditions"][0]["aligned_role_ids"], ["win"])
        self.assertIsNone(linked["conditions"][0]["standard_meets"])
        self.assertEqual(linked["evaluation_count"], 0)
        self.assertEqual(old, hashlib.sha256(self.store.path.read_bytes()).hexdigest())

    def test_different_opponent_iv_and_own_energy_cannot_be_joined(self):
        role = self.evaluation()
        for variant in ("opponent_iv", "own_energy", "other_build"):
            with self.subTest(variant=variant):
                other = copy.deepcopy(self.world)
                if variant == "opponent_iv":
                    # Lowering DEF remains legal at the same level and CP cap.
                    other["combatants"][1]["ivs"]["defense"] = 14
                elif variant == "own_energy":
                    other["combatants"][0]["initial"]["energy"] = 35
                else:
                    other["combatants"][0]["ivs"]["defense"] = (
                        other["combatants"][0]["ivs"]["defense"] + 1) % 16
                with self.assertRaisesRegex(ValueError, "does not match"):
                    compare_observed(self.service, role["evaluation_id"],
                                     [self.observed(world=other)])

    def test_unrelated_role_metrics_are_not_claimed_equivalent(self):
        role = self.evaluation({"minimum": {"fast_damage": 12}})
        result = compare_observed(self.service, role["evaluation_id"], [self.observed()])
        self.assertEqual(result["links"][0]["conditions"][0]["aligned_role_ids"], [])

    def test_foreign_owner_stale_search_and_invalid_ids_fail_closed(self):
        role = self.evaluation()
        search_id = self.observed()
        foreign = BattleService(
            self.client, store=BattleStore(self.store.path, owner_scope="foreign"))
        with self.assertRaisesRegex(ValueError, "unavailable for this owner"):
            compare_observed(foreign, role["evaluation_id"], [search_id])
        with self.assertRaises(ValueError):
            compare_observed(self.service, role["evaluation_id"], [search_id, search_id])
        with self.assertRaises(ValueError):
            compare_observed(self.service, role["evaluation_id"], ["x" * 64])
        with patch("pvpoke_observed_search.versions", return_value={}):
            with self.assertRaisesRegex(ValueError, "stale"):
                compare_observed(self.service, role["evaluation_id"], [search_id])

    def test_multiple_saved_jobs_do_not_merge_policies(self):
        role = self.evaluation()
        ids = [self.observed(horizon=horizon) for horizon in (1, 2)]
        result = compare_observed(self.service, role["evaluation_id"], ids)
        self.assertEqual([row["search_id"] for row in result["links"]], ids)
        self.assertTrue(all(row["build_id"] == result["links"][0]["build_id"]
                            for row in result["links"]))


if __name__ == "__main__":
    unittest.main()
