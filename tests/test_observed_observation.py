import unittest

from pvpoke_observed_observation import Context, ObservationV2, history_key


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.context = Context("a" * 64, (35, 55), 0, (1, 2))
        self.window = {"seq": 1, "observed_time_range": [1, 1], "kind": "window"}

    def test_canonical_keys_and_strict_fields(self):
        first = ObservationV2.read(self.context, [self.window])
        self.assertEqual(first.key, history_key(self.context, [dict(reversed(list(self.window.items())))]))
        for event in ({**self.window, "world": 1}, {**self.window, "seq": True},
                      {**self.window, "observed_time_range": [2, 1]}):
            with self.assertRaises(ValueError):
                ObservationV2.read(self.context, [event])

    def test_shield_commit_precedes_reveal(self):
        prompt = {"seq": 1, "observed_time_range": [1, 1], "kind": "charge_announced"}
        reveal = {"seq": 2, "observed_time_range": [1, 1], "kind": "charge_revealed",
                  "move_id": "HYDRO_PUMP"}
        with self.assertRaises(ValueError):
            history_key(self.context, [prompt, reveal])
        choice = {"seq": 2, "observed_time_range": [1, 1], "kind": "intent",
                  "action": "shield_yes"}
        key = history_key(self.context, [prompt, choice, {**reveal, "seq": 3},
                                         {**self.window, "seq": 4}])
        self.assertEqual(len(key), 64)
