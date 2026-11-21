"""Bounded, process-local web sessions for the native 6-to-3 practice battle."""
from copy import deepcopy
from dataclasses import dataclass, field
import logging
import os
import re
import secrets
from threading import Lock, Timer
from time import monotonic

from pvpoke_party_backend import PartyBuilder
from pvpoke_rl_team_env import OUTCOME_REWARD, SCHEMA, SixToThreeEnvironment
from pvpoke_rl_team_preview import FIELDS, six, prepared

APP_PATH = "/app-api/team-battle/"
API_PATH = "/api/team-battle/"
OPERATIONS = ("start", "state", "step", "close")
APP_ROUTES = frozenset(APP_PATH + operation for operation in OPERATIONS)
API_ROUTES = frozenset(API_PATH + operation for operation in OPERATIONS)
SCOPE_HEADER = "X-PvPoke-Battle-Scope"
MAX_REQUEST_BYTES = 2048
RULESET = "cp1500-lv50-v1"
PREVIEW_SCHEMA = "rl-6v3-preview-v1"
SESSION_SCHEMA = "team-battle-v1"
SESSION_ID = re.compile(r"[A-Za-z0-9_-]{32}")
SCOPE = re.compile(r"[0-9a-f]{64}")


def enabled():
    return os.environ.get("PVP_TEAM_BATTLE_ENABLED") == "1"


class BattleRequestError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def prepare_roster(rows, *, catalog, species, cpms, engine):
    """Convert Party Builder cards in their original slot order."""
    if type(rows) is not list or len(rows) != 6 or any(type(row) is not dict for row in rows):
        raise ValueError("Exactly six saved members are required")
    for row in rows:
        level = row.get("level_override")
        if level is None:
            continue
        if type(level) is str:
            level = float(level)
        if type(level) not in (int, float) or not 1 <= level <= 50 or level * 2 % 1 != 0:
            raise ValueError("Invalid saved level override")
    normalized = PartyBuilder._normalize(rows, catalog, species, cpms, engine, "対戦パーティ")
    roster = [{key: row["id" if key == "combatant_id" else key] for key in FIELDS}
              for row in normalized]
    return six(roster, prepared, with_ids=True)


def saved_rosters(payload, get_party, **game_data):
    if not {"party_id"} <= payload.keys() <= {"party_id", "opponent_party_id"}:
        raise BattleRequestError(400, "Invalid battle setup")
    party_ids = tuple(payload.values())
    if any(type(value) is not str or not 1 <= len(value) <= 64 for value in party_ids):
        raise BattleRequestError(400, "Invalid party ID")
    try:
        own = get_party(payload["party_id"])
        opponent_id = payload.get("opponent_party_id")
        opponent = own if opponent_id is None or opponent_id == payload["party_id"] else get_party(opponent_id)
    except ValueError as error:
        raise BattleRequestError(404, "Saved party not found") from error
    try:
        if any(party.get("ruleset") not in (None, "cp1500-lv50") for party in (own, opponent)):
            raise ValueError("Unsupported saved ruleset")
        own_six = prepare_roster(own.get("members"), **game_data)
        opponent_six = prepare_roster(
            opponent.get("opponents" if opponent_id is None else "members"), **game_data)
    except ValueError as error:
        raise BattleRequestError(422, "Both sides need six valid Great League members") from error
    return own_six, opponent_six


def public_observation(view):
    """Keep the HTTP response on the engine's public observation contract."""
    def pick(row, keys):
        return {key: row[key] for key in keys.split()}

    base = pick(view, "schema phase ruleset_id legal_actions")
    if view["schema"] == PREVIEW_SCHEMA:
        return {**base,
                "own_six": [{key: row[key] for key in FIELDS} for row in view["own_six"]],
                "opponent_public_six": [pick(row, "species roster_clause_id known_moves")
                                        for row in view["opponent_public_six"]],
                "opponent_selected_three_known": False}
    if view["schema"] != SCHEMA:
        raise ValueError("Unknown battle observation schema")
    own, opponent = view["own"], view["opponent"]
    team = []
    for row in own["team"]:
        member = pick(row, "species hp max_hp energy_points buffs cooldown_ms combatant_id fast_move")
        member["charged_moves"] = [pick(move, "move_id energy_cost") for move in row["charged_moves"]]
        team.append(member)
    event_fields = ("seq", "turn", "kind", "actor", "species",
                    "move_id", "shielded", "previous_species", "forced")
    return {**base, **pick(view, "turn elapsed_ms"),
            "own": {**pick(own, "active_slot shields switch_timer_ms"), "team": team},
            "opponent": {**pick(opponent, "active_species shields"),
                         "revealed": [pick(row, "species fainted hp_bucket_5pct seen_moves")
                                      for row in opponent["revealed"]]},
            "recent_events": [{key: row[key] for key in event_fields if key in row}
                              for row in view["recent_events"]]}


