"""Tests for TV-03 selection_pool differential workflow and /app-api/selection-diff endpoint."""
import csv
import http.client
import io
import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from zipfile import ZipFile

os.environ.setdefault("PVP_API_KEY", "test-" + "x" * 32)
import pvpoke_mcp_remote as gateway
from pvpoke_iv_workflow import IVWorkflow
from pvpoke_mega import resolve_battle_rules

SHIELDS = ("s0", "s1", "s2", "i0y1", "i0y2", "i1y2")
HASH = "b" * 64


def _build_zip(candidate: dict, ratings_by_iv: dict[tuple[int, int, int], dict[str, list[int]]]):
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", json.dumps({
            "batch_mode": "simple",
            "candidates": len(ratings_by_iv),
            "excluded": 0,
            "gamemaster_timestamp": "test",
            "matchup_cache": {"enabled": True, "hits": 6, "misses": 6},
        }))
        summary = io.StringIO()
        writer = csv.DictWriter(summary, fieldnames=[
            "species", "fast", "charged1", "charged2",
            "atk", "def", "hp", "opponent_iv_mode",
            "matchups", "mean_rating", "min_rating",
        ])
        writer.writeheader()
        for a, d, h in ratings_by_iv:
            writer.writerow({
                "species": candidate["species"],
                "fast": candidate["fast"],
                "charged1": candidate["charged1"],
                "charged2": candidate["charged2"],
                "atk": a, "def": d, "hp": h,
                "opponent_iv_mode": "default",
                "matchups": 12,
                "mean_rating": 500,
                "min_rating": 400,
            })
        for shield in SHIELDS:
            table = io.StringIO()
            rows = csv.writer(table)
            rows.writerow([
                "candidate",
                "Azumarill B+IB/PR 0/15/15",
                "Altaria DB+SA/MB 0/14/15",
                "rating_gt500", "rating_lt500", "rating_eq500", "mean_rating",
            ])
            for (a, d, h), shield_map in ratings_by_iv.items():
                r1, r2 = shield_map[shield]
                wins = int(r1 > 500) + int(r2 > 500)
                losses = int(r1 < 500) + int(r2 < 500)
                draws = int(r1 == 500) + int(r2 == 500)
                rows.writerow([
                    f"{candidate['species']} {a}/{d}/{h}",
                    r1, r2, wins, losses, draws, (r1 + r2) / 2,
                ])
            archive.writestr(f"default_{shield}.csv", table.getvalue())
        archive.writestr("ranking_summary.csv", summary.getvalue())
    output.seek(0)
    return ZipFile(output, "r")


class _FakePoolBackend:
    BridgeError = RuntimeError

    def __init__(self, ratings_by_iv: dict, pool_snapshots: dict | None = None, *, pool_error: Exception | None = None):
        self.state = "idle"
        self.time = "2026-11-28T05:00:00"
        self.run_count = 0
        self.start_calls = []
        self.pool_queries = []
        self.ratings_by_iv = ratings_by_iv
        self.pool_snapshots = pool_snapshots if pool_snapshots is not None else {}
        self.pool_error = pool_error
        self._last_candidate = None

    def meta_status(self):
        return {"sha256": HASH, "rows": 87}

    def candidate_name(self, species):
        return "Mega Sableye" if species == "sableye_mega" else species.title()

    def selection_pool(self, species_ids):
        self.pool_queries.append(list(species_ids))
        if self.pool_error is not None:
            raise self.pool_error
        return {
            "snapshots": {
                sid: self.pool_snapshots[sid]
                for sid in species_ids
                if sid in self.pool_snapshots
            }
        }

    def start24(self, candidate, ivs, batch_mode, **kwargs):
        self.run_count += 1
        self._last_candidate = dict(candidate)
        self.start_calls.append({"candidate": dict(candidate), "ivs": ivs, "batch_mode": batch_mode, **kwargs})
        self.state = "done"
        self.time = f"2026-11-28T05:00:{self.run_count:02}"
        return {
            "started": True,
            "preview": {
                "batch24": True,
                "batch_mode": batch_mode,
                "candidate_count": len([x for x in ivs.splitlines() if x.strip()]),
                "opponent_count": 2,
                "shield_cases": 6,
                "result_cache": {"reused": False},
            },
        }

    def status(self):
        return {
            "state": self.state,
            "started_at": self.time,
            "batch24": self.state != "idle",
            "message": "done",
        }

    def _zip(self):
        return _build_zip(self._last_candidate, self.ratings_by_iv)


