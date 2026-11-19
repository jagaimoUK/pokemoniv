"""Fast public-only MC tests and a bounded native-3v3 integration smoke."""
import copy
import json
import unittest

from pvpoke_rl_mc_train import (
    PublicMonteCarloPolicy, LearningError, play_episode, public_state,
)
from pvpoke_rl_team_preview import SixToThreeSelection
from pvpoke_rl_team_env import SixToThreeEnvironment
from test_rl_team_env import GAME_DATA, rosters


def preview(hidden=(2, 3, 5), lead=2):
    return SixToThreeSelection(*rosters(hidden, lead),
                               ruleset_id="great-league-v1").observe()


def public_tactics():
    return {
        "schema": "rl-native-3v3-v1", "ruleset_id": "great-league-v1",
        "phase": "turn", "legal_actions": ["wait", "fast"],
        "own": {
            "active_slot": 0, "shields": 2, "switch_timer_ms": 0,
            "team": [
                {
                    "species": f"own{i}", "hp": 100, "max_hp": 120,
                    "energy_points": i * 10, "buffs": [0, 0],
                    "cooldown_ms": 0, "fast_move": "MUD_SHOT",
                    "charged_moves": [
                        {"move_id": "AQUA_TAIL", "energy_cost": 35},
                        {"move_id": "STONE_EDGE", "energy_cost": 55},
                    ],
                } for i in range(3)
            ],
        },
        "opponent": {
            "active_species": "enemy_active", "shields": 2,
            "revealed": [{"species": "enemy_active",
                          "hp_bucket_5pct": 20, "fainted": False,
                          "seen_moves": []}],
        },
    }


class FakeMatch:
    def __init__(self, *, final="win"):
        self.final = final
        self.phase = "unset"
        self.selection = None
        self.action = None

    def reset(self, *, seed=0):
        self.phase = "selection"
        return preview(), {"training_eligible": False}

    def step(self, action):
        if self.phase == "selection":
            self.selection = action
            self.phase = "tactic"
            return public_tactics(), None, False, False, {"training_eligible": False}
        if self.phase == "tactic":
            self.action = action
            self.phase = "ended"
            if self.final == "win":
                return None, 1, True, False, {
                    "training_eligible": True,
                    "selection_reward": 1, "outcome": "self_ko_win",
                }
            if self.final == "timeout":
                return None, None, False, True, {
                    "training_eligible": False, "outcome": "timeout",
                }
            if self.final == "poisoned":
                return None, 1, True, False, {
                    "training_eligible": False,
                    "selection_reward": 1, "outcome": "self_ko_win",
                }
        raise AssertionError("Unexpected fake environment phase")


