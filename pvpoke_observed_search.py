"""Bounded offline search for one shared policy over declared scenarios."""
from dataclasses import asdict
import json
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time

from pvpoke_battle_store import BattleStoreError
from pvpoke_calculation_version import content_hash
from pvpoke_child_env import child_environment
from pvpoke_observed_audit import audit_v2
from pvpoke_observed_observation import Context, FLAGS, MODEL, ObservationV2, canonical, digest, integer

from pvpoke_observed_roles import KNOWN, VERSION as ROLE_VERSION, compare, evaluate_roles, normalize_roles

# The prior search module is part of existing persisted plan identities.
LEGACY_SEARCH_HASH = "1e31f67621e7f18430059a92f701eaed2822e98b0b4c55c45071c94fa9a56340"

RUNNER = Path(__file__).with_name("pvpoke_observed_native_runner.js")
MAX_WORK = 4096
MAX_POLICIES = 64
MAX_STEP = 8
STEP_SECONDS = 5
RSS_KIB = 256 * 1024
MAX_OUTPUT = 512 * 1024
OUTCOMES = ("opponent_ko_win", "simultaneous_ko", "self_ko_win")
UNKNOWN_REASONS = {"unsupported_uncertainty", "history_limit", "invalid_policy_intent",
                   "wall_limit", "memory_limit", "runner_unavailable", "replay_mismatch"}
SCHEMA = "observed-search-v2"


def initial_state():
    return {"frontier": [{"table": {}, "index": 0, "cells": [], "prefix": None}],
            "evaluations": [], "work": 0, "pruned": False, "stop_reason": None, "peak_rss_kib": 0}


class Search:
    def __init__(self, context, scenarios, roles=None):
        self.context = context
        self.roles = roles
        self.scenarios = tuple(sorted(scenarios))
        if (not 1 <= len(self.scenarios) <= 32 * 8 * 4
                or len(set(self.scenarios)) != len(self.scenarios)):
            raise ValueError("Invalid scenario support")

    def advance(self, state, receipt):
        """Apply one validated work receipt, without running a battle."""
        if state["stop_reason"] or not state["frontier"]:
            raise ValueError("Search cannot advance")
        item = state["frontier"][-1]
        kind = receipt["status"]
        if kind == "frontier":
            view = ObservationV2.read(self.context, receipt["events"])
            if view.key != receipt["key"] or list(view.legal) != receipt["legal"] or view.key in item["table"]:
                raise ValueError("Invalid frontier receipt")
            audit_v2(self.context, [receipt["events"]], item["table"])
        else:
            _cell(receipt)

        state["work"] += 1
        if kind == "frontier":
            state["frontier"].pop()
            capacity = MAX_POLICIES - len(state["frontier"]) - len(state["evaluations"])
            choices = view.legal[:capacity]
            state["pruned"] |= len(choices) != len(view.legal)
            for action in reversed(choices):
                state["frontier"].append({
                    **item, "cells": item["cells"].copy(), "table": {**item["table"], view.key: action},
                    "prefix": {"events": receipt["events"], "action": action},
                })
        else:
            item["cells"].append(_cell(receipt))
            item["index"] += 1
            item["prefix"] = None
            if item["index"] == len(self.scenarios):
                state["evaluations"].append(self.evaluate(item))
                state["frontier"].pop()

        if not state["frontier"]:
            results = state["evaluations"]
            state["stop_reason"] = ("policy_found" if any(r["role"] is True for r in results) else
                                    "policy_limit" if state["pruned"] else
                                    "incomplete" if any(r["unknown"] for r in results) else
                                    "no_policy_in_declared_class")
        elif state["work"] >= MAX_WORK:
            state["stop_reason"] = "work_limit"

    def evaluate(self, item):
        cells = item["cells"]
        known = [c for c in cells if c["outcome"] in (KNOWN if self.roles else OUTCOMES)]
        unknown = len(cells) - len(known) + len(self.scenarios) - len(cells)
        roles = evaluate_roles(self.roles, cells, len(self.scenarios)) if self.roles else None
        failed = (sum(any(role["scenario_meets"][i] is False for role in roles)
                      for i in range(len(cells))) if roles else
                  sum(c["outcome"] != "self_ko_win" for c in known))
        return {
            **({"roles": roles} if roles else {}),
            "policy_hash": digest([self.context.key, item["table"]]),
            "policy": item["table"], "tested": len(known), "failed": failed, "unknown": unknown,
            "role": (False if any(r["meets"] is False for r in roles) else
                     None if unknown else True) if roles else (False if failed else None if unknown else True),
            "worst_outcome": roles[0]["worst_outcome"] if roles else None if unknown else min((c["outcome"] for c in known), key=OUTCOMES.index),
            "resources": [c["terminal"][0] for c in known],
            "outcomes": [c["outcome"] for c in cells],
            "expected_value": None, "scope_complete": not unknown,
            "opponent_response_complete": False, **FLAGS,
        }


