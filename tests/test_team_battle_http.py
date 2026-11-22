"""Exercise saved-party practice sessions through both HTTP servers."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from copy import deepcopy
import http.client
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import tempfile
from threading import Barrier, Event, Thread
import unittest
from unittest.mock import patch

from test_battle_api import gateway, web
from test_battle_service import FIXTURES, ROWS
from test_rl_team_env import action_for
from pvpoke_app_access import AppAccess, BrowserLogin
from pvpoke_auth_store import CredentialStore
from pvpoke_http_security import RateBudget
from pvpoke_rl_step_client import NativeStepError
import pvpoke_team_battle as battle


class TeamBattleHTTPTests(unittest.TestCase):
    def setUp(self):
        self.work = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.master = self.work / "gamemaster.json"
        self.gm = json.loads((FIXTURES / "strategy_gamemaster.json").read_bytes())
        self.master.write_text(json.dumps(self.gm))
        pokemon_js = Path("vendor/pvpoke/src/js/pokemon/Pokemon.js").read_text()
        self.cpms = [float(x) for x in re.search(r"var cpms = \[([^\]]+)\]", pokemon_js)[1].split(",")]
        self.species = {row["speciesId"]: row for row in self.gm["pokemon"]}
        self.catalog = {sid: {"fastMoves": row["fastMoves"], "chargedMoves": web.engine.charged_move_pool(row)}
                        for sid, row in self.species.items()}
        self.store = web.PartyBuilder(self.work)
        self.rows = [{**row, "level_override": row["level"]} for row in ROWS]
        for row in self.rows:
            row.pop("level")
            row.pop("cp")
        self.enemy = list(reversed(deepcopy(self.rows)))
        self.party = self.store.save_party({
            "name": "Practice", "members": self.rows, "opponents": self.enemy,
        })
        self.sessions = battle.BattleSessions()
        self.battles = []
        local = self.server(web.Handler)
        self.gateway = self.server(gateway.Handler)
        self.root = {"Authorization": "Bearer " + gateway.API_KEY}
        self.browser_login = BrowserLogin(gateway.API_KEY, store=CredentialStore(self.work / "auth.sqlite3"))

        patches = self.enterContext(ExitStack())
        patches.enter_context(patch.dict(os.environ, {"PVP_TEAM_BATTLE_ENABLED": "1"}))
        patches.enter_context(patch.object(web, "PARTY", self.store))
        patches.enter_context(patch.object(web, "TEAM_BATTLES", self.sessions))
        patches.enter_context(patch.object(web, "CATALOG", {"ready": True, "species": self.catalog}))
        patches.enter_context(patch.object(web.engine, "DATA", self.work))
        patches.enter_context(patch.object(web.engine, "game_data", return_value=(self.gm, self.cpms, self.species)))
        patches.enter_context(patch.object(gateway.backend, "BASE", "http://127.0.0.1:%d" % local.server_port))
        patches.enter_context(patch.object(gateway, "RATE_BUDGET", RateBudget()))
        patches.enter_context(patch.object(gateway, "BROWSER_LOGIN", self.browser_login))
        patches.enter_context(patch.object(gateway, "APP_ACCESS", AppAccess()))
        patches.enter_context(patch.object(battle.secrets.SystemRandom, "sample", return_value=[2, 3, 5]))
        patches.enter_context(patch.object(battle.secrets, "randbits", return_value=12))
        self.addCleanup(self.close_battles)

    def server(self, handler):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()

        def stop():
            server.shutdown()
            server.server_close()
            thread.join()

        self.addCleanup(stop)
        return server

    def request(self, operation, payload, headers=None):
        connection = http.client.HTTPConnection(*self.gateway.server_address, timeout=20)
        try:
            connection.request("POST", battle.APP_PATH + operation, json.dumps(payload),
                               {"Content-Type": "application/json", **(self.root if headers is None else headers)})
            response = connection.getresponse()
            body = response.read()
            self.assertEqual(response.getheader("Cache-Control"), "no-store")
            return response.status, json.loads(body) if body else {}
        finally:
            connection.close()

    def start(self, headers=None, **extra):
        code, state = self.request("start", {"party_id": self.party["id"], **extra}, headers)
        self.assertEqual(code, 200, state)
        self.battles.append((state["battle_id"], headers))
        return state

    def close_battles(self):
        for battle_id, headers in self.battles:
            self.request("close", {"battle_id": battle_id}, headers)

    @staticmethod
    def reference(state):
        return {"battle_id": state["battle_id"]}

    def step_payload(self, state, action):
        return {**self.reference(state), "revision": state["revision"], "action": action}

    def step(self, state, action):
        code, next_state = self.request("step", self.step_payload(state, action))
        self.assertEqual(code, 200, next_state)
        return next_state

    def test_practice_page_and_navigation_follow_the_api_flag(self):
        def get(path):
            connection = http.client.HTTPConnection(*self.gateway.server_address, timeout=5)
            try:
                connection.request("GET", path)
                response = connection.getresponse()
                return response.status, response.getheader("Content-Security-Policy"), response.read()
            finally:
                connection.close()

        status, csp, document = get(battle.PAGE_PATH)
        self.assertEqual(status, 200)
        self.assertIn("script-src 'sha256-", csp)
        self.assertIn(b'id="select-three"', document)
        self.assertIn(b'href="/app/team-battle"', get("/app/party")[2])
        with patch.dict(os.environ, {"PVP_TEAM_BATTLE_ENABLED": "0"}):
            self.assertEqual(get(battle.PAGE_PATH)[0], 404)
            self.assertNotIn(b'href="/app/team-battle"', get("/app/party")[2])

    def test_saved_party_to_native_ko_without_private_fields_or_writes(self):
        before = self.store.path.read_bytes()
        state = self.start()
        view = state["observation"]
        self.assertEqual(state["status"], "select_three")
        self.assertEqual(len(view["legal_actions"]), 60)
        self.assertFalse(view["opponent_selected_three_known"])
        for row, raw in zip(view["own_six"], ROWS, strict=True):
            self.assertEqual({key: row[key] for key in raw}, raw)
        self.assertEqual([row["species"] for row in view["opponent_public_six"]],
                         [row["species"] for row in self.enemy])
        for row in view["opponent_public_six"]:
            self.assertEqual(set(row), {"species", "known_moves", "roster_clause_id"})
            self.assertEqual(row["known_moves"], [])
        self.assertEqual(self.request("step", self.step_payload(state, "0,1,2|4"))[0], 422)
        self.assertEqual(self.request("state", self.reference(state)), (200, state))

        first = state
        state = self.step(state, "0,1,4|4")
        view = state["observation"]
        self.assertEqual(view["own"]["team"][0]["species"], ROWS[4]["species"])
        enemy = view["opponent"]
        self.assertEqual(enemy["active_species"], self.enemy[2]["species"])
        self.assertEqual(set(enemy), {"active_species", "shields", "revealed"})
        self.assertEqual(len(enemy["revealed"]), 1)
        self.assertEqual(set(enemy["revealed"][0]), {"species", "fainted", "hp_bucket_5pct", "seen_moves"})
        self.assertEqual(self.request("step", self.step_payload(first, "0,1,4|4"))[0], 409)
        for _ in range(500):
            if state["status"] != "battle":
                break
            state = self.step(state, action_for(state["observation"]))
        self.assertEqual(state["status"], "terminated", state)
        self.assertIn(state["result"]["outcome"], battle.OUTCOME_REWARD)
        self.assertEqual(set(state["result"]), {"outcome", "turns", "elapsed_ms"})
        self.assertIsNone(state["observation"])
        self.assertEqual(self.request("state", self.reference(state)), (200, state))
        self.assertEqual(self.request("step", self.step_payload(state, "wait"))[0], 409)
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_adapter_handles_default_ivs_and_distinct_species_clause(self):
        own = deepcopy(self.rows)
        own[0].update(atk=None, hp=None, **{"def": None})
        data = {"catalog": self.catalog, "species": self.species, "cpms": self.cpms, "engine": web.engine}
        roster = battle.prepare_roster(own, **data)
        self.assertEqual([roster[0][key] for key in ("atk", "def", "hp")],
                         self.species[own[0]["species"]]["defaultIVs"]["cp1500"][1:])
        self.assertIsNone(own[0]["atk"])
        own[0]["atk"] = 1
        with self.assertRaises(ValueError):
            battle.prepare_roster(own, **data)
        own[0] = dict(self.rows[0], level_override=str(self.rows[0]["level_override"]))
        self.assertEqual(battle.prepare_roster(own, **data)[0]["cp"], ROWS[0]["cp"])
        own[0] = dict(self.rows[0], level_override=True)
        with self.assertRaises(ValueError):
            battle.prepare_roster(own, **data)
        own[0] = dict(self.rows[0])
        sid, other = (row["species"] for row in own[:2])
        self.species[other] = dict(self.species[other], dex=self.species[sid]["dex"])
        with self.assertRaisesRegex(ValueError, "Duplicate roster clause"):
            battle.prepare_roster(own, **data)

    def test_gateway_auth_origin_scope_and_session_isolation(self):
        party_id = {"party_id": self.party["id"]}
        for operation in battle.OPERATIONS:
            self.assertEqual(self.request(operation, {}, {})[0], 401)
        self.assertEqual(self.request("start", party_id, {**self.root, "Origin": "https://unrelated.example"})[0], 403)
        self.assertEqual(self.request("start", {**party_id, "seed": 0})[0], 400)
        with patch.dict(os.environ, {"PVP_TEAM_BATTLE_ENABLED": "0"}):
            self.assertEqual(self.request("start", party_id)[0], 503)
        cookie_name = self.browser_login.COOKIE_NAME

        def cookie_headers():
            value = SimpleCookie(self.browser_login.issue(secure=False))[cookie_name].value
            return {"Cookie": f"{cookie_name}={value}"}

        first, second = cookie_headers(), cookie_headers()
        other_party = self.store.save_party({"name": "Opponent", "members": self.rows})
        state = self.start(first, opponent_party_id=other_party["id"])
        reference = self.reference(state)
        self.assertEqual(state["observation"]["opponent_public_six"][0]["species"], ROWS[0]["species"])
        scope = self.sessions._sessions[state["battle_id"]].scope
        forged_headers = {**second, battle.SCOPE_HEADER: scope}
        self.assertEqual(self.request("state", reference, forged_headers)[0], 404)
        self.assertEqual(self.request("step", self.step_payload(state, "0,1,2|0"), forged_headers)[0], 404)
        self.assertEqual(self.request("close", reference, forged_headers)[0], 404)
        self.assertEqual(self.request("state", reference, self.root)[0], 404)
        self.assertEqual(self.request("state", reference, {**first, "Cookie": first["Cookie"] + "; test=one"}), (200, state))
        other = self.start(second)
        self.assertNotEqual(other["battle_id"], state["battle_id"])
        self.assertEqual(self.request("state", reference, first), (200, state))
        self.assertEqual(self.request("start", party_id)[0], 503)
        self.assertEqual(self.request("close", reference, first)[0], 200)
        self.assertEqual(self.request("state", reference, first)[0], 404)
        self.start()

    def test_concurrent_same_revision_only_applies_once(self):
        state = self.start()
        pending = self.step_payload(state, "0,1,4|0")
        barrier = Barrier(2)

        def send():
            barrier.wait(timeout=5)
            return self.request("step", pending)

        with ThreadPoolExecutor(max_workers=2) as executor:
            first, second = executor.submit(send), executor.submit(send)
            responses = [first.result(), second.result()]
        self.assertEqual(sorted(status for status, _ in responses), [200, 409])
        code, current = self.request("state", self.reference(state))
        self.assertEqual(code, 200)
        self.assertEqual(current["revision"], 1)
        self.assertEqual(current, next(body for status, body in responses if status == 200))

    def test_timeout_and_unsupported_stop_without_a_win_or_loss(self):
        original_reset = battle.SixToThreeEnvironment.reset

        def reset_short(environment, *, seed):
            return original_reset(environment, seed=seed, horizon=1)

        with patch.object(battle.SixToThreeEnvironment, "reset", reset_short):
            start = self.start()
        state = self.step(self.step(start, "0,1,4|0"), "wait")
        self.assertEqual((state["status"], state["result"]["outcome"]), ("truncated", "timeout"))
        self.assertIsNone(state["observation"])
        self.assertNotIn("reward", state["result"])

        self.species["fearow"]["formChange"] = {"trigger": "activate_charged", "alternativeFormId": "fearow"}
        self.master.write_text(json.dumps(self.gm))
        state = self.step(self.start(), "0,1,3|0")
        self.assertEqual((state["status"], state["result"]["outcome"]), ("truncated", "unsupported"))
        self.assertIsNone(state["observation"])
        self.assertNotIn("reward", state["result"])

    def test_idle_expiry_releases_the_session_without_another_request(self):
        sessions = battle.BattleSessions(capacity=1, idle_seconds=0.2)
        removed = Event()
        remove = sessions._remove

        def close_expired(*args):
            remove(*args)
            removed.set()

        with patch.object(web, "TEAM_BATTLES", sessions), patch.object(sessions, "_remove", close_expired):
            state = self.start()
            self.assertTrue(removed.wait(5), "idle session was not released")
            self.assertEqual(self.request("state", self.reference(state))[0], 404)
            self.assertEqual(self.request("close", self.reference(self.start()))[0], 200)

    def test_worker_failure_invalidates_the_revision_without_claiming_timeout(self):
        state = self.start()
        with patch.object(battle.SixToThreeEnvironment, "step", side_effect=NativeStepError("private path")):
            code, error = self.request("step", self.step_payload(state, "0,1,2|0"))
        self.assertEqual(code, 503)
        self.assertNotIn("private path", json.dumps(error))
        code, failed = self.request("state", self.reference(state))
        self.assertEqual((code, failed["status"], failed["revision"]), (200, "unavailable", 1))
        self.assertIsNone(failed["result"])
        self.assertEqual(self.request("step", self.step_payload(state, "0,1,2|0"))[0], 409)
