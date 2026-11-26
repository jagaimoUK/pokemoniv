import unittest

from pvpoke_observed_observation import Context
from pvpoke_observed_search import Search
from pvpoke_observed_roles import compare, normalize_roles


class ObservedRoleTests(unittest.TestCase):
    def setUp(self):
        self.roles = normalize_roles([
            {"id": "keep_shield", "priority": 2, "outcomes": ["self_ko_win"],
             "minimum": {"hp": 1, "shields": 1}},
            {"id": "keep_energy", "priority": 1, "outcomes": ["timeout"],
             "minimum": {"energy": 30}},
        ])
        self.search = Search(Context("a" * 64, (35, 55), 0, (1, 1)), ["a", "b"], self.roles)

    def evaluate(self, *cells):
        return self.search.evaluate({"cells": list(cells), "table": {}})

    def test_counterexample_and_unknown_are_separate(self):
        result = self.evaluate({"outcome": "self_ko_win", "terminal": [[1, 50, 0], [0, 0, 0]]})
        self.assertIs(result["roles"][0]["meets"], False)
        self.assertIsNone(result["roles"][0]["worst_outcome"])
        self.assertIs(result["roles"][1]["meets"], False)
        self.assertEqual(result["roles"][0]["unknown"], 1)

    def test_explicit_timeout_and_resource_tradeoff(self):
        def timeout(hp, energy):
            return {"outcome": "timeout", "terminal": [[hp, energy, 0], [1, 0, 0]]}
        left = self.evaluate(timeout(5, 30), timeout(5, 30))
        right = self.evaluate(timeout(3, 35), timeout(3, 35))
        self.assertIs(left["roles"][1]["meets"], True)
        self.assertEqual(compare(left, right), "incomparable")
        self.assertEqual(compare(left, self.evaluate(timeout(3, 30), timeout(3, 30))), "better")
        self.assertEqual(compare(left, self.evaluate(timeout(3, 30))), "incomparable")

    def test_rejects_invalid_conditions_and_prefers_high_priority(self):
        for field, value in (("priority", True), ("minimum", {"shields": 3}),
                             ("outcomes", ["self_ko_win", "self_ko_win"])):
            with self.subTest(field=field), self.assertRaises(ValueError):
                normalize_roles([{**self.roles[0], field: value}])
        win = {"outcome": "self_ko_win", "terminal": [[1, 0, 1], [0, 0, 0]]}
        time = {"outcome": "timeout", "terminal": [[100, 100, 2], [1, 0, 0]]}
        self.assertEqual(compare(self.evaluate(win, win), self.evaluate(time, time)), "better")