def _cell(receipt):
    kind = receipt["status"]
    if kind == "unknown" and receipt.get("reason") in UNKNOWN_REASONS:
        return {"outcome": receipt["reason"]}
    if kind != "complete":
        raise ValueError("Invalid result kind")
    terminal = receipt["terminal"]
    if (type(terminal) is not list or len(terminal) != 2 or
            any(type(row) is not list or len(row) != 3 or
                not all(integer(n, 0, limit) for n, limit in zip(row, (10000, 100, 2)))
                for row in terminal)):
        raise ValueError("Invalid native terminal state")
    hp = [row[0] for row in terminal]
    outcome = ("simultaneous_ko" if hp == [0, 0] else "self_ko_win" if hp[1] == 0 else
               "opponent_ko_win" if hp[0] == 0 else "timeout")
    if outcome != receipt.get("outcome"):
        raise ValueError("Outcome differs from terminal HP")
    return {"outcome": outcome, "terminal": terminal}



def validate_damage(receipt, battle=None, move_data=None):
    """Validate the compact HP/shield ledger before accepting saved evidence."""
    _cell(receipt)
    initial, moves = receipt["initial"], receipt["moves"]
    if (type(initial) is not list or len(initial) != 2 or
            any(type(row) is not list or len(row) != 3 or not integer(row[0], 1, 10000)
                or not integer(row[1], 0, 100) or not integer(row[2], 0, 2) for row in initial)
            or type(moves) is not list or len(moves) > 1000):
        raise ValueError("Invalid initial replay state")
    if battle is not None:
        for side, row in enumerate(initial):
            configured = battle["initial"][side]
            expected_hp = configured.get("hp_points")
            if ((expected_hp is not None and row[0] != expected_hp)
                    or row[1] != configured.get("energy_points", 0) or row[2] != battle["shields"][side]):
                raise ValueError("Initial state differs from declared world")
    energy = [row[1] for row in initial]
    hp = [row[0] for row in initial]
    shields = [row[2] for row in initial]
    last_window = 1
    for move in moves:
        if (type(move) is not dict or set(move) != {"actor", "move", "kind", "window", "damage", "shielded"}
                or not integer(move["actor"], 0, 1) or move["kind"] not in ("fast", "charged")
                or not integer(move["window"], last_window, 500) or type(move["shielded"]) is not bool):
            raise ValueError("Invalid native move receipt")
        last_window = move["window"]
        actor = move["actor"]
        target = 1 - actor
        if move_data is not None:
            build = battle["self" if actor == 0 else "opponent"]
            equipped = (build["fast"],) if move["kind"] == "fast" else (build["charged1"], build["charged2"])
            if move["move"] not in equipped:
                raise ValueError("Resolved move is not equipped")
            gm_move = move_data[move["move"]]
            if move["kind"] == "fast":
                energy[actor] = min(100, energy[actor] + int(gm_move["energyGain"]))
            else:
                energy[actor] -= int(gm_move["energy"])
                if energy[actor] < 0:
                    raise ValueError("Insufficient energy for resolved charge")
        if not integer(move["damage"], 0, hp[target]):
            raise ValueError("Invalid applied damage")
        if move["shielded"]:
            if not shields[target] or move["kind"] != "charged" or move["damage"] > 1:
                raise ValueError("Invalid shield consumption")
            shields[target] -= 1
        hp[target] -= move["damage"]
    for side, terminal in enumerate(receipt["terminal"]):
        if ((hp[side], shields[side]) != (terminal[0], terminal[2])
                or (move_data is not None and energy[side] != terminal[1])):
            raise ValueError("Terminal state differs from native move ledger")

