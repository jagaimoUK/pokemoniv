"""Experimental 1v1 reinforcement-learning decision adapter.

Each step replays the *existing* observation-conditioned native PvPoke runner
from the beginning. It deliberately does not modify the pinned engine,
Sandbox results, or existing database. This is a correctness spike, NOT an
efficient training environment or a verified live-game policy.

Only public ObservationV2 events are returned to the decision policy. The
complete opponent setup remains inside the private replay request.
"""
from __future__ import annotations

from copy import deepcopy

from pvpoke_observed_observation import Context, ObservationV2, digest


class ReplayStepError(RuntimeError):
    """The native replay cannot safely establish the next decision state."""


class ReplayStepEnv:
    """Gymnasium-shaped reset/step prototype around observed-native-v2 replay.

    The injected runner receives a *private* validated native request and
    returns the observed-native-v2 receipt. Pass only the returned observation
    to a policy. Python object introspection is not a security boundary.
    """

    def __init__(self, request, context: Context, runner, *, horizon=20,
                 seed=0, branch=None):
        if not isinstance(context, Context) or not callable(runner):
            raise ValueError("A public Context and callable native runner are required")
        if type(request) is not dict or "observed_v2" in request:
            raise ValueError("Expected a prepared native request without a replay plan")
        if type(horizon) is not int or not 1 <= horizon <= 500:
            raise ValueError("Replay horizon must be 1..500")
        if type(seed) is not int or not 0 <= seed <= 2147483647:
            raise ValueError("Replay seed is invalid")
        if branch is None:
            branch = {"fast_delay": 0, "miss_first_fast": False,
                      "reverse_fast_batch": False}
        if (type(branch) is not dict or set(branch) !=
                {"fast_delay", "miss_first_fast", "reverse_fast_batch"} or
                type(branch["fast_delay"]) is not int or not 0 <= branch["fast_delay"] <= 2 or
                any(type(branch[name]) is not bool
                    for name in ("miss_first_fast", "reverse_fast_batch"))):
            raise ValueError("Unsupported replay branch")
        try:
            own = request["self"]
            opponent = request["opponent"]
            costs = tuple(m["energy_cost"] for m in request["policy"]["own_charged_moves"])
            initial_energy = request["initial"][0].get("energy_points", 0)
            shields = tuple(request["shields"])
        except (KeyError, IndexError, TypeError, AttributeError) as error:
            raise ValueError("Incomplete native request") from error
        if (context.build_id != digest(own) or
                context.public_opponent != opponent.get("species") or
                context.costs != costs or context.initial_energy != initial_energy or
                context.initial_shields != shields):
            raise ValueError("Public Context does not match the prepared native request")
        self._request = deepcopy(request)
        self._context = context
        self._runner = runner
        self._horizon = horizon
        self._seed = seed
        self._branch = deepcopy(branch)
        self._table = {}
        self._events = []
        self._view = None
        self._done = True

    def _replay(self, table):
        request = deepcopy(self._request)
        request["observed_v2"] = {
            "context_hash": self._context.key,
            "table": dict(table),
            "horizon": self._horizon,
            "branch": deepcopy(self._branch),
            "seed": self._seed,
        }
        result = self._runner(request)
        if type(result) is not dict or result.get("schema") != "observed-native-v2":
            raise ReplayStepError("Invalid native replay receipt")
        return result

    def _frontier(self, receipt):
        events = receipt.get("events")
        if receipt.get("status") != "frontier":
            raise ReplayStepError("Native replay did not reach a decision frontier")
        try:
            view = ObservationV2.read(self._context, events)
        except (ValueError, KeyError, TypeError) as error:
            raise ReplayStepError("Invalid public observation history") from error
        if (receipt.get("key") != view.key or
                receipt.get("legal") != list(view.legal)):
            raise ReplayStepError("Native frontier disagrees with public observation")
        return view, deepcopy(events)

    @staticmethod
    def _observation(view, events):
        own_energy, own_shields, opponent_shields = view.self_knowledge
        return {
            "phase": view.phase,
            "history_key": view.key,
            "own_energy": own_energy,
            "own_shields": own_shields,
            "opponent_shields_visible": opponent_shields,
            "legal_actions": list(view.legal),
            "public_events": deepcopy(events),
            "timing_candidates": list(view.timing_candidates),
        }

    @staticmethod
    def _info(**extra):
        return {
            "experimental": True,
            "information_fairness": "not_established",
            "live_reproducibility": "not_verified",
            **extra,
        }

    def reset(self):
        """Return (public_observation, info), with no opponent private state."""
        receipt = self._replay({})
        view, events = self._frontier(receipt)
        self._table = {}
        self._view = view
        self._events = events
        self._done = False
        return self._observation(view, events), self._info()

    def step(self, action):
        """Return (observation, reward, terminated, truncated, info).

        Each call *replays* the whole history, so it is not suitable for bulk
        reinforcement learning until replaced with a persistent-step runner.
        """
        if self._done or self._view is None:
            raise ReplayStepError("Call reset() before step() or after episode end")
        if type(action) is not str or action not in self._view.legal:
            raise ValueError("Action is not legal in the public observation")
        proposed = dict(self._table)
        proposed[self._view.key] = action
        receipt = self._replay(proposed)
        status = receipt.get("status")

        if status == "unknown":
            self._table = proposed
            self._done = True
            reason = receipt.get("reason")
            if type(reason) is not str:
                raise ReplayStepError("Unknown replay result without a reason")
            return None, 0.0, False, True, self._info(reason=reason)

        if status not in ("frontier", "complete"):
            raise ReplayStepError("Unexpected native replay status")
        events = receipt.get("events")
        if type(events) is not list or events[:len(self._events)] != self._events:
            raise ReplayStepError("Replay diverged from the previous public history")
        following = events[len(self._events):]
        if not following or following[0].get("kind") != "intent" or following[0].get("action") != action:
            raise ReplayStepError("Native replay did not commit the requested action")

        if status == "frontier":
            view, observed = self._frontier(receipt)
            self._view, self._events, self._table = view, observed, proposed
            return self._observation(view, observed), 0.0, False, False, self._info()

        # Reuse the native search's terminal ledger checks. Never reward a
        # forged win or a malformed HP/energy/shield receipt.
        from pvpoke_observed_search import _cell
        try:
            outcome = _cell(receipt)["outcome"]
        except (ValueError, KeyError, TypeError) as error:
            raise ReplayStepError("Invalid native terminal result") from error
        self._table = proposed
        self._done = True
        if outcome == "timeout":
            return None, 0.0, False, True, self._info(reason="horizon")
        reward = 1.0 if outcome == "self_ko_win" else -1.0 if outcome == "opponent_ko_win" else 0.0
        return None, reward, True, False, self._info(outcome=outcome)


def native_runner_for(sandbox, *, timeout=20):
    """Use the existing bounded native replay transport without a new endpoint."""
    if type(timeout) not in (int, float) or not 0 < timeout <= 120:
        raise ValueError("Invalid native replay timeout")

    def run(request):
        from pvpoke_observed_search import native_replay
        receipt, _rss = native_replay(sandbox, request, timeout)
        if receipt.get("status") == "unknown" and "schema" not in receipt:
            return {"schema": "observed-native-v2", **receipt}
        return receipt

    return run
