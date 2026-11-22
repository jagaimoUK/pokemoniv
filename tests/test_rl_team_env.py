"""Exercise the Python selection, worker and native 3v3 end to end."""
import unittest

from pvpoke_rl_step_client import NativeStepError
from pvpoke_rl_team_env import SixToThreeEnvironment, ThreeVThreeEnvironment
from pvpoke_rl_team_preview import SixToThreeSelection
from test_battle_service import FIXTURES, ROWS

GAME_DATA = FIXTURES / "strategy_gamemaster.json"


def rosters(hidden=(2, 3, 5), lead=2):
    def six(side):
        return [{**row, "combatant_id": f"{side}{i}", "roster_clause_id": row["species"]}
                for i, row in enumerate(ROWS)]
    own, enemy = six("own"), six("enemy")
    public = [{key: row[key] for key in ("species", "roster_clause_id")} for row in enemy]
    return own, public, enemy, hidden, lead


def make_env(*args):
    return SixToThreeEnvironment(GAME_DATA, *rosters(*args), ruleset_id="great-league-v1")


def action_for(observation):
    actions = observation["legal_actions"]
    for action in ("shield_yes", "charge_1", "charge_0", "fast"):
        if action in actions:
            return action
    return actions[0]


class NativeTeamEnvironmentTests(unittest.TestCase):
    def test_selection_to_ko_reward_and_deterministic_worker_reuse(self):
        with make_env() as env:
            def rollout():
                view, info = env.reset(seed=12)
                self.assertFalse(info["training_eligible"])
                self.assertEqual(len(env.legal_actions()), 60)
                self.assertEqual(view["phase"], "select_three")
                view["legal_actions"].clear()
                self.assertEqual(len(env.legal_actions()), 60)
                with self.assertRaises(ValueError):
                    env.step("0,1,2|3")
                view, reward, term, trunc, info = env.step("0,1,4|4")
                self.assertEqual(view["own"]["team"][0]["combatant_id"], "own4")
                self.assertEqual(view["opponent"]["active_species"], ROWS[2]["species"])
                self.assertIsNone(reward)
                self.assertFalse(term or trunc or info["training_eligible"])
                self.assertNotIn("selection_reward", info)
                for step in range(550):
                    view, reward, term, trunc, info = env.step(action_for(view))
                    if term or trunc:
                        break
                    self.assertIsNone(reward)
                    self.assertNotIn("selection_reward", info)
                    self.assertEqual(tuple(view["legal_actions"]), env.legal_actions())
                self.assertTrue(term, (step, info))
                self.assertFalse(trunc)
                self.assertIsNone(view)
                self.assertTrue(info["training_eligible"])
                self.assertEqual(reward, info["selection_reward"])
                self.assertIn(reward, (-1, 0, 1))
                self.assertEqual(env.legal_actions(), ())
                with self.assertRaises(NativeStepError):
                    env.step("wait")
                replay = env.private_replay()
                self.assertEqual(replay["selection"], "0,1,4|4")
                self.assertEqual(replay["battle"]["result"]["reward"], reward)
                return replay
            first = rollout()
            pid = env._battle._proc.pid
            self.assertEqual(rollout(), first)
            self.assertEqual(env._battle._proc.pid, pid)

    def test_hidden_opponent_roster_never_in_selection_or_initial_battle_view(self):
        with make_env() as first, make_env((0, 1, 2), 2) as second:
            self.assertEqual(first.reset(), second.reset())
            self.assertNotIn("opponent_team", first.observe())
            self.assertEqual(first.step("0,1,4|1"), second.step("0,1,4|1"))
            first_history = first.private_replay()["battle"]
            second_history = second.private_replay()["battle"]
            self.assertNotEqual(first_history["handoff"]["opponent_team"],
                                second_history["handoff"]["opponent_team"])

    def test_horizon_cannot_supply_tactics_or_selection_rewards(self):
        with make_env() as env:
            env.reset(horizon=1)
            env.step("0,1,4|0")
            view, reward, term, trunc, info = env.step("wait")
            self.assertIsNone(view)
            self.assertIsNone(reward)
            self.assertFalse(term)
            self.assertTrue(trunc)
            self.assertFalse(info["training_eligible"])
            self.assertEqual(info["outcome"], "timeout")
            self.assertNotIn("selection_reward", info)
            env.reset()
            with self.assertRaises(NativeStepError):
                env.private_replay()

    def test_direct_handoff_validation_and_reset(self):
        selection = SixToThreeSelection(*rosters(), ruleset_id="great-league-v1")
        selection.choose("0,1,4|0")
        handoff = selection._private_engine_input()
        with ThreeVThreeEnvironment(GAME_DATA) as env:
            with self.assertRaises(ValueError):
                env.reset(handoff, seed=True)
            view, _ = env.reset(handoff)
            with self.assertRaises(ValueError):
                env.step("shield_yes")
            self.assertEqual(env.observe(), view)
            bad = selection._private_engine_input()
            bad["opponent_team"][1]["charged1"] = "AQUA_TAIL"
            # Malformed private fixtures are infrastructure errors, never wins.
            with self.assertRaises(NativeStepError):
                env.reset(bad)
            self.assertIsNone(env.observe())
            self.assertEqual(env.reset(handoff)[0], view)
