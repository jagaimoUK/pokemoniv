"""Pinned native PvPoke fixture: one visible opening proposal must execute.

This is NOT an observation-conditioned live-policy integration. There is no
native hook to re-evaluate at later turns, shield reveals or CMP decisions.
"""
from pathlib import Path
import tempfile
import unittest

from pvpoke_battle_service import BattleService
from pvpoke_battle_store import BattleStore
from pvpoke_direct_backend import DirectMatrixClient
from pvpoke_observed_policy import propose
from pvpoke_sandbox import SandboxService
from test_battle_service import FIXTURES
from test_sandbox import scripted_spec


class NativeObservedProposalTests(unittest.TestCase):
    def test_bounded_opening_proposal_executes_with_distinct_hidden_opponent_energy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = BattleStore(root / "battle_analysis.sqlite3")
            client = DirectMatrixClient(
                gamemaster=FIXTURES / "strategy_gamemaster.json", log_dir=root)
            try:
                native = SandboxService(BattleService(client, store=store))
                visible = {
                    "turn": 1, "phase": "choose_action", "own_energy": 100,
                    "own_shields": 0, "opponent_shields_visible": 1,
                    "own_can_act": True, "events": [],
                }
                fixed = {
                    "own_charged_moves": [
                        {"move_id": "AQUA_TAIL", "energy_cost": 35},
                        {"move_id": "STONE_EDGE", "energy_cost": 55},
                    ],
                    "energy_reserve": 0, "shield_rule": "never",
                }
                choice = propose(visible, fixed)
                self.assertEqual(choice["action"],
                                 {"kind": "charged", "move_id": "AQUA_TAIL"})
                for enemy_energy, enemy_ivs in (
                    (0, {"attack": 0, "defense": 0, "hp": 0}),
                    (100, {"attack": 15, "defense": 15, "hp": 15}),
                ):
                    with self.subTest(hidden_energy=enemy_energy, hidden_ivs=enemy_ivs):
                        # The proposal is identical across hidden worlds.
                        self.assertEqual(propose(visible, fixed), choice)
                        spec = scripted_spec(energy=100, shield=1)
                        spec["actions"] = [{
                            "id": "visible-proposal", "actor": 0, "turn": 1,
                            "kind": "charged", "move_id": choice["action"]["move_id"]
                        }]
                        spec["shield_decisions"] = []
                        spec["combatants"][1]["initial"]["energy"] = enemy_energy
                        spec["combatants"][1]["ivs"] = enemy_ivs
                        result = native.simulate(spec)
                        self.assertEqual(result["status"], "complete", result.get("error"))
                        executed = result["summary"]["action_results"]
                        self.assertEqual(executed[0]["status"], "executed")
                        self.assertTrue(any(
                            event.get("action_id") == "visible-proposal" and
                            event["kind"] == "charged" and event["move_id"] == "AQUA_TAIL"
                            for event in result["summary"]["executed_moves"]))
                self.assertFalse(choice["native_execution_verified"])
                self.assertEqual(choice["live_reproducibility"], "not_verified")
            finally:
                client.close()


if __name__ == "__main__":
    unittest.main()
