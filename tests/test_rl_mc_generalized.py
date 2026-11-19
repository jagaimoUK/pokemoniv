"""Opt-in v2 public-state generalization: privacy, semantics and compatibility."""
import copy
import json
import unittest

from pvpoke_rl_mc_train import PublicMonteCarloPolicy, LearningError, public_state, play_episode
from pvpoke_rl_mc_generalized import (
    GeneralizedMonteCarloPolicy, VERSION, coarse_public_state,
)
from pvpoke_rl_team_env import SixToThreeEnvironment
from test_rl_team_env import GAME_DATA, rosters
from test_rl_mc_train import preview, public_tactics


class GeneralizedMCPolicyTests(unittest.TestCase):
    def test_nearby_public_resource_values_share_coarse_key_not_exact_key(self):
        a = public_tactics()
        a["opponent"]["revealed"][0]["hp_bucket_5pct"] = 18
        b = copy.deepcopy(a)
        b["own"]["team"][0]["hp"] = 99
        b["own"]["team"][0]["energy_points"] = 4
        b["opponent"]["revealed"][0]["hp_bucket_5pct"] = 17
        self.assertNotEqual(public_state(a)[1], public_state(b)[1])
        self.assertEqual(coarse_public_state(a), coarse_public_state(b))

    def test_important_public_rules_change_key(self):
        a = public_tactics()
        a["legal_actions"] = ["wait", "fast", "switch_1"]
        b = copy.deepcopy(a)
        b["own"]["team"][1]["species"] = "new_bench_species"
        self.assertNotEqual(coarse_public_state(a)[1], coarse_public_state(b)[1])
        b = copy.deepcopy(a)
        b["own"]["shields"] = 0
        self.assertNotEqual(coarse_public_state(a)[1], coarse_public_state(b)[1])
        b = copy.deepcopy(a)
        b["own"]["team"][0]["charged_moves"][0]["move_id"] = "CHANGED_MOVE"
        self.assertNotEqual(coarse_public_state(a)[1], coarse_public_state(b)[1])
        b = copy.deepcopy(a)
        b["legal_actions"] = ["wait", "switch_1"]
        self.assertNotEqual(coarse_public_state(a)[1], coarse_public_state(b)[1])
        b = copy.deepcopy(a)
        b["opponent"]["revealed"][0]["seen_moves"] = ["PUBLIC_CHARGED"]
        self.assertNotEqual(coarse_public_state(a)[1], coarse_public_state(b)[1])

    def test_hidden_fields_never_affect_state(self):
        a = public_tactics()
        b = copy.deepcopy(a)
        b["private_replay"] = {"opponent_team": ["secret"]}
        b["opponent"]["unseen_ivs"] = [15, 15, 15]
        b["opponent"]["unselected_bench"] = ["hidden"]
        self.assertEqual(coarse_public_state(a), coarse_public_state(b))

    def test_selection_state_keeps_public_six_but_not_hidden_opponent(self):
        a = preview(hidden=(0, 1, 2), lead=0)
        b = preview(hidden=(3, 4, 5), lead=5)
        self.assertEqual(coarse_public_state(a), coarse_public_state(b))
        self.assertEqual(coarse_public_state(a)[0], "selection")
        b["opponent_public_six"][0]["species"] = "public_other"
        self.assertNotEqual(coarse_public_state(a)[1], coarse_public_state(b)[1])

    def test_missing_active_opponent_is_rejected_not_guessed(self):
        a = public_tactics()
        a["opponent"]["revealed"].clear()
        with self.assertRaises(LearningError):
            coarse_public_state(a)

    def test_v1_checkpoints_are_not_silently_loaded_as_v2_and_vice_versa(self):
        old = PublicMonteCarloPolicy(seed=11).snapshot()
        new = GeneralizedMonteCarloPolicy(seed=11).snapshot()
        self.assertNotEqual(old["schema"], new["schema"])
        self.assertEqual(new["schema"], VERSION)
        with self.assertRaises(LearningError):
            GeneralizedMonteCarloPolicy.restore(old)
        with self.assertRaises(LearningError):
            PublicMonteCarloPolicy.restore(new)
        roundtrip = GeneralizedMonteCarloPolicy.restore(
            json.loads(json.dumps(new)), seed=11)
        self.assertEqual(roundtrip.snapshot(), new)

    def test_public_reward_updates_v2_action_preference(self):
        policy = GeneralizedMonteCarloPolicy(seed=9)
        kind, key, _ = coarse_public_state(preview())
        tactic, tkey, _ = coarse_public_state(public_tactics())
        self.assertEqual(kind, "selection")
        self.assertEqual(tactic, "tactics")
        policy.learn([("selection", key, "0,1,2|0"),
                      ("tactics", tkey, "fast")],
                     reward=1, selection_reward=1)
        policy.learn([("selection", key, "0,1,3|0"),
                      ("tactics", tkey, "wait")],
                     reward=-1, selection_reward=-1)
        self.assertEqual(policy.choose(preview(), epsilon=0)[0], "0,1,2|0")
        self.assertEqual(policy.choose(public_tactics(), epsilon=0)[0], "fast")
        restored = GeneralizedMonteCarloPolicy.restore(
            json.loads(json.dumps(policy.snapshot())), seed=9)
        self.assertEqual(restored.snapshot(), policy.snapshot())

    def test_real_native_3v3_episode_works_with_v2(self):
        policy = GeneralizedMonteCarloPolicy(seed=12)
        with SixToThreeEnvironment(GAME_DATA, *rosters(),
                                   ruleset_id="great-league-v1") as env:
            record = play_episode(env, policy, seed=12, epsilon=0.0)
        self.assertIn(record["status"], ("complete", "discarded"))
        self.assertEqual(policy.completed_matches,
                         1 if record["status"] == "complete" else 0)


if __name__ == "__main__":
    unittest.main()
