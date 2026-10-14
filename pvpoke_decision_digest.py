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


def _compact_numbers(value):
    """JSON has one number type; omit .0 without rounding any measured value."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return [_compact_numbers(item) for item in value]
    if isinstance(value, dict):
        return {key: _compact_numbers(item) for key, item in value.items()}
    return value


def decision_digest_v2(digest: dict) -> dict:
    """Intern repeated opponent labels and include ready-to-use downside facts.

    Indices are local to this report's opponents array and start at zero.
    All v1 numerical evidence and full opponent labels can be reconstructed.
    No recommendation cap, automatic grade, or matchup filter is added.
    """
    out = decision_digest(digest)
    out.pop("candidate_tradeoffs", None)
    out["format"] = "decision-v2"
    names, indices = [], {}

    def opponent_index(name):
        if name not in indices:
            indices[name] = len(names)
            names.append(name)
        return indices[name]

    out["example_columns"][0] = "opponent_index"
    for examples in out["examples_by_iv"].values():
        for row in examples:
            row[0] = opponent_index(row[0])
    out["crossover_columns"][1] = "opponent_index"
    candidates = [row[0] for row in digest["ranking_rows"]]
    candidate_indices = {iv: i for i, iv in enumerate(candidates)}
    out["candidate_ivs"] = candidates
    out["crossover_columns"][3:] = [
        "above500_candidate_indices", "best_index_rating",
        "second_index_rating", "worst_index_rating",
    ]
    for row in out["crossover_rows"]:
        row[1] = opponent_index(row[1])
        row[3] = [candidate_indices[iv] for iv in row[3]]
        for col in (4, 5, 6):
            if row[col] is not None:
                row[col] = [candidate_indices[row[col][0]], row[col][1]]
    out["focus_matchups"] = [
        {"opponent_index": opponent_index(row["opponent"]), "by_iv": row["by_iv"]}
        for row in digest["focus_matchups"]
    ]
    out["tradeoff_columns"] = ["lower_than_best", "lost_gt500", "example"]
    out["tradeoff_example_columns"] = [
        "opponent_index", "shield", "rating", "best_iv", "best_rating", "gap", "focus",
    ]
    out["tradeoff_rows"] = []
    for item in digest["candidate_tradeoffs"]:
        event = item["example"]
        example = None if event is None else [
            opponent_index(event["opponent"]), event["shield"], event["rating"],
            event["best_iv"], event["best_rating"], event["gap"], event["focus"],
        ]
        out["tradeoff_rows"].append([
            item["lower_than_best"], item["lost_gt500"], example,
        ])
    out["opponents"] = names
    out["opponent_index_base"] = 0
    out["tradeoff_scope"] = "rows in candidate_ivs order; all matchups counted; one selective example per IV; best reference varies by matchup"
    return _compact_numbers(out)
