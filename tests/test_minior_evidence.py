"""Minior evidence must be internally consistent before being used in selection."""
import unittest

from pvpoke_direct_backend import DirectMatrixError, validate_minior_strategies


def payload(policies=None):
    return {
        "result": {
            "minior_policy_model": "experimental-max-per-matchup-v1",
            "candidates": [{
                "ratings": [520, 600],
                "policies": policies or ["hold", "adaptive"],
                "strategy_ratings": {
                    "instant": [500, 550],
                    "hold": [520, 570],
                    "adaptive": [510, 600],
                },
            }],
        }
    }


class TestMiniorEvidence(unittest.TestCase):
    def test_complete(self):
        self.assertEqual(len(validate_minior_strategies(payload(), 1, 2)), 1)

    def test_reject_missing(self):
        bad = payload()
        del bad["result"]["candidates"][0]["strategy_ratings"]["hold"]
        with self.assertRaises(DirectMatrixError):
            validate_minior_strategies(bad, 1, 2)

    def test_reject_inconsistent_best(self):
        with self.assertRaises(DirectMatrixError):
            validate_minior_strategies(payload(["instant", "adaptive"]), 1, 2)

    def test_legacy_untouched(self):
        self.assertIsNone(validate_minior_strategies({"result": {}}, 1, 2))


if __name__ == "__main__":
    unittest.main()
