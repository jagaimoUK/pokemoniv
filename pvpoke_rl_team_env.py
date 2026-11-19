"""Local native team environments driven by public observations and legal actions.

The coordinator owns the private roster and replay. Pass only copies returned
by observe(), reset() and step() to a policy. There is no HTTP endpoint.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from pvpoke_rl_step_client import ROOT, NativeStepError, _NativeWorkerTransport
from pvpoke_rl_team_preview import SixToThreeSelection

SCHEMA = "rl-native-3v3-v1"
ACTIONS = frozenset(("wait", "fast", "charge_0", "charge_1",
                     "switch_0", "switch_1", "switch_2", "shield_yes", "shield_no"))
OUTCOME_REWARD = {"self_ko_win": 1, "opponent_ko_win": -1, "simultaneous_ko": 0}


class ThreeVThreeEnvironment(_NativeWorkerTransport):
    """One persistent native worker, with a CPU using only its own view."""

    def __init__(self, gamemaster, *, source=ROOT / "vendor/pvpoke", timeout=10.0):
        super().__init__(source, timeout=timeout)
        self._gamemaster = Path(gamemaster).resolve(strict=True)
        if not self._gamemaster.is_file():
            raise ValueError("GameMaster must be a file")
        self._observation = None

    def close(self):
        super().close()
        self._observation = None

    def observe(self):
        return deepcopy(self._observation)

    def legal_actions(self):
        return tuple(self._observation["legal_actions"]) if self._observation else ()

    def _read_result(self, response):
        result = response.get("result")
        if type(result) is dict:
            observation = result.get("observation")
            reward = result.get("reward")
            terminated = result.get("terminated")
            truncated = result.get("truncated")
            info = result.get("info")
            if (type(info) is dict and info.get("schema") == SCHEMA and
                    type(terminated) is bool and type(truncated) is bool and
                    not (terminated and truncated) and
                    info.get("training_eligible") is terminated):
                outcome = info.get("outcome")
                if observation is None and (
                        terminated and type(reward) is int and
                        type(outcome) is str and OUTCOME_REWARD.get(outcome) == reward or
                        truncated and reward is None and outcome in ("timeout", "unsupported")):
                    self._observation = None
                    return None, reward, terminated, truncated, info
                if (not terminated and not truncated and reward is None and outcome is None
                        and type(observation) is dict and observation.get("schema") == SCHEMA
                        and type(observation.get("legal_actions")) is list
                        and observation["legal_actions"]
                        and all(type(action) is str and action in ACTIONS
                                for action in observation["legal_actions"])):
                    self._observation = observation
                    return self.observe(), None, False, False, info
        self.close()
        raise NativeStepError("Invalid native team result")

    def reset(self, handoff, *, seed=0, horizon=500):
        """Start from a trusted lead-first handoff and return (observation, info)."""
        if type(seed) is not int or not 0 <= seed <= 0xffffffff:
            raise ValueError("Seed must be a 32-bit unsigned integer")
        if type(horizon) is not int or not 1 <= horizon <= 500:
            raise ValueError("Invalid horizon")
        observation, _, terminated, truncated, info = self._read_result(self._rpc({
            "op": "team_reset", "handoff": handoff, "gamemaster_path": str(self._gamemaster),
            "seed": seed, "horizon": horizon,
        }))
        return observation, {**info, "terminated": terminated, "truncated": truncated}

    def step(self, action):
        if self._observation is None:
            raise NativeStepError("No active team decision")
        if type(action) is not str or action not in self.legal_actions():
            raise ValueError("Illegal action for the current team decision")
        return self._read_result(self._rpc({"op": "team_step", "action": action}))

    def private_replay(self):
        """Trusted two-sided history, RNG draws and native resource snapshots."""
        if self._proc is None:
            raise NativeStepError("No native episode to replay")
        return self._rpc({"op": "team_replay"})["replay"]


class SixToThreeEnvironment:
    """One selection action followed by the same episode's tactical decisions."""

    def __init__(self, gamemaster, own_six, opponent_public_six, opponent_private_six,
                 opponent_chosen_three, opponent_lead, *, ruleset_id,
                 source=ROOT / "vendor/pvpoke", timeout=10.0):
        self._rosters = deepcopy((own_six, opponent_public_six, opponent_private_six,
                                  opponent_chosen_three, opponent_lead))
        self._ruleset_id = ruleset_id
        self._battle = ThreeVThreeEnvironment(gamemaster, source=source, timeout=timeout)
        self._selection = None
        self._chosen_action = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self._battle.close()
        self._selection = None
        self._chosen_action = None

    def reset(self, *, seed=0, horizon=500):
        if type(seed) is not int or not 0 <= seed <= 0xffffffff:
            raise ValueError("Seed must be a 32-bit unsigned integer")
        if type(horizon) is not int or not 1 <= horizon <= 500:
            raise ValueError("Invalid horizon")
        self._selection = SixToThreeSelection(*self._rosters, ruleset_id=self._ruleset_id)
        self._chosen_action = None
        self._seed, self._horizon = seed, horizon
        return self.observe(), {"training_eligible": False}

    def observe(self):
        if self._selection is None:
            return None
        if self._chosen_action is None:
            return self._selection.observe()
        return self._battle.observe()

    def legal_actions(self):
        if self._selection is None:
            return ()
        if self._chosen_action is None:
            return tuple(self._selection.observe()["legal_actions"])
        return self._battle.legal_actions()

    def step(self, action):
        if self._selection is None:
            raise NativeStepError("Call reset() before step()")
        if self._chosen_action is None:
            self._selection.choose(action)
            self._chosen_action = action
            observation, info = self._battle.reset(
                self._selection._private_engine_input(), seed=self._seed, horizon=self._horizon)
            return observation, None, info["terminated"], info["truncated"], info
        observation, reward, terminated, truncated, info = self._battle.step(action)
        if terminated:
            info = {**info, "selection_reward": reward}
        return observation, reward, terminated, truncated, info

    def private_replay(self):
        if self._chosen_action is None:
            raise NativeStepError("No committed selection to replay")
        return {"selection": self._chosen_action, "battle": self._battle.private_replay()}
