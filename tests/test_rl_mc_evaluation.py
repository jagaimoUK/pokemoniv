"""Check paired held-out evaluation contracts without claiming real strength."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from evaluate_rl_mc import (
    _metrics, evaluate_one, evaluate_paired, fixed_public_action, heldout_scenarios,
)
from pvpoke_rl_mc_train import PublicMonteCarloPolicy, public_state
from pvpoke_rl_mc_generalized import GeneralizedMonteCarloPolicy, coarse_public_state
from pvpoke_rl_team_preview import SixToThreeSelection
from test_rl_team_env import rosters
from test_rl_mc_train import public_tactics, FakeMatch, preview


class MatchedEvaluationTests(unittest.TestCase):
    def test_scenarios_are_deterministic_with_legal_hidden_selection(self):
        scenarios = heldout_scenarios(count=8, seed=1203)
        self.assertEqual(scenarios, heldout_scenarios(count=8, seed=1203))
        for seed, chosen, lead in scenarios:
            self.assertEqual(len(chosen), 3)
            self.assertEqual(len(set(chosen)), 3)
            self.assertTrue(all(type(i) is int and 0 <= i < 6 for i in chosen))
            self.assertIn(lead, chosen)
        with self.assertRaises(ValueError):
            heldout_scenarios(count=33, seed=1203)

    def test_native_cpu_baseline_uses_only_public_and_legal_fields(self):
        selection = SixToThreeSelection(
            *rosters(), ruleset_id="great-league-v1"
        ).observe()
        self.assertEqual(fixed_public_action(selection), "0,1,2|0")
        tactical = public_tactics()
        self.assertEqual(fixed_public_action(tactical), "fast")
        changed = copy.deepcopy(tactical)
        changed["opponent"]["secret_team"] = ["hidden"]
        self.assertEqual(fixed_public_action(changed), "fast")

        shield = copy.deepcopy(tactical)
        shield["phase"] = "shield"
        shield["legal_actions"] = ["shield_yes", "shield_no"]
        self.assertEqual(fixed_public_action(shield), "shield_yes")
        shield["own"]["team"][0]["hp"] = 10
        self.assertEqual(fixed_public_action(shield), "shield_no")

        replace = copy.deepcopy(tactical)
        replace["phase"] = "replace"
        replace["legal_actions"] = ["switch_1", "switch_2"]
        self.assertEqual(fixed_public_action(replace), "switch_1")

    def test_denominators_count_discarded_and_do_not_treat_as_loss(self):
        stats = _metrics([
            {"status": "complete", "reward": 1, "decisions": 10},
            {"status": "discarded", "reward": None, "decisions": 15},
            {"status": "complete", "reward": -1, "decisions": 7},
        ])
        self.assertEqual(stats["episodes"], 3)
        self.assertEqual(stats["complete"], 2)
        self.assertEqual(stats["discarded"], 1)
        self.assertEqual(stats["wins"], 1)
        self.assertEqual(stats["losses"], 1)
        self.assertEqual(stats["win_fraction_among_completed"], 0.5)
        self.assertEqual(stats["total_decisions"], 32)
        no_matches = _metrics([
            {"status": "discarded", "reward": None, "decisions": 4},
        ])
        self.assertIsNone(no_matches["win_fraction_among_completed"])

    def test_public_timeout_diagnostics_do_not_treat_timeout_as_a_loss(self):
        results = [
            {"status": "discarded", "outcome": "timeout", "reward": None,
             "decisions": 5,
             "action_counts": {"selection": 1, "fast": 2, "wait": 2,
                               "charged": 0, "switch": 0, "shield": 0},
             "public_clock_before_final_action": {"elapsed_ms": 239000, "turn": 478}},
            {"status": "complete", "outcome": "self_ko_win", "reward": 1,
             "decisions": 4,
             "action_counts": {"selection": 1, "fast": 1, "wait": 0,
                               "charged": 1, "switch": 1, "shield": 0},
             "public_clock_before_final_action": {"elapsed_ms": 25000, "turn": 28}},
        ]
        summary = _metrics(results)
        self.assertEqual(summary["complete"], 1)
        self.assertEqual(summary["discarded"], 1)
        self.assertEqual(summary["wins"], 1)
        self.assertEqual(summary["losses"], 0)
        self.assertEqual(summary["discard_reasons"], {"timeout": 1})
        self.assertEqual(summary["public_action_counts"]["wait"], 2)
        self.assertEqual(summary["public_action_counts"]["fast"], 3)
        self.assertEqual(summary["timeout_public_clocks"]["latest_elapsed_ms_max"], 239000)
        self.assertEqual(summary["timeout_public_clocks"]["latest_turn_min"], 478)
        with self.assertRaises(ValueError):
            _metrics([{**results[0], "decisions": 6}])

    def test_wait_reasons_are_disjoint_and_accounted_for(self):
        episode = {
            "status": "discarded", "outcome": "timeout", "reward": None,
            "decisions": 8,
            "action_counts": {
                "selection": 1, "wait": 5, "fast": 2, "charged": 0,
                "switch": 0, "shield": 0,
            },
            "public_wait_reasons": {
                "forced_only_wait": 4, "optional_wait": 1,
                "cooldown_forced": 3, "other_forced": 1,
                "fast_available_when_waiting": 1,
                "charge_available_when_waiting": 0,
            },
        }
        summary = _metrics([episode])
        self.assertEqual(summary["public_wait_reasons"]["forced_only_wait"], 4)
        self.assertEqual(summary["public_wait_reasons"]["optional_wait"], 1)
        self.assertEqual(summary["public_wait_reasons"]["cooldown_forced"], 3)
        self.assertEqual(summary["discard_reasons"], {"timeout": 1})
        self.assertEqual(summary["wins"], 0)
        self.assertEqual(summary["losses"], 0)
        invalid = copy.deepcopy(episode)
        invalid["public_wait_reasons"]["optional_wait"] = 2
        with self.assertRaises(ValueError):
            _metrics([invalid])
        invalid = copy.deepcopy(episode)
        invalid["public_wait_reasons"]["cooldown_forced"] = 5
        with self.assertRaises(ValueError):
            _metrics([invalid])

    def test_learning_coverage_fraction_has_an_explicit_denominator(self):
        stat = _metrics([
            {"status": "complete", "reward": 1, "decisions": 6,
             "coverage": {"state_hits": 4, "chosen_action_hits": 2,
                          "selection_state_seen": True,
                          "selection_action_seen": False}},
            {"status": "discarded", "reward": None, "decisions": 4,
             "coverage": {"state_hits": 1, "chosen_action_hits": 0,
                          "selection_state_seen": False,
                          "selection_action_seen": False}},
        ])
        hits = stat["learned_coverage"]
        self.assertEqual(hits["state_hits"], 5)
        self.assertEqual(hits["chosen_action_hits"], 2)
        self.assertEqual(hits["state_hit_fraction"], 0.5)
        self.assertEqual(hits["chosen_action_hit_fraction"], 0.2)
        self.assertEqual(hits["selection_state_hits"], 1)
        self.assertEqual(hits["selection_action_hits"], 0)
        self.assertEqual(hits["tactical_decisions"], 8)
        self.assertEqual(hits["tactical_state_hits"], 4)
        self.assertEqual(hits["tactical_action_hits"], 2)
        self.assertEqual(hits["tactical_state_hit_fraction"], 0.5)
        self.assertEqual(hits["tactical_action_hit_fraction"], 0.25)
        self.assertEqual(stat["complete"], 1)
        self.assertEqual(stat["discarded"], 1)

    def test_paired_comparison_excludes_nonmatching_completions(self):
        seen = []
        scripted = {
            "trained": [(1, True), (1, True), (None, False)],
            "fixed": [(-1, True), (None, False), (-1, True)],
            "untrained": [(1, True), (-1, True), (None, False)],
        }

        def fake_one(policy, label, scenario, **kwargs):
            n = scenario[0] - 900
            seen.append((label, scenario))
            reward, completed = scripted[label][n]
            return {"status": "complete" if completed else "discarded",
                    "reward": reward, "decisions": 3}

        trained, untrained = PublicMonteCarloPolicy(seed=3), PublicMonteCarloPolicy(seed=3)
        scenarios = [(900 + n, (0, 1, 2), 0) for n in range(3)]
        with patch("evaluate_rl_mc.evaluate_one", side_effect=fake_one):
            summary = evaluate_paired(
                trained=trained, untrained=untrained, scenarios=scenarios)
        self.assertEqual(
            summary["paired"]["trained_vs_fixed"],
            {"both_completed": 1, "trained_better": 1,
             "equal_return": 0, "trained_worse": 0,
             "selection_compared": 0, "same_selection": 0,
             "different_selection": 0},
        )
        self.assertEqual(
            summary["paired"]["trained_vs_untrained"],
            {"both_completed": 2, "trained_better": 1,
             "equal_return": 1, "trained_worse": 0,
             "selection_compared": 0, "same_selection": 0,
             "different_selection": 0},
        )
        self.assertEqual(summary["metrics"]["fixed"]["discarded"], 1)
        self.assertEqual(trained.completed_matches, 0)
        self.assertEqual(untrained.completed_matches, 0)
        self.assertEqual(len(seen), 9)
        for n in range(3):
            self.assertEqual(
                [x[0] for x in seen[3*n:3*n+3]],
                ["fixed", "untrained", "trained"])
            self.assertTrue(all(x[1] == scenarios[n] for x in seen[3*n:3*n+3]))

    def test_v2_evaluation_uses_exactly_the_training_encoder(self):
        # Regression: v2 previously looked up v1 hashes, reporting zero
        # coverage even after observing a trained public state/action.
        model = GeneralizedMonteCarloPolicy(seed=7)
        selection = preview()
        tactic = public_tactics()
        kind, selection_key, _ = coarse_public_state(selection)
        tactic_kind, tactic_key, _ = coarse_public_state(tactic)
        self.assertEqual(kind, "selection")
        self.assertEqual(tactic_kind, "tactics")
        self.assertNotEqual(coarse_public_state(tactic)[1],
                            public_state(tactic)[1])
        self.assertEqual(model.encode_state(selection), coarse_public_state(selection))
        self.assertEqual(model.encode_state(tactic), coarse_public_state(tactic))
        model.learn([("selection", selection_key, "0,1,2|0"),
                     ("tactics", tactic_key, "fast")],
                    reward=1, selection_reward=1)

        class PublicFakeMatch(FakeMatch):
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

        before = model.snapshot()
        with patch("evaluate_rl_mc.SixToThreeEnvironment",
                   return_value=PublicFakeMatch()):
            record = evaluate_one(model, "trained", (12, (0, 1, 2), 0))
        self.assertEqual(record["status"], "complete")
        self.assertEqual(record["coverage"]["state_hits"], 2)
        self.assertEqual(record["coverage"]["chosen_action_hits"], 2)
        self.assertTrue(record["coverage"]["selection_state_seen"])
        self.assertTrue(record["coverage"]["selection_action_seen"])
        self.assertEqual(record["selection_action"], "0,1,2|0")
        self.assertEqual(model.snapshot(), before)

    def test_v1_evaluation_encoder_remains_backward_compatible(self):
        model = PublicMonteCarloPolicy(seed=7)
        self.assertEqual(model.encode_state(preview()), public_state(preview()))
        self.assertEqual(model.encode_state(public_tactics()),
                         public_state(public_tactics()))

    def test_native_3v3_paired_evaluation_does_not_train(self):
        trained, untrained = PublicMonteCarloPolicy(seed=17), PublicMonteCarloPolicy(seed=17)
        scenario = heldout_scenarios(count=1, seed=123456)[0]
        summary = evaluate_paired(
            trained=trained, untrained=untrained, scenarios=[scenario])
        self.assertEqual(trained.completed_matches, 0)
        self.assertEqual(untrained.completed_matches, 0)
        for kind in ("fixed", "untrained", "trained"):
            stats = summary["metrics"][kind]
            self.assertEqual(stats["episodes"], 1)
            self.assertEqual(stats["complete"] + stats["discarded"], 1)
        self.assertFalse(summary["evaluation_policy_updated"])
        self.assertIsNone(summary["metrics"]["fixed"]["learned_coverage"])
        for label in ("trained", "untrained"):
            hits = summary["metrics"][label]["learned_coverage"]
            self.assertIsNotNone(hits)
            self.assertGreaterEqual(hits["state_hits"], hits["chosen_action_hits"])
            self.assertGreaterEqual(hits["state_hit_fraction"],
                                    hits["chosen_action_hit_fraction"])
        for name in ("trained_vs_fixed", "trained_vs_untrained"):
            paired = summary["paired"][name]
            self.assertEqual(paired["selection_compared"],
                             paired["same_selection"] + paired["different_selection"])


if __name__ == "__main__":
    unittest.main()