def _monitor(process, done, usage):
    """Observe Linux child RSS while the synchronous replay runs."""
    status = Path(f"/proc/{process.pid}/status")
    while not done.is_set():
        try:
            values = [int(line.split()[1]) for line in status.read_text().splitlines()
                      if line.startswith(("VmRSS:", "VmHWM:"))]
            usage[0] = max([usage[0], *values])
            if usage[0] > RSS_KIB:
                process.kill()
                return
        except (FileNotFoundError, ProcessLookupError):
            return
        done.wait(0.01)


def native_replay(sandbox, request, timeout):
    if not Path("/proc/self/status").is_file() or not shutil.which("node"):
        return {"status": "unknown", "reason": "runner_unavailable"}, 0
    env = child_environment({"PVP_PVPOKE_SOURCE": str(sandbox.standard.client.source)})
    done, usage = threading.Event(), [0]
    with subprocess.Popen(
        ["node", "--max-old-space-size=96", str(RUNNER)], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
    ) as process:
        watcher = threading.Thread(target=_monitor, args=(process, done, usage))
        watcher.start()
        try:
            output, _ = process.communicate(canonical(request).encode(), timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            return {"status": "unknown", "reason": "wall_limit"}, usage[0]
        finally:
            done.set()
            watcher.join()
        if usage[0] > RSS_KIB:
            return {"status": "unknown", "reason": "memory_limit"}, usage[0]
        if process.returncode or len(output) > MAX_OUTPUT:
            return {"status": "unknown", "reason": "runner_unavailable"}, usage[0]
    result = json.loads(output)
    if result.get("schema") != "observed-native-v2":
        raise ValueError("Invalid native replay response")
    return result, usage[0]


def _move_data(sandbox):
    gm = json.loads(sandbox.standard.client.gamemaster.read_bytes())
    return {row["moveId"]: row for row in gm["moves"]}


def prepare(sandbox, worlds, controllers, branches, horizon, roles=None):
    """Normalize all declared worlds through the existing Sandbox contract."""
    if (type(worlds) is not list or not 1 <= len(worlds) <= 32
            or type(controllers) is not list or not 1 <= len(controllers) <= 8
            or type(branches) is not list or not 1 <= len(branches) <= 4
            or not integer(horizon, 1, 500)):
        raise ValueError("Invalid observed search bounds")
    sandbox._check_inputs()
    move_data = _move_data(sandbox)
    manifest = {}
    context = None
    self_identity = None
    for world in worlds:
        normalized, payload = sandbox.prepare(world)
        if payload.pop("actions") or payload.pop("shield_decisions"):
            raise ValueError("Observed search cannot include a scripted action")
        own, opponent = normalized["combatants"]
        if any(len(side["moves"]["charged"]) != 2 for side in (own, opponent)):
            raise ValueError("Observed replay requires two equipped charged moves per combatant")
        moves = [move_data[m] for m in own["moves"]["charged"]]
        candidate = Context(digest(payload["self"]), tuple(int(m["energy"]) for m in moves),
                            own["initial"]["energy"], tuple(payload["shields"]),
                            int(move_data[own["moves"]["fast"]]["energyGain"]),
                            opponent["species_id"])
        identity = digest([own, normalized["rules"]])
        if context is None:
            context, self_identity = candidate, identity
        if candidate != context or identity != self_identity:
            raise ValueError("All worlds must share one public context and own build")
        for controller in controllers:
            if (type(controller) is not dict or set(controller) != {"attack", "shield"}
                    or controller["attack"] not in ("standard", "charge_if_ready", "charge_slot_1", "bank_1", "bank_2")
                    or controller["shield"] not in ("standard", "always", "never", "first")):
                raise ValueError("Invalid opponent controller")
            for branch in branches:
                if (type(branch) is not dict or set(branch) != {"fast_delay", "miss_first_fast", "reverse_fast_batch"}
                        or not integer(branch["fast_delay"], 0, 2)
                        or any(type(branch[k]) is not bool for k in ("miss_first_fast", "reverse_fast_batch"))):
                    raise ValueError("Invalid observation branch")
                entry = {"battle": payload, "controller": controller, "branch": branch}
                if roles is not None:
                    entry["world_id"] = digest(payload)
                manifest[digest(entry)] = entry
    return context, {"schema": SCHEMA, "versions": versions(sandbox, roles is not None),
                     **({"roles": normalize_roles(roles)} if roles is not None else {}), "context": asdict(context),
                     "manifest": manifest, "horizon": horizon}


def versions(sandbox, extended=False):
    sandbox._check_inputs()
    paths = (RUNNER, Path(__file__), Path(__file__).with_name("pvpoke_observed_audit.py"),
             Path(__file__).with_name("pvpoke_observed_observation.py"))
    hashes = [content_hash(path) for path in paths]
    if extended:
        hashes.append(content_hash(Path(__file__).with_name("pvpoke_observed_roles.py")))
    else:
        hashes[1] = LEGACY_SEARCH_HASH
    return {**sandbox.versions, "observation_model": MODEL,
            "role": ROLE_VERSION if extended else "self_ko_win-v1", "adapter": digest(hashes)}


def replay(sandbox, context, plan, scenario, item, timeout):
    entry = plan["manifest"][scenario]
    battle = entry["battle"]
    request = {**battle, "gamemaster_path": str(sandbox.standard.client.gamemaster),
               "policy": {"own_charged_moves": [
                   {"move_id": battle["self"][f"charged{i + 1}"], "energy_cost": cost}
                   for i, cost in enumerate(context.costs)], "energy_reserve": 0, "shield_rule": "never"},
               "opponent_attack_rule": entry["controller"]["attack"],
               "opponent_shield_rule": entry["controller"]["shield"],
               "observed_v2": {"context_hash": context.key, "table": item["table"],
                               "horizon": plan["horizon"], "branch": entry["branch"], "seed": 0}}
    result, rss = native_replay(sandbox, request, timeout)
    if result["status"] == "unknown":
        return result, rss
    events = result["events"]
    prefix = item["prefix"]
    if prefix:
        previous = prefix["events"]
        index = len(previous)
        if (events[:index] != previous or len(events) <= index
                or events[index].get("kind") != "intent"
                or events[index].get("action") != prefix["action"]):
            return {"status": "unknown", "reason": "replay_mismatch"}, rss
    audit_v2(context, [events], item["table"])
    if result["status"] == "frontier":
        return {key: result[key] for key in ("status", "key", "events", "legal")}, rss
    validate_damage(result, battle, _move_data(sandbox))
    return {key: result[key] for key in ("status", "outcome", "terminal", "initial", "moves")}, rss


class ObservedSearch:
    """Owner-scoped append-only receipts. A receipt and its cursor commit together."""

    def __init__(self, sandbox):
        self.sandbox = sandbox
        self.store = sandbox.store

    def start(self, worlds, controllers, branches, horizon, roles=None):
        _, plan = prepare(self.sandbox, worlds, controllers, branches, horizon, roles)
        body = canonical(plan)
        if len(body) > 1024 * 1024:
            raise ValueError("Observed plan exceeds storage limit")
        search_id = digest(plan)
        with self.store._writer() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS observed_jobs_v2 (
                owner TEXT NOT NULL, id TEXT NOT NULL, plan TEXT NOT NULL,
                cursor INTEGER NOT NULL DEFAULT 0, paused INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (owner,id)) WITHOUT ROWID""")
            db.execute("""CREATE TABLE IF NOT EXISTS observed_work_v2 (
                owner TEXT NOT NULL, id TEXT NOT NULL, position INTEGER NOT NULL,
                work_id TEXT NOT NULL, receipt TEXT NOT NULL, digest TEXT NOT NULL,
                rss INTEGER NOT NULL, PRIMARY KEY (owner,id,position)) WITHOUT ROWID""")
            db.execute("INSERT OR IGNORE INTO observed_jobs_v2 (owner,id,plan) VALUES (?,?,?)",
                       (self.store.owner_scope, search_id, body))
        return self.get(search_id)

    def _read(self, db, search_id):
        if type(search_id) is not str or not re.fullmatch(r"[a-f0-9]{64}", search_id):
            raise ValueError("Invalid observed search ID")
        if not db.execute("SELECT 1 FROM sqlite_schema WHERE name='observed_jobs_v2'").fetchone():
            return None
        owner = self.store.owner_scope
        job = db.execute("SELECT plan,cursor,paused FROM observed_jobs_v2 WHERE owner=? AND id=?",
                         (owner, search_id)).fetchone()
        if job is None:
            return None
        body, cursor, paused = job
        if len(body) > 1024 * 1024 or not integer(cursor, 0, MAX_WORK) or paused not in (0, 1):
            raise BattleStoreError("Invalid observed checkpoint")
        plan = json.loads(body)
        if digest(plan) != search_id or plan.get("schema") != SCHEMA:
            raise BattleStoreError("Invalid observed plan")
        if plan["versions"] != versions(self.sandbox, "roles" in plan):
            return {"stale": True}
        data = plan["context"]
        context = Context(**{**data, "costs": tuple(data["costs"]),
                             "initial_shields": tuple(data["initial_shields"])})
        search = Search(context, plan["manifest"], normalize_roles(plan["roles"]) if "roles" in plan else None)
        state = initial_state()
        move_data = None
        rows = db.execute("""SELECT position,work_id,receipt,digest,rss FROM observed_work_v2
                          WHERE owner=? AND id=? ORDER BY position LIMIT ?""",
                          (owner, search_id, cursor + 1))
        for position, work_id, receipt, checksum, rss in rows:
            if (position != state["work"] or not state["frontier"] or state["stop_reason"]
                    or len(receipt) > MAX_OUTPUT or not integer(rss, 0, RSS_KIB * 2)
                    or work_id != self._work_id(search_id, search, state)):
                raise BattleStoreError("Invalid observed work position")
            value = json.loads(receipt)
            if checksum != digest([work_id, value, rss]):
                raise BattleStoreError("Invalid observed receipt checksum")
            if value["status"] == "complete":
                if move_data is None:
                    move_data = _move_data(self.sandbox)
                scenario = search.scenarios[state["frontier"][-1]["index"]]
                validate_damage(value, plan["manifest"][scenario]["battle"], move_data)
            search.advance(state, value)
            state["peak_rss_kib"] = max(state["peak_rss_kib"], rss)
        if state["work"] != cursor:
            raise BattleStoreError("Missing observed work receipt")
        return {"search": search, "state": state, "plan": plan, "paused": bool(paused)}

    @staticmethod
    def _work_id(search_id, search, state):
        item = state["frontier"][-1]
        return digest([search_id, state["work"], search.scenarios[item["index"]], item["table"]])

    def _summary(self, search_id, loaded):
        if loaded is None:
            return None
        if loaded.get("stale"):
            return {"search_id": search_id, "status": "stale", "role": None, **FLAGS}
        state = loaded["state"]
        evaluations = state["evaluations"]
        role = True if any(e["role"] is True for e in evaluations) else (
            False if state["stop_reason"] == "no_policy_in_declared_class" else None)
        extra = {}
        if loaded["search"].roles:
            candidates = []
            for index, candidate in enumerate(evaluations):
                if not any(compare(other, candidate) == "better" for other in evaluations if other is not candidate):
                    candidates.append(index)
            ordered = candidates + [i for i in range(len(evaluations)) if i not in candidates]
            manifest = loaded["plan"]["manifest"]
            world_ids = sorted({entry["world_id"] for entry in manifest.values()})
            representatives = {entry["world_id"]: entry["battle"]["opponent"] for entry in manifest.values()}
            world_numbers = {wid: i for i, wid in enumerate(world_ids, 1)}
            extra = {"roles": loaded["search"].roles,
                     "worlds": [{"id": wid, "opponent": representatives[wid]} for wid in world_ids],
                     "scenario_worlds": [world_numbers[manifest[key]["world_id"]]
                                         for key in loaded["search"].scenarios],
                     "active_coverage": (loaded["search"].evaluate(state["frontier"][-1])
                                         if state["frontier"] else None), "undominated_count": len(candidates),
                     "comparisons": [{"left": i + 1, "right": j + 1, "order": compare(evaluations[i], evaluations[j])}
                                     for n, i in enumerate(ordered[:8]) for j in ordered[:8][n+1:]],
                     "policy_numbers": [i + 1 for i in ordered[:8]]}
            evaluations = [evaluations[i] for i in ordered]
        return {**extra, "search_id": search_id, "schema": SCHEMA, "work": state["work"],
                "scenario_count": len(loaded["search"].scenarios), "paused": loaded["paused"],
                "stop_reason": state["stop_reason"], "role": role, "expected_value": None,
                "evaluations": evaluations[:8], "evaluation_count": len(evaluations),
                "policy_scope_truncated": state["pruned"], "peak_rss_kib": state["peak_rss_kib"],
                "status": "stopped" if state["stop_reason"] or loaded["paused"] else "pending",
                **FLAGS}

    def get(self, search_id):
        if not self.store.path.exists():
            return None
        with self.store._reader() as db:
            return self._summary(search_id, self._read(db, search_id))

    def pause(self, search_id, *, paused=True):
        if type(paused) is not bool:
            raise ValueError("Invalid pause value")
        with self.store._writer() as db:
            loaded = self._read(db, search_id)
            if loaded and not loaded.get("stale"):
                db.execute("UPDATE observed_jobs_v2 SET paused=? WHERE owner=? AND id=?",
                           (paused, self.store.owner_scope, search_id))
                loaded["paused"] = paused
            return self._summary(search_id, loaded)

    def step(self, search_id, expected_work, budget):
        if not integer(expected_work, 0, MAX_WORK) or not integer(budget, 1, MAX_STEP):
            raise ValueError("Invalid observed step budget")
        deadline = time.monotonic() + STEP_SECONDS
        # Serialize a bounded step across processes. The transaction rolls
        # back both the cursor and receipts on write failure or interruption.
        loaded = None
        for offset in range(budget):
            with self.store._writer() as db:
                if loaded is None:
                    loaded = self._read(db, search_id)
                if not loaded or loaded.get("stale"):
                    break
                search, state, plan = (loaded[k] for k in ("search", "state", "plan"))
                cursor, paused = db.execute(
                    "SELECT cursor,paused FROM observed_jobs_v2 WHERE owner=? AND id=?",
                    (self.store.owner_scope, search_id)).fetchone()
                if cursor != expected_work + offset or paused or state["stop_reason"]:
                    # Another request may have advanced or paused this job.
                    loaded = self._read(db, search_id)
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                item = state["frontier"][-1]
                position = state["work"]
                work_id = self._work_id(search_id, search, state)
                receipt, rss = replay(self.sandbox, search.context, plan,
                                      search.scenarios[item["index"]], item, remaining)
                search.advance(state, receipt)
                state["peak_rss_kib"] = max(state["peak_rss_kib"], rss)
                db.execute("INSERT INTO observed_work_v2 VALUES (?,?,?,?,?,?,?)",
                           (self.store.owner_scope, search_id, position, work_id, canonical(receipt),
                            digest([work_id, receipt, rss]), rss))
                db.execute("UPDATE observed_jobs_v2 SET cursor=? WHERE owner=? AND id=?",
                           (state["work"], self.store.owner_scope, search_id))
        return self._summary(search_id, loaded)
