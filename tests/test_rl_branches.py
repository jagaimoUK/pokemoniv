"""Check native branch integrity, public policy inputs and censored pairing."""
import json
from collections import Counter
import unittest
from unittest.mock import patch

from pvpoke_rl_step_client import NativeStepError
from pvpoke_rl_team_env import InvalidNativeTeamResult, SixToThreeEnvironment
from tools import evaluate_rl_branches as branches


class _RecordingEnvironment(SixToThreeEnvironment):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.actions = []
        self.rosters = []

    def reset(self, **kwargs):
        self.actions.append([])
        view, info = super().reset(**kwargs)
        self.rosters.append(tuple(row["species"] for row in view["own_six"]))
        return view, info

    def step(self, action):
        self.actions[-1].append(action)
        return super().step(action)


class BranchReplayTests(unittest.TestCase):
    def test_native_prefix_control_and_public_policy(self):
        policy = branches.fixed_public_action

        def public_only(view):
            self.assertEqual(set(view), {
                "schema", "phase", "ruleset_id", "turn", "elapsed_ms", "own",
                "opponent", "legal_actions", "recent_events",
            })
            self.assertEqual(set(view["opponent"]), {"active_species", "shields", "revealed"})
            for member in view["opponent"]["revealed"]:
                self.assertEqual(set(member), {"species", "fainted", "hp_bucket_5pct", "seen_moves"})
            return policy(view)

        cases = [(branches.DEFAULT_ROSTER, pair) for pair in branches.PAIRS]
        cases += [("skarmory", "switch"), ("primeape", "charge")]
        for roster, pair in cases:
            envs = []

            def make_recording(*args, **kwargs):
                env = _RecordingEnvironment(*args, **kwargs)
                envs.append(env)
                return env

            with (self.subTest(roster=roster, pair=pair),
                  patch.object(branches, "SixToThreeEnvironment",
                               side_effect=make_recording),
                  patch.object(branches, "fixed_public_action", side_effect=public_only)):
                result = branches.compare_branches(roster=roster, pair=pair, seed=12, scenarios=1)
                selection, primeape_slot = branches.ROSTERS[roster]
                self.assertEqual(envs[0].rosters, [envs[0].rosters[0]] * 3)
                if primeape_slot is None:
                    self.assertNotIn("primeape", envs[0].rosters[0])
                else:
                    self.assertEqual(envs[0].rosters[0][primeape_slot], "primeape")
                reference, control, alternative = envs[0].actions
                self.assertEqual(reference[0], selection)
                self.assertEqual(reference, control)
                index = next(i for i, (a, b) in enumerate(zip(reference, alternative)) if a != b)
                self.assertGreater(index, 1)  # Selection and at least one tactical action.
                self.assertEqual((reference[index], alternative[index]), branches.PAIRS[pair][1:])
                self.assertEqual(result["fork_state_matches"], 2)
                self.assertEqual(result["same_action_replay_matches"], 1)
                self.assertEqual(result["attempted_pairs"], 1)
                self.assertEqual(result["roster"], roster)
                self.assertEqual(result["excluded_before_pair"], {})
                self.assertEqual(result["post_fork_divergence"]["audited_pairs"], 1)
                serialized = json.dumps(result)
                for private_key in ("opponent_team", "handoff", "starting_shields", "randomness",
                                    "combatant_id", "decisions", "game_data_sha256"):
                    self.assertNotIn(f'"{private_key}"', serialized)

    def test_private_prefix_mismatch_discards_publicly_identical_frontier(self):
        for field in ("opponent_action", "rng", "malformed"):
            with self.subTest(field=field):
                class AlteredAudit(_RecordingEnvironment):
                    def private_replay(self):
                        audit = super().private_replay()
                        if len(self.actions) == 2:
                            battle = audit["battle"]
                            if field == "opponent_action":
                                actions = battle["decisions"][0]["actions"]
                                actions[1] = "wait" if actions[1] == "fast" else "fast"
                            elif field == "rng":
                                battle["randomness"][0]["roll"] = -1
                            else:
                                del battle["decisions"]
                        return audit

                with patch.object(branches, "SixToThreeEnvironment", AlteredAudit):
                    result = branches.compare_branches(seed=12, scenarios=1)
                reason = "invalid_native_result" if field == "malformed" else "fork_state_mismatch"
                self.assertEqual(result["excluded_before_pair"], {reason: 1})
                self.assertEqual(result["candidate_frontiers"], 1)
                self.assertEqual(result["fork_state_matches"], 0)
                self.assertEqual(result["attempted_pairs"], 0)

    def test_same_action_control_audits_terminal_clock(self):
        class AlteredClock(_RecordingEnvironment):
            def step(self, action):
                view, reward, terminated, truncated, info = super().step(action)
                if len(self.actions) == 2 and (terminated or truncated):
                    info = {**info, "elapsed_ms": info["elapsed_ms"] + 500}
                return view, reward, terminated, truncated, info

        with patch.object(branches, "SixToThreeEnvironment", AlteredClock):
            result = branches.compare_branches(seed=12, scenarios=1)
        self.assertEqual(result["excluded_before_pair"], {"same_action_replay_mismatch": 1})
        self.assertEqual(result["fork_state_matches"], 1)
        self.assertEqual(result["same_action_replay_matches"], 0)
        self.assertEqual(result["attempted_pairs"], 0)

    def test_empty_native_tape_cannot_certify_a_nonempty_prefix(self):
        class MissingHistory(_RecordingEnvironment):
            def private_replay(self):
                audit = super().private_replay()
                audit["battle"]["decisions"] = []
                return audit

        with patch.object(branches, "SixToThreeEnvironment", MissingHistory):
            result = branches.compare_branches(seed=12, scenarios=1)
        self.assertEqual(result["excluded_before_pair"], {"invalid_native_result": 1})
        self.assertEqual(result["attempted_pairs"], 0)

    def test_candidate_errors_are_censored_without_leaking_exception_text(self):
        run = branches._roll_out
        for error, reason in ((NativeStepError, "worker_failure"),
                              (InvalidNativeTeamResult, "invalid_native_result")):
            def fail_candidate(env, action, budget, prefix_audit):
                if action == "shield_no":
                    raise error("private sentinel")
                return run(env, action, budget, prefix_audit)

            with (self.subTest(reason=reason),
                  patch.object(branches, "_roll_out", side_effect=fail_candidate)):
                result = branches.compare_branches(seed=12, scenarios=1)
                self.assertEqual(result["attempted_pairs"], 1)
                self.assertEqual(result["baseline_only_completed"], 1)
                self.assertEqual(result["both_completed"], 0)
                self.assertEqual(result["arms"]["candidate"]["censored"], {reason: 1})
                self.assertEqual(result["arms"]["candidate"]["losses"], 0)
                self.assertEqual(result["both_completed_rate"], 0)
                self.assertIsNone(result["paired_reward_delta_mean"])
                self.assertNotIn("private sentinel", json.dumps(result))

    def test_native_timeout_before_frontier_is_not_a_pair(self):
        result = branches.compare_branches(seed=12, scenarios=1, horizon=1)
        self.assertEqual(result["excluded_before_pair"], {"timeout": 1})
        self.assertEqual(result["candidate_frontiers"], 0)
        self.assertEqual(result["attempted_pairs"], 0)
        self.assertIsNone(result["both_completed_rate"])
        self.assertIsNone(result["paired_reward_delta_mean"])

    def test_charge_pair_requires_both_moves_at_the_same_frontier(self):
        result = branches.compare_branches(roster="skarmory", pair="charge", seed=12, scenarios=1)
        self.assertEqual(result["attempted_pairs"], 0)
        self.assertEqual(result["candidate_frontiers"], 0)
        self.assertEqual(sum(result["excluded_before_pair"].values()), 1)
        self.assertNotIn("worker_failure", result["excluded_before_pair"])
        self.assertNotIn("invalid_native_result", result["excluded_before_pair"])

    def test_terminal_labels_require_verified_ko_and_preserve_draws(self):
        good = {"training_eligible": True, "outcome": "simultaneous_ko", "selection_reward": 0}
        self.assertEqual(branches._verdict((None, 0, True, False, good)), (0, None))
        self.assertEqual(branches._verdict((None, 0, True, False, {**good, "selection_reward": False})),
                         (None, "invalid_outcome"))
        for outcome in ("timeout", "unsupported"):
            info = {"training_eligible": False, "outcome": outcome}
            self.assertEqual(branches._verdict((None, None, False, True, info)), (None, outcome))
        self.assertEqual(branches._verdict(({}, None, False, False, {})), (None, "decision_limit"))

    def test_pair_buckets_are_disjoint_and_only_verified_pairs_are_ranked(self):
        metrics = Counter()
        arms = {name: {"wins": 0, "losses": 0, "draws": 0, "censored": Counter()}
                for name in ("baseline", "candidate")}
        win, draw, loss, timeout = (1, None), (0, None), (-1, None), (None, "timeout")
        for baseline, candidate in (
            (win, loss), (draw, draw), (loss, draw), (win, timeout),
            (timeout, loss), (timeout, timeout),
        ):
            branches._record_pair(metrics, arms, baseline, candidate)
        self.assertEqual(metrics, {"both_completed": 3, "better": 1, "equal": 1, "worse": 1,
                                   "paired_reward_delta_sum": -1,
                                   "baseline_only_completed": 1, "candidate_only_completed": 1,
                                   "both_censored": 1})
        self.assertEqual(arms["baseline"], {"wins": 2, "losses": 1, "draws": 1,
                                            "censored": {"timeout": 2}})
        self.assertEqual(arms["candidate"], {"wins": 0, "losses": 2, "draws": 2,
                                             "censored": {"timeout": 2}})
