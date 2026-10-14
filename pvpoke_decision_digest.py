"""Lossless table encoding for GPT's candidate-level decision evidence.

Every candidate, signal, selected example and crossover highlight survives.
Only repeated field names and explanatory boilerplate are removed.
This encoding never selects or grades candidates.
"""
from __future__ import annotations

EVIDENCE_COLUMNS = (
    "ivs", "dominated", "unique_gt500", "unique_gt500_focus",
    "unique_gt500_disadvantage", "clear_leads", "clear_leads_focus",
    "clear_leads_disadvantage", "strict_leads", "examples_total",
    "examples_truncated",
)
EXAMPLE_COLUMNS = (
    "opponent", "shield", "rating", "next_best", "lead",
    "unique_gt500", "focus",
)
CROSSOVER_COLUMNS = (
    "shield", "opponent", "focus", "above500_ivs", "best", "second", "worst",
)


def decision_digest(digest: dict) -> dict:
    """Keep verification, all-candidate evidence, ranking and focus ratings."""
    redundant = {
        "candidate_evidence", "priority_crossovers", "note",
    }
    out = {key: value for key, value in digest.items() if key not in redundant}
    out["format"] = "decision-v1"
    out["evidence_columns"] = list(EVIDENCE_COLUMNS)
    out["evidence_rows"] = [
        [item[key] for key in EVIDENCE_COLUMNS]
        for item in digest["candidate_evidence"]
    ]
    out["example_columns"] = list(EXAMPLE_COLUMNS)
    out["crossover_columns"] = list(CROSSOVER_COLUMNS)
    out["crossover_rows"] = [
        [event[key] for key in CROSSOVER_COLUMNS]
        for event in digest["priority_crossovers"]
    ]
    out["examples_by_iv"] = {
        item["ivs"]: [[event[key] for key in EXAMPLE_COLUMNS]
                      for event in item["examples"]]
        for item in digest["candidate_evidence"] if item["examples"]
    }
    out["focus_candidate_scope"] = "selective; evidence_rows covers every candidate"
    return out
