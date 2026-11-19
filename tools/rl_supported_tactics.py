"""Offline v2 ablation: require comparative evidence before deviating."""
from pvpoke_rl_mc_generalized import GeneralizedMonteCarloPolicy
from pvpoke_rl_mc_train import PRIORITY

MIN_EPISODES = 2


def compare_tactical_actions(legal, table):
    """Return the cold action, supported choice and whether both were sampled."""
    ordered = sorted(legal, key=PRIORITY.index)
    baseline = ordered[0]
    action = baseline
    baseline_count, best_return = table.get(baseline, (0, 0.0))
    comparable = False
    if baseline_count >= MIN_EPISODES:
        for candidate in ordered[1:]:
            count, mean = table.get(candidate, (0, 0.0))
            if count < MIN_EPISODES:
                continue
            comparable = True
            if mean > best_return:
                action, best_return = candidate, mean
    return baseline, action, comparable


class SupportedTacticsPolicy(GeneralizedMonteCarloPolicy):
    """Greedy tactical overlay for a restored, unchanged v2 checkpoint.

    Use the cold v2 action unless another legal action has a strictly better
    observed average terminal return and both have at least two visits.
    First-visit counts are per completed episode; this is a support threshold,
    not a causal estimate or a confidence bound.
    """

    def _choose_encoded(self, encoded, *, epsilon):
        kind, key, legal = encoded
        if kind != "tactics" or type(epsilon) not in (int, float) or epsilon != 0:
            return super()._choose_encoded(encoded, epsilon=epsilon)

        # Preserve v2's RNG advancement even for deterministic decisions.
        self._rng.random()
        table = self._values[kind].get(key, {})
        _, action, _ = compare_tactical_actions(legal, table)
        return action, (kind, key, action)
