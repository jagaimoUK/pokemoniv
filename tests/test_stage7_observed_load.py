"""Low-amplitude Stage-7 synthetic measurement of the saved-policy read API."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import resource
import sqlite3
import statistics
import time
import unittest

from pvpoke_observed_evidence import compare_observed, MAX_COMPARE_RECEIPTS
from test_missing_observed_evidence import MissingObservedEvidenceTests


def ms_percentile(values, percentile):
    series = sorted(values)
    index = max(0, min(len(series) - 1, (len(series) * percentile + 99) // 100 - 1))
    return round(series[index] * 1000, 3)


class Stage7ObservedLoad(unittest.TestCase):
    def setUp(self):
        # Reuse the existing, legal, isolated synthetic battle setup.
        self.fixture = MissingObservedEvidenceTests(
            "test_link_matches_only_exact_build_and_starting_conditions_without_writes")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.evaluation = self.fixture.evaluation()["evaluation_id"]
        self.search_id = self.fixture.observed()

    def test_repeated_requests_four_workers_and_saved_state(self):
        path = self.fixture.store.path
        expected = hashlib.sha256(path.read_bytes()).hexdigest()
        def request(_):
            start = time.perf_counter()
            result = compare_observed(self.fixture.service, self.evaluation, [self.search_id])
            assert result["new_battles"] == 0
            assert result["standard_assessment_unchanged"] is True
            return time.perf_counter() - start
        begin_cpu = time.process_time()
        begin_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        warm = [request(0) for _ in range(5)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            concurrent = list(pool.map(request, range(16)))
        elapsed_cpu = round(time.process_time() - begin_cpu, 4)
        peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected)
        self.assertEqual(len(concurrent), 16)
        print("STAGE7_OBSERVED_RESULT " + json.dumps({
            "type": "full_API_in_process", "replay_cursor": 0,
            "warm_p50_ms": ms_percentile(warm, 50),
            "warm_p95_ms": ms_percentile(warm, 95),
            "concurrent_p50_ms": ms_percentile(concurrent, 50),
            "concurrent_p95_ms": ms_percentile(concurrent, 95),
            "concurrent_workers": 4, "total_calls": 21,
            "process_cpu_seconds": elapsed_cpu,
            "peak_rss_kib": peak_rss,
            "rss_growth_kib_upper_bound": max(0, peak_rss - begin_rss),
            "db_bytes": path.stat().st_size,
            "native_calls": 0}, sort_keys=True))

    def test_1024_receipt_preflight_and_one_over_limit(self):
        # Synthetic receipt rows are intentionally NOT replay-valid.
        # They are used only to benchmark SQL size checks, not to claim
        # that a 1024-receipt native replay or HTTP endpoint was tested.
        store = self.fixture.store
        record = '{"status":"unknown","reason":"wall_limit"}'
        with store._writer() as db:
            for index in range(MAX_COMPARE_RECEIPTS):
                db.execute(
                    "INSERT INTO observed_work_v2 VALUES (?,?,?,?,?,?,?)",
                    (store.owner_scope, self.search_id, index, "x"*64, record, "y"*64, 0))
            db.execute("UPDATE observed_jobs_v2 SET cursor=? WHERE owner=? AND id=?",
                       (MAX_COMPARE_RECEIPTS, store.owner_scope, self.search_id))
        values = []
        for _ in range(16):
            with store._reader() as db:
                t0 = time.perf_counter()
                count, nbytes = db.execute(
                    "SELECT COUNT(*), COALESCE(SUM(LENGTH(receipt)),0) "
                    "FROM observed_work_v2 WHERE owner=? AND id=?",
                    (store.owner_scope, self.search_id)).fetchone()
                values.append(time.perf_counter() - t0)
                self.assertEqual(count, MAX_COMPARE_RECEIPTS)
                self.assertEqual(nbytes, MAX_COMPARE_RECEIPTS * len(record))
        # The upper bound must fail before the expensive replay parse.
        with store._writer() as db:
            db.execute("INSERT INTO observed_work_v2 VALUES (?,?,?,?,?,?,?)",
                       (store.owner_scope, self.search_id, MAX_COMPARE_RECEIPTS,
                        "x"*64, record, "y"*64, 0))
            db.execute("UPDATE observed_jobs_v2 SET cursor=? WHERE owner=? AND id=?",
                       (MAX_COMPARE_RECEIPTS + 1, store.owner_scope, self.search_id))
        with self.assertRaisesRegex(ValueError, "too large"):
            compare_observed(self.fixture.service, self.evaluation, [self.search_id])
        self.assertIsNotNone(store.path)
        print("STAGE7_OBSERVED_RESULT " + json.dumps({
            "type": "SQL_preflight_only_not_validated_replay",
            "receipt_count": count, "receipt_bytes": nbytes,
            "p50_ms": ms_percentile(values, 50),
            "p95_ms": ms_percentile(values, 95),
            "db_bytes": store.path.stat().st_size, "over_limit_rejected": True},
            sort_keys=True))


if __name__ == "__main__":
    unittest.main()
