"""Minimal local JSON-lines/Python integration for native 1v1 stepping."""
import unittest

import test_observed_native_runner as fixtures
from pvpoke_rl_step_client import NativeStepClient, NativeStepError


class NativeStepClientTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.NativeObservedMultiTurnTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture

    def client(self):
        return NativeStepClient(self.fixture.client.source, timeout=10)

    def test_reset_and_steps_preserve_public_view_and_episode_boundary(self):
        request = self.fixture.request(energy=0, enemy_energy=100, shields=(0, 0))
        with self.client() as client:
            first, info = client.reset(request, horizon=4)
            self.assertEqual(first["turn"], 1)
            self.assertNotIn("energy", first["opponent"])
            self.assertNotIn("charged", first["opponent"])
            self.assertFalse(first["capabilities"]["manual_shield"])
            self.assertEqual(info["information_fairness"], "not_established")
            observed = []
            for _ in range(4):
                view, reward, ended, truncated, details = client.step(
                    "fast" if "fast" in first["legal_actions"] else "wait")
                observed.append((view, reward, ended, truncated))
                if ended or truncated:
                    break
                first = view
            self.assertTrue(ended or truncated)
            self.assertIsNone(view)
            self.assertGreaterEqual(len(observed), 1)
            self.assertLessEqual(len(observed), 4)
            self.assertEqual(client.stats()["peak_rss_kib"] > 0, True)
            with self.assertRaises(NativeStepError):
                client.step("fast")
            again, _ = client.reset(request, horizon=4)
            self.assertEqual(again["turn"], 1)

    def test_illegal_action_is_rejected_without_advancing_native_battle(self):
        request = self.fixture.request(energy=0, shields=(0, 0))
        with self.client() as client:
            first, _ = client.reset(request, horizon=4)
            with self.assertRaises(ValueError):
                client.step("charge_1")
            self.assertEqual(first["turn"], 1)
            view, _, _, _, _ = client.step("fast")
            self.assertEqual(view["turn"], 2)

    def test_two_resets_follow_same_deterministic_first_steps(self):
        request = self.fixture.request(energy=0, shields=(0, 0))
        with self.client() as client:
            histories = []
            for _ in range(2):
                view, _ = client.reset(request, horizon=4)
                series = [view]
                for step in range(2):
                    view, reward, ended, truncated, _ = client.step(
                        "fast" if "fast" in view["legal_actions"] else "wait")
                    series.append((view, reward, ended, truncated))
                    if ended or truncated:
                        break
                histories.append(series)
            self.assertEqual(histories[0], histories[1])


if __name__ == "__main__":
    unittest.main()
