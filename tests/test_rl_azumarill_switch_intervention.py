"""Verify matched switch forks, execution, and the common CPU continuation."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, call, patch

from test_rl_mc_train import preview
from tools.evaluate_rl_azumarill_natural_energy import POLICY_CLASSES, _forks
from tools.evaluate_rl_azumarill_shared_history import EVAL_WINDOWS, TRAIN_WINDOW, _validate_split
from tools.evaluate_rl_azumarill_switch_intervention import (
    ROSTERS, WINDOWS, _run_case, find_switch_fork, play_one_action, summarize, training_cases, window_cases,
)
from tools.evaluate_rl_azumarill_switch_rl_150s import _SwitchRlWorkerTransport
from tools.evaluate_rl_azumarill_switch_rl_targeted import ROOT
from tools.evaluate_rl_quagsire import shadow_gamemaster

MODULE = "tools.evaluate_rl_azumarill_switch_intervention"


class SwitchInterventionTests(unittest.TestCase):
    def test_collects_only_the_first_two_hit_switch_disagreement(self):
        view = {"legal_actions": ["fast", "switch_1", "switch_2"]}
        worker = Mock()
        worker.step.return_value = {"observation": view}
        agreed = {"v2": "fast", "energy": "fast"}
        differing = {"v2": "switch_2", "energy": "switch_1"}
        hit = {"v2": True, "energy": True}
        with (patch(f"{MODULE}._forks", return_value={"hp_60": (("fast",), view)}),
              patch(f"{MODULE}.replay_fork", return_value={"observation": view}),
              patch(f"{MODULE}._candidates", side_effect=[(agreed, hit), (differing, hit)])):
            found, excluded = find_switch_fork(worker, {}, {}, {})
        self.assertEqual(found, ((("fast", "fast"), view), differing))
        self.assertIsNone(excluded)
        worker.step.assert_called_once_with("fast")

        for other, other_hit, expected in (
            ("switch_1", False, "first_difference_state_miss"),
            ("fast", True, "first_difference_not_two_switches"),
        ):
            with (patch(f"{MODULE}._forks", return_value={"hp_60": ((), view)}),
                  patch(f"{MODULE}.replay_fork", return_value={"observation": view}),
                  patch(f"{MODULE}._candidates",
                        return_value=({"v2": "switch_2", "energy": other}, {"v2": True, "energy": other_hit}))):
                self.assertEqual(find_switch_fork(worker, {}, {}, {}), (None, expected))

    def test_summary_keeps_timeouts_and_unresolved_switches_distinct(self):
        def arm(outcome, reward, elapsed_ms, resolved=True):
            return {"outcome": outcome, "reward": reward, "elapsed_ms": elapsed_ms,
                    "switch_resolved": resolved, "target_species": "fixture"}

        ko = arm("self_ko_win", 1, 190000)
        late_ko = arm("self_ko_win", 1, 210000)
        timed = arm("timeout", None, 240000)
        blocked = arm("timeout", None, 240000, resolved=False)
        fork = {"public_view_sha256": "same-fork"}
        result = summarize([
            {"fork": fork, "v2": ko, "energy": late_ko},
            {"fork": fork, "v2": timed, "energy": ko},
            {"fork": fork, "v2": ko, "energy": blocked},
            {"excluded": "hp_60_not_reached"},
        ])
        self.assertEqual(result["planned_histories"], 4)
        self.assertEqual(result["eligible_forks"], 3)
        self.assertEqual(result["distinct_public_forks"], 1)
        self.assertEqual(result["both_switches_resolved"], 2)
        self.assertEqual(result["timeouts"], {"v2": 1, "energy": 0, "both": 0})
        self.assertEqual(result["ko_reward_comparison"]["both_completed"], 1)
        self.assertEqual(result["both_ko_elapsed_delta_ms_energy_minus_v2"], {20000: 1})
        self.assertEqual(len(result["intention_outcomes"]), 3)
        self.assertEqual(len(result["resolved_outcomes"]), 2)

    def test_only_the_first_action_is_overridden(self):
        own = {"active_slot": 0, "team": [{"species": "quagsire"}, {"species": "fearow"}]}
        view = {"own": own, "phase": "turn", "legal_actions": ["switch_1"], "recent_events": []}
        post_switch = {"legal_actions": ["fast", "wait"]}
        worker = Mock()
        worker.public_replay.return_value = {"events": [{
            "seq": 1, "side": "self", "kind": "switch", "previous_species": "quagsire",
            "species": "fearow", "forced": False,
        }]}
        worker.step.side_effect = [
            {"observation": post_switch},
            {"observation": None, "reward": None, "terminated": False, "truncated": True,
             "info": {"outcome": "timeout", "training_eligible": False, "elapsed_ms": 240000}},
        ]
        with (patch(f"{MODULE}.replay_fork", return_value={"observation": view}),
              patch(f"{MODULE}.choose_team_cpu", return_value="fast") as cpu):
            result = play_one_action(worker, {}, ((), view), "switch_1")
        cpu.assert_called_once_with(post_switch)
        self.assertEqual(worker.step.call_args_list, [call("switch_1"), call("fast")])
        self.assertTrue(result["switch_resolved"])
        self.assertEqual(result["outcome"], "timeout")
        self.assertIsNone(result["reward"])

    def test_fixed_windows_and_native_switches_then_cpu(self):
        self.assertEqual(WINDOWS, (3000012, 3001012))
        prior = {seed for window in EVAL_WINDOWS for seed in range(window, window + 18)}
        for window in WINDOWS:
            cases = window_cases(window)
            self.assertEqual(len(cases), 36)
            self.assertEqual({case["roster"] for case in cases}, {row[0] for row in ROSTERS})
            seeds = {case["seed"] for case in cases}
            self.assertEqual(seeds, set(range(window, window + 18)))
            self.assertTrue(seeds.isdisjoint(prior))
            prior.update(seeds)
            _validate_split(training_cases(TRAIN_WINDOW), cases)

        case = next(case for case in window_cases(WINDOWS[0])
                    if case["roster"] == "fearow_reference"
                    and case["handoff"]["own_team"][0]["species"] == "quagsire_shadow")
        with TemporaryDirectory(prefix="switch-intervention-test-") as directory:
            path = Path(directory) / "shadow.json"
            path.write_text(json.dumps(shadow_gamemaster()), encoding="utf-8")
            with _SwitchRlWorkerTransport(ROOT / "vendor/pvpoke", path) as worker:
                _, view = _forks(worker, case)["hp_60"]
                models = {name: cls(seed=0) for name, cls in POLICY_CLASSES.items()}
                for name, action in (("v2", "switch_2"), ("energy", "switch_1")):
                    model = models[name]
                    selection, key, legal = model.encode_state(preview())
                    kind, tactical_key, available = model.encode_state(view)
                    self.assertIn(action, available)
                    model.learn([(selection, key, legal[0]), (kind, tactical_key, action)],
                                reward=1, selection_reward=1)
                tables = {name: model.snapshot()["values"]["tactics"] for name, model in models.items()}
                result = _run_case(worker, case, models, tables)

        self.assertEqual(result["fork"]["phase"], "turn")
        self.assertTrue(50 <= result["fork"]["own_hp_pct"] < 75)
        self.assertEqual(result["v2"]["target_species"], "wigglytuff")
        self.assertEqual(result["energy"]["target_species"], "fearow")
        self.assertTrue(all(result[name]["switch_resolved"] for name in POLICY_CLASSES))
        for name in POLICY_CLASSES:
            if result[name]["outcome"] == "timeout":
                self.assertIsNone(result[name]["reward"])
        for field in ("handoff", "private_replay", "opponent_team", "energy_points"):
            self.assertNotIn(f'"{field}"', json.dumps(result))