@dataclass
class BattleSession:
    scope: str
    environment: SixToThreeEnvironment
    observation: dict | None
    expires_at: float
    revision: int = 0
    status: str = "select_three"
    result: dict | None = None
    lock: Lock = field(default_factory=Lock)
    timer: Timer | None = None
    closed: bool = False

    def snapshot(self, battle_id):
        return {"schema": SESSION_SCHEMA, "battle_id": battle_id, "revision": self.revision,
                "status": self.status, "observation": deepcopy(self.observation),
                "result": deepcopy(self.result)}


class BattleSessions:
    def __init__(self, *, capacity=2, idle_seconds=600):
        self._sessions = {}
        self._lock = Lock()
        self._capacity = capacity
        self._idle_seconds = idle_seconds

    def start(self, scope, gamemaster, own, opponent):
        with self._lock:
            if len(self._sessions) >= self._capacity:
                raise BattleRequestError(503, "All battle slots are occupied")
            preview = [{key: row[key] for key in ("species", "roster_clause_id")} for row in opponent]
            chosen = secrets.SystemRandom().sample(range(6), 3)
            environment = SixToThreeEnvironment(
                gamemaster, own, preview, opponent, chosen, chosen[0], ruleset_id=RULESET)
            try:
                view, _ = environment.reset(seed=secrets.randbits(32))
                observation = public_observation(view)
            except Exception:
                environment.close()
                raise
            battle_id = secrets.token_urlsafe(24)
            session = BattleSession(scope, environment, observation, monotonic() + self._idle_seconds)
            try:
                self._schedule_expiry(battle_id, session, self._idle_seconds)
            except RuntimeError:
                environment.close()
                raise
            self._sessions[battle_id] = session
            return session.snapshot(battle_id)

    def _schedule_expiry(self, battle_id, session, delay):
        session.timer = Timer(delay, self._expire, args=(battle_id, session))
        session.timer.daemon = True
        session.timer.start()

    def _expire(self, battle_id, session):
        with session.lock:
            if session.closed:
                return
            remaining = session.expires_at - monotonic()
            if remaining > 0:
                self._schedule_expiry(battle_id, session, remaining)
            else:
                self._remove(battle_id, session)

    def _remove(self, battle_id, session):
        session.closed = True
        session.timer.cancel()
        try:
            session.environment.close()
        finally:
            with self._lock:
                del self._sessions[battle_id]

    def operate(self, scope, operation, payload):
        fields = {"battle_id", "revision", "action"} if operation == "step" else {"battle_id"}
        battle_id = payload.get("battle_id")
        if (payload.keys() != fields or type(battle_id) is not str or
                not SESSION_ID.fullmatch(battle_id)):
            raise BattleRequestError(400, "Invalid battle request")
        with self._lock:
            session = self._sessions.get(battle_id)
            if session is None or session.scope != scope:
                raise BattleRequestError(404, "Battle session not found")
        if not session.lock.acquire(blocking=False):
            raise BattleRequestError(409, "Battle action is in progress")
        try:
            if session.closed:
                raise BattleRequestError(404, "Battle session not found")
            if session.expires_at <= monotonic():
                self._remove(battle_id, session)
                raise BattleRequestError(404, "Battle session expired")
            if operation == "close":
                self._remove(battle_id, session)
                return {"battle_id": battle_id, "closed": True}
            try:
                if operation == "step":
                    self._step(session, payload["revision"], payload["action"])
            finally:
                session.expires_at = monotonic() + self._idle_seconds
            return session.snapshot(battle_id)
        finally:
            session.lock.release()

    @staticmethod
    def _step(session, revision, action):
        if type(revision) is not int or revision < 0 or type(action) is not str:
            raise BattleRequestError(400, "Invalid battle action or revision")
        if revision != session.revision or session.observation is None:
            raise BattleRequestError(409, "Battle revision has changed or battle has ended")
        if action not in session.observation["legal_actions"]:
            raise BattleRequestError(422, "Action is not legal for the current decision")
        session.revision += 1
        try:
            view, _, terminated, truncated, info = session.environment.step(action)
            if terminated or truncated:
                outcome = info["outcome"]
                if ((terminated and (truncated or outcome not in OUTCOME_REWARD)) or
                        (truncated and outcome not in ("timeout", "unsupported"))):
                    raise ValueError("Invalid battle outcome")
                session.status = "terminated" if terminated else "truncated"
                session.result = {"outcome": outcome, "turns": info["turns"],
                                  "elapsed_ms": info["elapsed_ms"]}
                session.observation = None
                session.environment.close()
            else:
                session.observation = public_observation(view)
                session.status = "battle"
        except Exception as error:
            # A step may have advanced before the transport failed. Discard the
            # worker and never retry the action against an uncertain state.
            session.observation = None
            session.status = "unavailable"
            session.result = None
            session.environment.close()
            logging.warning("Team battle step failed: %s", type(error).__name__)
            raise BattleRequestError(503, "Battle worker unavailable") from error
