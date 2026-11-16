"""Tests for Phase D-02: Compute slot reservation and LOCK holding minimization."""
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pvpoke_web as web
import pvpoke_meta_variants as meta_variants
from pvpoke_http_security import BoundedHTTPServer


class ComputeReservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)
        web.COMPUTE_OWNER = None
        web.BATTLE_RUNNING = False
        web.STATUS['state'] = 'idle'

    def tearDown(self):
        web.COMPUTE_OWNER = None
        web.BATTLE_RUNNING = False
        web.STATUS['state'] = 'idle'
        self.tmp.cleanup()

    def test_d02_01_try_reserve_compute_and_release(self):
        # Successful reservation
        token = web.try_reserve_compute('test_kind')
        self.assertIsNotNone(token)
        self.assertTrue(web._compute_busy_locked())
        self.assertEqual(web.COMPUTE_OWNER['kind'], 'test_kind')

        # Concurrent attempt rejected
        second = web.try_reserve_compute('second_kind')
        self.assertIsNone(second)

        # Release with wrong token fails
        self.assertFalse(web.release_compute('wrong_token'))
        self.assertTrue(web._compute_busy_locked())

        # Release with correct token succeeds
        self.assertTrue(web.release_compute(token))
        self.assertFalse(web._compute_busy_locked())
        self.assertIsNone(web.COMPUTE_OWNER)

    def test_d02_02_battle_reservation_sets_and_clears_flag(self):
        token = web.try_reserve_compute('battle')
        self.assertIsNotNone(token)
        self.assertTrue(web.BATTLE_RUNNING)

        web.release_compute(token)
        self.assertFalse(web.BATTLE_RUNNING)
        self.assertIsNone(web.COMPUTE_OWNER)

    def test_d02_03_evaluate_runs_simulation_outside_lock(self):
        lock = threading.RLock()
        status = {'state': 'idle'}
        acquired = []
        released = []

        def acquire():
            acquired.append(time.monotonic())
            return 'token_eval'

        def release(tok):
            released.append(tok)

        fake_client = MagicMock()
        def simulate_with_lock_check(*args, **kwargs):
            self.assertFalse(lock._is_owned())
            return {'files': ['f1']}
        fake_client.simulate.side_effect = simulate_with_lock_check

        job = {
            'id': 'test_job',
            'target_id': 't1',
            'created_at': time.monotonic(),
            'attempts': 0,
            'source_csv': 'quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n',
        }
        species = {
            'quagsire': {
                'fastMoves': ['MUD_SHOT', 'WATER_GUN'],
                'chargedMoves': ['AQUA_TAIL', 'STONE_EDGE', 'SLUDGE_BOMB', 'MUD_BOMB'],
            }
        }
        cpms = {50: 0.84029999}
        checkpoint = MagicMock()

        # Mock engine.DATA / 'gamemaster.json' moves
        moves_data = {
            'moves': [
                {'moveId': 'MUD_SHOT', 'type': 'ground', 'power': 3, 'energyGain': 9, 'cooldown': 2},
                {'moveId': 'WATER_GUN', 'type': 'water', 'power': 6, 'energyGain': 3, 'cooldown': 1},
                {'moveId': 'AQUA_TAIL', 'type': 'water', 'power': 50, 'energy': 35},
                {'moveId': 'STONE_EDGE', 'type': 'rock', 'power': 100, 'energy': 55},
                {'moveId': 'SLUDGE_BOMB', 'type': 'poison', 'power': 80, 'energy': 50},
                {'moveId': 'MUD_BOMB', 'type': 'ground', 'power': 55, 'energy': 40},
            ]
        }
        with patch.object(Path, 'read_text', return_value=json.dumps(moves_data)):
            with patch('pvpoke_meta_variants.shortlist', return_value=[('quagsire', 'WATER_GUN', 'AQUA_TAIL', 'STONE_EDGE')]):
                with patch('pvpoke_meta_variants.prepared_rows', return_value=[['dummy']]):
                    with patch('pvpoke_meta_variants.choose_variants', return_value=[]):
                        meta_variants.evaluate(
                            job, fake_client, species, cpms, lock, status, checkpoint,
                            acquire_compute=acquire, release_compute=release
                        )

        self.assertGreaterEqual(len(acquired), 1)
        self.assertIn('token_eval', released)
        self.assertTrue(fake_client.simulate.called)

    def test_d02_04_schedule_queue_capacity(self):
        # Clear any existing in-memory state
        with meta_variants._guard:
            meta_variants._queued.clear()
            while not meta_variants._queue.empty():
                try:
                    meta_variants._queue.get_nowait()
                except Exception:
                    break

        # Set fake runtime
        meta_variants._runtime = (self.work, threading.RLock(), {}, lambda: False, None, None)

        fake_entry = {'id': 'p', 'sha256': '0'*64, 'csv': 'quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n'}
        with patch.object(meta_variants.presets, 'resolve', return_value=fake_entry):
            with patch.object(Path, 'is_file', return_value=True):
                with patch.object(Path, 'read_bytes', return_value=b'{}'):
                    # Fill queue up to MAX_PENDING_JOBS (32)
                    for i in range(meta_variants.MAX_PENDING_JOBS):
                        res = meta_variants.schedule(self.work, f'preset_{i}')
                        self.assertEqual(res['state'], 'queued')

                    # 33rd job should be rejected with deferred
                    res = meta_variants.schedule(self.work, 'overflow_preset')
                    self.assertEqual(res['state'], 'deferred')

    def test_d02_05_job_retry_limit(self):
        # Verify MAX_JOB_ATTEMPTS is 3 and exceeding attempts marks failed
        job_dir = meta_variants.directory(self.work)
        job_dir.mkdir(parents=True, exist_ok=True)
        job_path = job_dir / 'expired_job.json'
        job_path.write_text(json.dumps({
            'id': 'expired_job',
            'state': 'running',
            'minimal_policy': 1,
            'attempts': 3,
        }))

        # Running start() with attempts >= 3 should mark job failed
        lock = threading.RLock()
        status = {'state': 'idle'}
        meta_variants._runtime = None
        with patch.object(Path, 'is_file', return_value=True):
            meta_variants.start(self.work, lock, status)

        self.assertTrue(job_path.exists())
        saved = json.loads(job_path.read_text())
        self.assertEqual(saved['state'], 'failed')
        self.assertIn('上限', saved['error'])

    def test_d02_06_bounded_http_server_configuration(self):
        server = BoundedHTTPServer(('127.0.0.1', 0), web.Handler, max_workers=24, socket_timeout=15, request_timeout=90)
        try:
            self.assertEqual(server._slots._value, 24)
            self.assertEqual(server.socket_timeout, 15)
            self.assertEqual(server.request_timeout, 90)
        finally:
            server.server_close()


if __name__ == '__main__':
    unittest.main()