class SelectionDiffPoolTests(unittest.TestCase):
    def test_resolve_battle_rules_accepts_great_mega_ruleset_and_super_max(self):
        resolved = resolve_battle_rules({"ruleset": "great_mega", "super_max_mode": "hypothesis_1_pl52"})
        self.assertEqual(resolved["league"], "great")
        self.assertEqual(resolved["cup_id"], "great_mega")
        self.assertEqual(resolved["cp_cap"], 1500)
        self.assertTrue(resolved["allow_cp_downscaling"])
        self.assertEqual(resolved["max_level"], 52.0)
        self.assertEqual(resolved["super_max_mode"], "hypothesis_1_pl52")
        self.assertTrue(resolved["rule_explicit"])

        resolved_pl53 = resolve_battle_rules({"ruleset": "great_mega", "super_max_mode": "hypothesis_2_pl53"})
        self.assertEqual(resolved_pl53["max_level"], 53.0)

    def test_tv03_diff_classifies_unique_win_equivalent_and_dominated_mega(self):
        # Saved pool has 1/14/14 and 2/15/13 for sableye_mega.
        # Incoming has:
        #   0/15/15 -> unique_win (beats opponent 2 in s0, where others lose; and dominates 2/15/13)
        #   3/14/14 -> equivalent_alternative to 1/14/14
        #   4/10/10 -> dominated by 1/14/14
        ratings = {
            (0, 15, 15): {s: [480 if s == "s1" else 520, 540 if s == "s0" else 480] for s in SHIELDS},
            (3, 14, 14): {s: [550 if s in ("s0", "s1") else 510, 450] for s in SHIELDS},
            (4, 10, 10): {s: [490, 440] for s in SHIELDS},
            (1, 14, 14): {s: [550 if s in ("s0", "s1") else 510, 450] for s in SHIELDS},
            (2, 15, 13): {s: [470 if s == "s1" else 510, 470] for s in SHIELDS},
        }
        pool = {
            "sableye_mega": {
                "revision": 7,
                "ivs": ["1/14/14", "2/15/13"],
                "links": [{"ivs": "1/14/14", "instance_id": "inst-1", "goal": "PL48 / メガLv3"}],
                "needs_reevaluation": False,
            }
        }
        backend = _FakePoolBackend(ratings, pool)
        wf = IVWorkflow(backend)

        result = wf.run_with_selection_pool(
            candidate={
                "species": "sableye_mega",
                "owned_species_id": "sableye",
                "fast": "SHADOW_CLAW",
                "charged1": "FOUL_PLAY",
                "charged2": "POWER_GEM",
                "mega_level": 3,
            },
            ivs="0,15,15\n3,14,14\n4,10,10",
            rules={"ruleset": "great_mega", "super_max_mode": "hypothesis_1_pl52"},
        )

        self.assertEqual(result["state"], "done")
        self.assertEqual(backend.pool_queries, [["sableye_mega"]])
        self.assertEqual(
            backend.start_calls[0]["ivs"],
            "0,15,15\n3,14,14\n4,10,10\n1,14,14\n2,15,13",
        )
        self.assertEqual(backend.start_calls[0]["rules"]["cup_id"], "great_mega")
        self.assertEqual(backend.start_calls[0]["rules"]["super_max_mode"], "hypothesis_1_pl52")

        diff = result["pool_diff"]
        self.assertEqual(diff["version"], "tv03-pool-diff-v1")
        self.assertEqual(diff["target_species_id"], "sableye_mega")
        self.assertEqual(diff["owned_species_id"], "sableye")
        self.assertTrue(diff["is_mega_form"])
        self.assertEqual(diff["saved_revision"], 7)
        self.assertEqual(diff["unique_win_incoming_ivs"], ["0/15/15"])
        self.assertEqual(diff["dominated_incoming_ivs"], ["4/10/10"])
        # 3/14/14 and 1/14/14 are equivalent; 3/14/14 is the lexicographical rep or equivalent
        by_iv = {item["ivs"]: item for item in diff["incoming_assessments"]}
        self.assertEqual(by_iv["0/15/15"]["classification"], "unique_win")
        self.assertEqual(by_iv["4/10/10"]["classification"], "dominated")
        self.assertIn(by_iv["3/14/14"]["classification"], ("recommended", "equivalent_alternative"))
        self.assertEqual(diff["newly_dominated_saved_ivs"], ["2/15/13"])
        self.assertTrue(diff["snapshot_update_recommended"])

    def test_async_polling_preserves_pool_diff_and_unavailable_pool_graceful(self):
        ratings = {
            (0, 15, 15): {s: [530, 520] for s in SHIELDS},
        }
        backend = _FakePoolBackend(ratings, pool_error=RuntimeError("missing disabled"))
        wf = IVWorkflow(backend)

        # Force async wait_seconds=0 while backend stays running initially
        orig_start24 = backend.start24
        def delayed_start24(*args, **kwargs):
            res = orig_start24(*args, **kwargs)
            backend.state = "running"
            return res
        backend.start24 = delayed_start24

        pending = wf.run_with_selection_pool(
            candidate={"species": "altaria_mega", "fast": "DRAGON_BREATH", "charged1": "SKY_ATTACK", "charged2": "MOONBLAST"},
            ivs="0,15,15",
            wait_seconds=0,
        )
        self.assertEqual(pending["state"], "running")

        backend.state = "done"
        completed = wf.result(pending["run_ref"], wait_seconds=1)
        self.assertEqual(completed["state"], "done")
        self.assertEqual(completed["pool_diff"]["pool_source"], "unavailable")
        self.assertEqual(completed["pool_diff"]["saved_pool_ivs"], [])
        self.assertEqual(completed["pool_diff"]["recommended_incoming_ivs"], ["0/15/15"])