class PublicMCTests(unittest.TestCase):
    def test_public_selection_state_cannot_see_hidden_three_or_private_ivs(self):
        own, pub, enemy, _, _ = rosters()
        base = SixToThreeSelection(
            own, pub, enemy, (0, 1, 2), 0, ruleset_id="great-league-v1")
        changed_enemy = copy.deepcopy(enemy)
        changed_enemy[0]["atk"] = 15
        other = SixToThreeSelection(
            own, pub, changed_enemy, (3, 4, 5), 5, ruleset_id="great-league-v1")
        self.assertEqual(public_state(base.observe()), public_state(other.observe()))
        first = PublicMonteCarloPolicy(seed=42)
        second = PublicMonteCarloPolicy(seed=42)
        self.assertEqual(first.choose(base.observe()), second.choose(other.observe()))

    def test_unrecognized_hidden_properties_are_not_in_a_tactical_state_key(self):
        original = public_tactics()
        modified = copy.deepcopy(original)
        modified["private_replay"] = {"opponent_team": ["secret"]}
        modified["opponent"]["unseen_ivs"] = [0, 15, 15]
        self.assertEqual(public_state(original), public_state(modified))
        self.assertEqual(PublicMonteCarloPolicy(seed=7).choose(original),
                         PublicMonteCarloPolicy(seed=7).choose(modified))

    def test_real_training_updates_selection_and_tactical_values(self):
        policy = PublicMonteCarloPolicy(seed=11)
        results = [play_episode(FakeMatch(), policy, seed=i, epsilon=0.0)
                   for i in range(3)]
        self.assertTrue(all(x["updated"] and x["reward"] == 1 for x in results))
        snapshot = policy.snapshot()
        self.assertEqual(snapshot["completed_matches"], 3)
        self.assertTrue(snapshot["values"]["selection"])
        self.assertTrue(snapshot["values"]["tactics"])
        self.assertNotIn("opponent_team", json.dumps(snapshot))
        restored = PublicMonteCarloPolicy.restore(json.loads(json.dumps(snapshot)), seed=11)
        self.assertEqual(restored.snapshot(), snapshot)

    def test_timeout_and_invalid_rewards_do_not_update_learning(self):
        policy = PublicMonteCarloPolicy(seed=3)
        for final in ("timeout", "poisoned"):
            result = play_episode(FakeMatch(final=final), policy, epsilon=0.0)
            self.assertEqual(result["status"], "discarded")
            self.assertIsNone(result["reward"])
            self.assertFalse(result["updated"])
        self.assertEqual(policy.completed_matches, 0)
        self.assertEqual(policy.snapshot()["values"], {"selection": {}, "tactics": {}})

    def test_legal_action_mask_and_state_phase(self):
        model = PublicMonteCarloPolicy(seed=0)
        tactic = public_tactics()
        for _ in range(100):
            action, record = model.choose(tactic, epsilon=1.0)
            self.assertIn(action, ("wait", "fast"))
            self.assertEqual(record[0], "tactics")
        with self.assertRaises(LearningError):
            model.choose({"schema": "rl-native-3v3-v1", "phase": "turn",
                          "legal_actions": ["invalid"]})
        with self.assertRaises(LearningError):
            model.choose({**tactic, "legal_actions": ["wait", "wait"]})

    def test_checkpoint_rejects_invalid_counts_values_and_schema(self):
        p = PublicMonteCarloPolicy(seed=1)
        play_episode(FakeMatch(), p, epsilon=0)
        snapshot = p.snapshot()
        bad = copy.deepcopy(snapshot)
        bad["values"]["tactics"][next(iter(bad["values"]["tactics"]))]["fast"] = [-1, 1.0]
        with self.assertRaises(LearningError):
            PublicMonteCarloPolicy.restore(bad)
        bad = copy.deepcopy(snapshot)
        bad["schema"] = "unknown"
        with self.assertRaises(LearningError):
            PublicMonteCarloPolicy.restore(bad)
        with self.assertRaises(LearningError):
            p.learn([], reward=1, selection_reward=1)
        with self.assertRaises(LearningError):
            p.learn([("selection", "a" * 64, "0,1,2|0")],
                    reward=1, selection_reward=-1)

    def test_policy_choice_and_update_are_seed_reproducible(self):
        first, second = PublicMonteCarloPolicy(seed=15), PublicMonteCarloPolicy(seed=15)
        sequence_one = [play_episode(FakeMatch(), first, seed=i, epsilon=.2)
                        for i in range(5)]
        sequence_two = [play_episode(FakeMatch(), second, seed=i, epsilon=.2)
                        for i in range(5)]
        self.assertEqual(sequence_one, sequence_two)
        self.assertEqual(first.snapshot(), second.snapshot())

    def test_native_3v3_one_episode_smoke_from_public_policy(self):
        with SixToThreeEnvironment(GAME_DATA, *rosters(),
                                   ruleset_id="great-league-v1") as env:
            policy = PublicMonteCarloPolicy(seed=12)
            result = play_episode(env, policy, seed=12, epsilon=0.0)
            self.assertIn(result["status"], ("complete", "discarded"))
            self.assertLessEqual(result["decisions"], 2000)
            if result["status"] == "complete":
                self.assertEqual(policy.completed_matches, 1)
                self.assertIn(result["reward"], (-1, 0, 1))
            else:
                self.assertEqual(policy.completed_matches, 0)
                self.assertIsNone(result["reward"])


if __name__ == "__main__":
    unittest.main()
