"""Verify predeclared matchup controls and public-only branch setup."""
from collections import defaultdict
import unittest
from unittest.mock import patch

from pvpoke_rl_team_preview import SixToThreeSelection
from tools import evaluate_rl_branches as branches, evaluate_rl_openings as openings


class OpeningStudyTests(unittest.TestCase):
    def test_crossed_setup_uses_native_slots_and_crosses_each_seed_with_each_lead(self):
        seed_sets = []
        for window in openings.SEED_WINDOWS:
            with patch.object(openings, "compare_cases", return_value={}) as compare:
                report = openings.compare_openings(pair="switch", window=window)
            self.assertEqual(len(report["matchups"]), 16)
            groups = defaultdict(set)
            pool_trios = defaultdict(set)
            seeds = set(range(window, window + openings.SEEDS_PER_WINDOW))
            seed_sets.append(seeds)
            for row, call in zip(report["matchups"], compare.call_args_list, strict=True):
                args = call.kwargs
                own, public, enemy = args["teams"]
                self.assertEqual({seed for seed, _, _ in args["cases"]}, seeds)
                self.assertIs(args["frontier_filter"], openings.opening_switch)
                self.assertIsNone(args["prefix_policy"])
                for _, trio, lead in args["cases"]:
                    preview = SixToThreeSelection(own, public, enemy, trio, lead,
                                                  ruleset_id="great-league-v1")
                    preview.choose(args["selection"])
                    handoff = preview._private_engine_input()
                    self.assertEqual([p["species"] for p in handoff["own_team"]],
                                     [row["own_lead"], row["slot_1"], "wigglytuff"])
                    self.assertEqual(handoff["opponent_team"][0]["species"], row["opponent_lead"])
                    pool = tuple(p["species"] for p in enemy)
                    pool_trios[pool].add(tuple(trio))
                    groups[pool].add(row["opponent_lead"])
            self.assertEqual(sorted(map(len, groups.values())), [2, 2])
            self.assertTrue(all(len(trios) == 1 for trios in pool_trios.values()))
        self.assertFalse(seed_sets[0] & seed_sets[1])

    def test_switch_filter_limits_window_and_uses_visible_lead_and_bench(self):
        opponent = {"revealed": [{"fainted": False}]}
        own = {"active_slot": 0, "team": [{}, {"hp": 99, "max_hp": 99}, {}]}
        view = {"turn": 2, "own": own, "opponent": opponent}
        self.assertTrue(openings.opening_switch(view))
        self.assertTrue(openings.opening_switch({**view, "turn": 8}))
        for modified in (
            {**view, "turn": 1}, {**view, "turn": 9},
            {**view, "own": {**own, "active_slot": 1}},
            {**view, "opponent": {"revealed": [{"fainted": False}, {"fainted": False}]}},
            {**view, "own": {**own, "team": [{}, {"hp": 98, "max_hp": 99}, {}]}},
        ):
            self.assertFalse(openings.opening_switch(modified))

    def test_charge_setup_banks_a_legal_fast_and_keeps_a_common_bench(self):
        view = {"phase": "turn", "own": {"active_slot": 0},
                "legal_actions": ["charge_0", "fast", "wait", "switch_1"]}
        self.assertEqual(openings.bank_charge_energy(view), "fast")
        self.assertEqual(openings.bank_charge_energy({**view, "legal_actions": ["wait"]}), "wait")
        with patch.object(openings, "compare_cases", return_value={}) as compare:
            report = openings.compare_openings(pair="charge", window=openings.SEED_WINDOWS[0])
        self.assertEqual(len(report["matchups"]), 8)
        self.assertEqual({r["slot_1"] for r in report["matchups"]}, {"fearow"})
        self.assertTrue(all(c.kwargs["prefix_policy"] is openings.bank_charge_energy and
                            c.kwargs["frontier_filter"] is openings.own_lead_active
                            for c in compare.call_args_list))

    def test_native_charge_forks_have_both_actions_in_the_same_public_view(self):
        rollout = branches._roll_out

        def inspect(env, first_action, budget, prefix_audit):
            view = env.observe()
            self.assertEqual(view["phase"], "turn")
            self.assertEqual(view["own"]["active_slot"], 0)
            self.assertTrue({"charge_0", "charge_1"} <= set(view["legal_actions"]))
            return rollout(env, first_action, budget, prefix_audit)

        with (patch.object(openings, "OPPONENT_POOLS", ((3, (1, 3, 5), (1,)),)),
              patch.object(openings, "SEEDS_PER_WINDOW", 1),
              patch.object(branches, "_roll_out", side_effect=inspect) as recorded):
            report = openings.compare_openings(pair="charge", window=openings.SEED_WINDOWS[0])
        self.assertEqual([r["attempted_pairs"] for r in report["matchups"]], [1, 1])
        self.assertEqual([r["same_action_replay_matches"] for r in report["matchups"]], [1, 1])
        self.assertEqual([c.args[1] for c in recorded.call_args_list],
                         ["charge_0", "charge_0", "charge_1"] * 2)
