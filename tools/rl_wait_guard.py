"""Evaluation-only ablation: suppress unsupported voluntary idle decisions.

This is NOT a new trained model, a new ruleset or a production policy.
It reads the exact v2 public state key and v2 checkpoint, keeps training
unchanged, and alters only deterministic (epsilon=0) action selection.

A positive first-visit terminal-return mean is NOT evidence that a wait is
causally beneficial. This ablation tests a narrow failure hypothesis.
"""
from __future__ import annotations

from pvpoke_rl_mc_generalized import GeneralizedMonteCarloPolicy

ABLATION_NAME = "guard_unproven_voluntary_wait_v1"


class GuardedWaitMonteCarloPolicy(GeneralizedMonteCarloPolicy):
    """Do not greedily choose unproven wait when a fast/charge is legal.

    Forced wait remains legal; an observed positive wait retains eligibility.
    Exploration (epsilon>0) is untouched. Always preserve the ORIGINAL public
    state hash, even when filtering the candidate action list for a decision.
    Checkpoints remain bit-for-bit compatible with v2.
    """

    def _choose_encoded(self, encoded, *, epsilon):
        kind, key, legal = encoded
        if (epsilon == 0 and kind == "tactics" and "wait" in legal and
                any(a == "fast" or a.startswith("charge_") for a in legal)):
            observed_wait = self._values["tactics"].get(key, {}).get("wait")
            if observed_wait is None or observed_wait[1] <= 0:
                candidates = tuple(a for a in legal if a != "wait")
                return super()._choose_encoded(
                    (kind, key, candidates), epsilon=epsilon)
        return super()._choose_encoded(encoded, epsilon=epsilon)
