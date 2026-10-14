"""Correctness checks for shared parsing, table encoding and bounded polling."""
import io
import csv
import json
import threading
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from pvpoke_selection_digest import build_selection_digest
from pvpoke_decision_digest import decision_digest
from pvpoke_iv_workflow import IVWorkflow
from test_iv_workflow import CANDIDATE, IVS, FakeBackend
from test_selection_digest import sample_zip


class PipelineTests(unittest.TestCase):
    def test_each_condition_is_read_once(self):
        with ZipFile(sample_zip(n=12, opponents=87)) as archive:
            with patch.object(archive, "read", wraps=archive.read) as read:
                result = build_selection_digest(archive)
            csv_reads = [c.args[0] for c in read.call_args_list if c.args[0].endswith('.csv')]
        self.assertEqual(len(csv_reads), 6)
        self.assertEqual(len(set(csv_reads)), 6)
        self.assertEqual(result['total_ratings_checked'], 12 * 87 * 6)

    def test_decision_encoding_preserves_every_signal_and_example(self):
        with ZipFile(sample_zip(n=12, opponents=87)) as archive:
            full = build_selection_digest(archive, focus_opponents=['Corsola'])
        compact = decision_digest(full)
        decoded = []
        for row in compact['evidence_rows']:
            item = dict(zip(compact['evidence_columns'], row))
            item['examples'] = [dict(zip(compact['example_columns'], example))
                                for example in compact['examples_by_iv'].get(item['ivs'], [])]
            decoded.append(item)
        self.assertEqual(decoded, full['candidate_evidence'])
        self.assertEqual(
            [dict(zip(compact['crossover_columns'], row))
             for row in compact['crossover_rows']], full['priority_crossovers'])
        self.assertEqual(compact['ranking_rows'], full['ranking_rows'])
        self.assertEqual(compact['dominated_by'], full['dominated_by'])
        self.assertEqual(compact['focus_matchups'], full['focus_matchups'])
        self.assertLess(len(json.dumps(compact)), len(json.dumps(full)))

    def test_poll_waits_until_done_without_starting_again(self):
        backend = FakeBackend()
        workflow = IVWorkflow(backend)
        started = workflow.run(CANDIDATE, IVS, wait_seconds=0)
        timer = threading.Timer(0.01, lambda: setattr(backend, 'state', 'done'))
        timer.start()
        try:
            result = workflow.result(started['run_ref'], wait_seconds=1)
        finally:
            timer.join()
        self.assertEqual(result['state'], 'done')
        self.assertEqual(backend.run_count, 1)
        self.assertEqual(result['reports']['default']['format'], 'decision-v2')

    def test_cached_result_is_isolated_and_identity_checked(self):
        backend = FakeBackend()
        workflow = IVWorkflow(backend)
        ref = workflow.run(CANDIDATE, IVS, wait_seconds=0)['run_ref']
        backend.state = 'done'
        with patch.object(backend, '_zip', wraps=backend._zip) as download:
            first = workflow.result(ref)
            first['reports'].clear()
            second = workflow.result(ref)
            self.assertEqual(download.call_count, 1)
        self.assertEqual(len(second['reports']), 1)
        backend.time = 'changed'
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            workflow.result(ref)

    def test_more_than_87_opponents_does_not_cap_internal_crossovers(self):
        stream = io.BytesIO()
        with ZipFile(stream, 'w') as archive:
            for shield in ('s0', 's1', 's2', 'i0y1', 'i0y2', 'i1y2'):
                table = io.StringIO()
                writer = csv.writer(table)
                writer.writerow(['candidate', *[f'Opponent_{i}' for i in range(100)],
                                 'rating_gt500','rating_lt500','rating_eq500','mean_rating'])
                writer.writerow(['Quagsire MS+AT/SE 0/11/12', *([510]*100),100,0,0,510])
                writer.writerow(['Quagsire MS+AT/SE 2/15/13', *([490]*100),0,100,0,490])
                archive.writestr(f'default_{shield}.csv', table.getvalue())
        stream.seek(0)
        with ZipFile(stream) as archive:
            result = build_selection_digest(archive, focus_opponents=['Opponent_99'])
        self.assertEqual(result['crossovers_total'], 600)
        self.assertEqual(result['focus_crossovers_total'], 6)
        self.assertEqual(result['candidate_evidence'][0]['unique_gt500'], 600)

    def test_explicit_compact_format_and_parameter_validation(self):
        backend = FakeBackend()
        workflow = IVWorkflow(backend)
        with self.assertRaisesRegex(ValueError, 'report_format'):
            workflow.run(CANDIDATE, IVS, report_format='unknown')
        self.assertEqual(backend.run_count, 0)
        ref = workflow.run(CANDIDATE, IVS, wait_seconds=0, report_format='compact')['run_ref']
        backend.state = 'done'
        self.assertIn('candidate_evidence', workflow.result(ref)['reports']['default'])
        with self.assertRaisesRegex(ValueError, 'wait_seconds'):
            workflow.result(ref, wait_seconds=21)


if __name__ == '__main__':
    unittest.main()