class SelectionDiffHTTPTests(unittest.TestCase):
    def setUp(self):
        self.s = ThreadingHTTPServer(("127.0.0.1", 0), gateway.Handler)
        self.t = threading.Thread(target=self.s.serve_forever, daemon=True)
        self.t.start()

    def tearDown(self):
        self.s.shutdown()
        self.s.server_close()
        self.t.join()

    def request(self, path, payload, authorized=True):
        c = http.client.HTTPConnection(*self.s.server_address)
        h = {"Content-Type": "application/json"}
        if authorized:
            h["Authorization"] = "Bearer " + gateway.API_KEY
        c.request("POST", path, json.dumps(payload), h)
        r = c.getresponse()
        body = r.read().decode()
        c.close()
        return r.status, (json.loads(body) if body else None)

    def test_selection_diff_endpoint_auth_and_response(self):
        payload = {
            "candidate": {
                "species": "sableye_mega",
                "owned_species_id": "sableye",
                "fast": "SHADOW_CLAW",
                "charged1": "FOUL_PLAY",
                "charged2": "POWER_GEM",
                "mega_level": 3,
            },
            "ivs": "0,15,15",
            "rules": {"ruleset": "great_mega", "super_max_mode": "hypothesis_2_pl53"},
            "selection_pool": {
                "snapshots": {
                    "sableye_mega": {"revision": 3, "ivs": ["1/14/14"], "links": []},
                }
            },
        }
        status_unauth, _ = self.request("/app-api/selection-diff", payload, authorized=False)
        self.assertEqual(status_unauth, 401)

        ratings = {
            (0, 15, 15): {s: [540, 520] for s in SHIELDS},
            (1, 14, 14): {s: [520, 480] for s in SHIELDS},
        }
        fake_backend = _FakePoolBackend(ratings)
        fake_runner = IVWorkflow(fake_backend)
        with patch.object(gateway, "backend", fake_backend), patch.object(gateway, "IV_RUNNER", fake_runner):
            code, data = self.request("/app-api/selection-diff", payload, authorized=True)
        self.assertEqual(code, 200)
        self.assertEqual(data["state"], "done")
        self.assertEqual(data["rules"]["cup_id"], "great_mega")
        self.assertEqual(data["rules"]["super_max_mode"], "hypothesis_2_pl53")
        self.assertEqual(data["pool_diff"]["unique_win_incoming_ivs"], ["0/15/15"])
        self.assertEqual(data["pool_diff"]["newly_dominated_saved_ivs"], ["1/14/14"])
        self.assertFalse(data["meta_verified_against_project"])


if __name__ == "__main__":
    unittest.main()
