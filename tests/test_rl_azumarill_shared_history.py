"""Keep public behavior trajectories and native KO rewards paired during training."""
import json
import unittest
from unittest.mock import patch

from pvpoke_rl_mc_train import PublicMonteCarloPolicy
from test_rl_mc_train import preview, public_tactics
from tools.evaluate_rl_azumarill_natural_energy import WINDOWS as PRIOR_WINDOWS
from tools.evaluate_rl_azumarill_shared_history import (
    EVAL_WINDOWS, ROSTERS, TRAIN_WINDOW, _validate_split, evaluate_shared_history, train_shared, window_cases,
)


class OneTurnWorker:
    def __init__(self):
        self.resets = []
        self.actions = []

    def reset(self, handoff, *, seed, shields):
        self.resets.append((seed, shields))
        view = public_tactics()
        view["own"]["team"][0]["energy_points"] = seed * 10
        return {"observation": view}

    def step(self, action):
        self.actions.append(action)
        target = {1: 1, 2: None, 3: -1}[self.resets[-1][0]]
        return {
            "observation": None, "reward": target,
            "terminated": target is not None, "truncated": target is None,
            "info": {
                "outcome": {1: "self_ko_win", None: "timeout", -1: "opponent_ko_win"}[target],
                "training_eligible": target is not None,
            },
        }


class SharedHistoryTests(unittest.TestCase):
    def test_shared_actions_and_ko_rewards_exclude_timeouts(self):
        selection_view = preview()
        cases = [
            {"roster": "test", "seed": seed, "opponent_shields": 2, "handoff": {},
             "selection": selection_view["legal_actions"][0], "selection_view": selection_view,
             "explore": False}
            for seed in (1, 2, 3)
        ]
        original = PublicMonteCarloPolicy.learn
        observed = {}

        def record(model, decisions, *, reward, selection_reward):
            observed.setdefault(model.MODEL_VERSION, []).append((decisions, reward, selection_reward))
            return original(model, decisions, reward=reward, selection_reward=selection_reward)

        worker = OneTurnWorker()
        with patch.object(PublicMonteCarloPolicy, "learn", record):
            snapshots, report = train_shared(worker, cases)

        self.assertEqual(worker.resets, [(seed, (2, 2)) for seed in (1, 2, 3)])
        self.assertEqual(worker.actions, ["fast"] * 3)
        self.assertEqual((report["attempted"], report["trained"], report["excluded"]), (3, 2, 1))
        self.assertEqual(report["outcomes"], {"self_ko_win": 1, "timeout": 1, "opponent_ko_win": 1})
        v2, energy = (observed[snapshots[name]["schema"]] for name in ("v2", "energy"))
        for expected, left, right in zip((1, -1), v2, energy, strict=True):
            self.assertEqual(left[1:], right[1:])
            self.assertEqual(left[1:], (expected, expected))
            self.assertEqual([(kind, action) for kind, _, action in left[0]],
                             [(kind, action) for kind, _, action in right[0]])
            self.assertNotEqual(left[0][1][1], right[0][1][1])
        self.assertEqual(snapshots["v2"]["completed_matches"], snapshots["energy"]["completed_matches"])
        self.assertEqual(snapshots["v2"]["completed_matches"], 2)
        self.assertNotEqual(snapshots["v2"]["values"]["tactics"], snapshots["energy"]["values"]["tactics"])

    def test_fixed_split_and_native_smoke(self):
        train = window_cases(TRAIN_WINDOW)
        evaluation = [case for window in EVAL_WINDOWS for case in window_cases(window)]
        self.assertEqual((len(train), len(evaluation)), (96, 72))
        self.assertEqual({case["roster"] for case in evaluation}, {row[0] for row in ROSTERS})
        self.assertTrue(all(case["opponent_shields"] == 2 for case in train + evaluation))
        prior = {seed for window in PRIOR_WINDOWS for seed in range(window, window + 15)}
        self.assertTrue(prior.isdisjoint({case["seed"] for case in train + evaluation}))
        _validate_split(train, evaluation)
        with self.assertRaises(ValueError):
            _validate_split(train, [{**evaluation[0], "seed": train[0]["seed"]}])
        with self.assertRaises(ValueError):
            _validate_split(train, [{**train[0], "seed": evaluation[0]["seed"]}])

        train_sample, eval_sample = {}, {}
        for case in train:
            train_sample.setdefault(case["roster"], case)
        for case in evaluation:
            eval_sample.setdefault(case["roster"], case)
        batches = {TRAIN_WINDOW: list(train_sample.values()), EVAL_WINDOWS[0]: list(eval_sample.values())}
        with patch("tools.evaluate_rl_azumarill_shared_history.window_cases", side_effect=batches.__getitem__):
            result = evaluate_shared_history(windows=EVAL_WINDOWS[:1])

        self.assertEqual(result["starting_shields"], [2, 2])
        self.assertTrue(result["policy_snapshots_unchanged"])
        training = result["training"]
        self.assertEqual({row["completed_matches"] for row in training["models"].values()}, {training["trained"]})
        self.assertEqual(training["attempted"], len(train_sample))
        self.assertEqual(result["evaluation_planned_histories"], len(eval_sample))
        self.assertFalse(result["ruleset_distinction"]["worlds_2026_mimikyu"]["tournament_eligible"])
        self.assertTrue(result["ruleset_distinction"]["cs_2026_11_16_mimikyu"]["tournament_eligible"])
        hp_60 = result["summary"]["hp_60"]
        self.assertGreater(hp_60["matched_forks"], 0)
        for name in ("v2", "energy"):
            stats = hp_60["policies"][name]["stats"]
            self.assertEqual(stats["choices"], stats["hits"] + stats["cpu_fallbacks"])
            self.assertLessEqual(stats["actions_different_from_cpu"], stats["hits"])
        for field in ("handoff", "selection_view", "private_replay", "opponent_team", "energy_points"):
            self.assertNotIn(f'"{field}"', json.dumps(result))
