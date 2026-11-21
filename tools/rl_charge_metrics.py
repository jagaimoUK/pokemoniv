"""Public battle strata and paired terminal metrics shared by charge studies."""
from collections import Counter

BATTLE_CLOCK_MS = 240000


def charge_stratum(public_state):
    """Predeclared buckets using the rounded public HP and the native clock."""
    hp = public_state["hp_bucket_5pct"]
    shields = public_state["opponent_shields"]
    remaining = BATTLE_CLOCK_MS - public_state["elapsed_ms"]
    if not 0 <= hp <= 20 or not 0 <= shields <= 2 or not 0 <= remaining <= BATTLE_CLOCK_MS:
        raise ValueError("Invalid public charge-fork state")
    hp_band = ("0–25%", "30–50%", "55–75%", "80–100%")[max(0, (hp - 1) // 5)]
    time_band = "≤30s" if remaining <= 30000 else ">30–60s" if remaining <= 60000 else ">60s"
    return f"{hp_band} / {shields} shield / {time_band}"


def paired_charge_rewards(pairs):
    """Terminal delta is alternative minus immediate, among jointly completed pairs."""
    deltas = [b["reward"] - a["reward"] for a, b in pairs
              if a["reward"] is not None and b["reward"] is not None]
    return {
        "attempted": len(pairs), "both_completed": len(deltas),
        "both_completed_rate": len(deltas) / len(pairs) if pairs else None,
        "alternative_better": sum(d > 0 for d in deltas), "equal": sum(d == 0 for d in deltas),
        "alternative_worse": sum(d < 0 for d in deltas),
        "mean_reward_delta": sum(deltas) / len(deltas) if deltas else None,
        "immediate_censored": dict(Counter(a["outcome"] for a, _ in pairs if a["reward"] is None)),
        "alternative_censored": dict(Counter(b["outcome"] for _, b in pairs if b["reward"] is None)),
    }
