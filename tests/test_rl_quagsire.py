"""Verify isolated shadow mechanics, ruleset separation and paired fork accounting."""
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from pvpoke_child_env import child_environment
from tools.evaluate_rl_quagsire import (
    BASE_GAMEMASTER, ROOT, RULESET_IDS, WINDOWS, run_cases, shadow_gamemaster,
    summarize, summarize_forks, window_cases,
)
from tools.rl_tournament_rules import validate_team_for_ruleset


class QuagsireStudyTests(unittest.TestCase):
    def test_overlay_keeps_base_data_and_executes_shadow_attack_and_defense(self):
        original = BASE_GAMEMASTER.read_bytes()
        base = json.loads(original)
        extended = shadow_gamemaster()
        shadow = extended["pokemon"].pop()
        self.assertEqual(extended, base)
        self.assertEqual(shadow["speciesId"], "quagsire_shadow")
        self.assertEqual(shadow["tags"], ["shadow"])
        extended["pokemon"].append(shadow)

        handoff = next(
            row["handoff"] for row in window_cases(WINDOWS[0])
            if row["handoff"]["own_team"][0]["charged2"] == "STONE_EDGE"
        )
        with TemporaryDirectory() as temp:
            fixture = Path(temp) / "gamemaster.json"
            fixture.write_text(json.dumps(extended), encoding="utf-8")
            subprocess.run(
                ["node", str(ROOT / "tests/test_rl_quagsire.cjs"), str(fixture)],
                input=json.dumps(handoff), text=True, cwd=ROOT, check=True, timeout=30,
                env=child_environment({"PVP_PVPOKE_SOURCE": str(ROOT / "vendor/pvpoke")}),
            )
        self.assertEqual(BASE_GAMEMASTER.read_bytes(), original)

    def test_rulesets_keep_same_conditions_and_separate_eligibility(self):
        for window in WINDOWS:
            cases = window_cases(window)
            self.assertEqual(len(cases), 144)
            self.assertEqual({row["seed"] for row in cases}, set(range(window, window + 6)))
            worlds, later = cases[:72], cases[72:]
            for first, second in zip(worlds, later):
                self.assertEqual(first["handoff"]["ruleset_id"], RULESET_IDS[0])
                self.assertEqual(second["handoff"]["ruleset_id"], RULESET_IDS[1])
                self.assertEqual(second, {
                    **first, "handoff": {**first["handoff"], "ruleset_id": RULESET_IDS[1]},
                })
            lead = cases[0]["handoff"]["own_team"][0]
            normal_and_shadow = [lead, {**lead, "species": "quagsire_shadow"}]
            mimikyu = {**lead, "species": "mimikyu", "roster_clause_id": "mimikyu"}
            for ruleset in RULESET_IDS:
                with self.assertRaisesRegex(ValueError, "Duplicate species clause"):
                    validate_team_for_ruleset(normal_and_shadow, ruleset)
            with self.assertRaisesRegex(ValueError, "mimikyu is banned"):
                validate_team_for_ruleset([mimikyu], RULESET_IDS[0])
            validate_team_for_ruleset([mimikyu], RULESET_IDS[1])

    def test_native_forks_preserve_ruleset_label_and_public_output(self):
        cases = [
            {**row, "seed": 17} for row in window_cases(WINDOWS[0])
            if row["roster"] == "clodsire" and row["seed"] == WINDOWS[0]
            and row["opponent_shields"] == 1
        ]
        rows = run_cases(cases)
        self.assertEqual(len(rows), 8)
        for row in rows:
            self.assertEqual(row["public_state"]["opponent_shields"], 1)
            self.assertEqual(set(row["public_state"]),
                             {"turn", "hp_bucket_5pct", "opponent_shields", "elapsed_ms"})
            for arm, move in (("aqua_tail", "AQUA_TAIL"), ("second_charge", row["second_move"])):
                self.assertEqual(row[arm]["requested_move"], move)
                self.assertTrue(row[arm]["move_resolved"])
                self.assertTrue(row[arm]["shielded"])
        self.assertEqual(rows[4:], [{**row, "ruleset_id": RULESET_IDS[1]} for row in rows[:4]])
        for forbidden in ("handoff", "audit", "decisions", "randomness", "opponent_team"):
            self.assertNotIn(f'"{forbidden}"', json.dumps(rows))
        report = summarize(rows)
        self.assertEqual(set(report), set(RULESET_IDS))
        self.assertEqual(report[RULESET_IDS[0]], report[RULESET_IDS[1]])
        self.assertEqual(report[RULESET_IDS[0]]["worlds_builds_matched_inputs"]["planned"], 1)

    def test_summary_does_not_score_timeouts_or_unavailable_forks(self):
        won = {"reward": 1, "outcome": "self_ko_win", "move_resolved": True, "shielded": False}
        timeout = {"reward": None, "outcome": "timeout", "move_resolved": True, "shielded": True}
        result = summarize_forks([
            {"public_state": {}, "aqua_tail": won, "second_charge": timeout},
            {"public_state": {}, "aqua_tail": {**won, "reward": -1}, "second_charge": won},
            {"excluded": "target_fainted_before_fork"},
        ])
        self.assertEqual((result["planned"], result["attempted"], result["both_completed"]), (3, 2, 1))
        self.assertEqual(result["both_completed_rate"], 0.5)
        self.assertEqual(result["mean_reward_delta"], 2)
        self.assertEqual(result["alternative_censored"], {"timeout": 1})
        self.assertEqual(result["second_charge"], {"resolved": 2, "shielded": 1})
