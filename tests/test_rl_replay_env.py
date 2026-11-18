"""Bounded native integration and input-boundary tests for the RL replay spike."""
import unittest

import test_observed_native_runner as fixtures
from pvpoke_observed_observation import Context, digest
from pvpoke_rl_replay_env import ReplayStepEnv, ReplayStepError


class ReplayStepEnvTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.NativeObservedMultiTurnTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture

    def environment(self, *, energy=35, enemy_energy=0, horizon=4, runner=None):
        request = self.fixture.request(
            energy=energy, enemy_energy=enemy_energy,
            opponent_attack_rule="charge_if_ready")
        context = Context(
            digest(request["self"]),
            tuple(m["energy_cost"] for m in request["policy"]["own_charged_moves"]),
            energy, tuple(request["shields"]), 8, request["opponent"]["species"])
        return ReplayStepEnv(
            request, context, runner or self.fixture.native, horizon=horizon, seed=3)

    def test_reset_returns_only_public_information(self):
        first = self.environment(enemy_energy=0)
        second = self.environment(enemy_energy=100)
        obs_a, info = first.reset()
        obs_b, _ = second.reset()
        self.assertEqual(obs_a, obs_b)
        self.assertEqual(obs_a["phase"], "window")
        self.assertEqual(obs_a["own_energy"], 35)
        self.assertIn("charge_0", obs_a["legal_actions"])
        self.assertNotIn("charge_1", obs_a["legal_actions"])
        self.assertNotIn("opponent_energy", obs_a)
        self.assertNotIn("opponent", str(obs_a))
        self.assertEqual(info["information_fairness"], "not_established")
        with self.assertRaises(ValueError):
            first.step("charge_1")

    def test_native_step_and_replay_reset_are_deterministic(self):
        env = self.environment()
        opening, _ = env.reset()
        next_obs, reward, terminated, truncated, info = env.step("wait_one_window")
        self.assertEqual(reward, 0.0)
        self.assertFalse(terminated)
        self.assertFalse(truncated)
        self.assertIsNotNone(next_obs)
        self.assertNotEqual(next_obs["history_key"], opening["history_key"])
        self.assertEqual(info["live_reproducibility"], "not_verified")
        env.reset()
        again, reward, terminated, truncated, _ = env.step("wait_one_window")
        self.assertEqual(next_obs, again)
        self.assertEqual((reward, terminated, truncated), (0.0, False, False))

    def test_horizon_is_truncation_not_a_win(self):
        env = self.environment(horizon=1)
        env.reset()
        obs, reward, terminated, truncated, info = env.step("wait_one_window")
        self.assertIsNone(obs)
        self.assertEqual(reward, 0.0)
        self.assertFalse(terminated)
        self.assertTrue(truncated)
        self.assertEqual(info["reason"], "horizon")
        with self.assertRaises(ReplayStepError):
            env.step("fast")

    def test_runner_unknown_is_not_treated_as_loss(self):
        env = self.environment()
        env.reset()
        env._runner = lambda request: {
            "schema": "observed-native-v2", "status": "unknown",
            "reason": "unsupported_uncertainty"}
        obs, reward, terminated, truncated, info = env.step("fast")
        self.assertIsNone(obs)
        self.assertEqual(reward, 0.0)
        self.assertFalse(terminated)
        self.assertTrue(truncated)
        self.assertEqual(info["reason"], "unsupported_uncertainty")

    def test_replay_divergence_fails_closed(self):
        env = self.environment()
        first, _ = env.reset()
        original_runner = env._runner

        def stale_result(request):
            request["observed_v2"]["table"] = {}
            return original_runner(request)

        env._runner = stale_result
        with self.assertRaisesRegex(ReplayStepError, "commit"):
            env.step("fast")
        self.assertFalse(env._done)
        self.assertEqual(env._table, {})
        self.assertEqual(env._view.key, first["history_key"])

    def test_context_mismatch_or_invalid_seed_is_rejected(self):
        request = self.fixture.request(energy=35)
        context = Context(digest(request["self"]), (35, 55), 34,
                          tuple(request["shields"]), 8,
                          request["opponent"]["species"])
        with self.assertRaisesRegex(ValueError, "does not match"):
            ReplayStepEnv(request, context, self.fixture.native)
        context = Context(digest(request["self"]), (35, 55), 35,
                          tuple(request["shields"]), 8,
                          request["opponent"]["species"])
        with self.assertRaises(ValueError):
            ReplayStepEnv(request, context, self.fixture.native, seed=True)


if __name__ == "__main__":
    unittest.main()
