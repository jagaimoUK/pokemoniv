"""Lossless transport and independently checked all-candidate downside facts."""
from copy import deepcopy
import io
import json
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from pvpoke_decision_digest import decision_digest, decision_digest_v2
from pvpoke_selection_digest import build_selection_digest
from pvpoke_selection_matrix import load_selection_matrix, SelectionMatrix, SHIELDS
from pvpoke_selection_tradeoffs import candidate_tradeoffs
from pvpoke_iv_workflow import IVWorkflow
from test_selection_digest import sample_zip
from test_iv_workflow import CANDIDATE, IVS, HASH, FakeBackend, fixture_zip


class DecisionV2Tests(unittest.TestCase):
    def test_v2_roundtrip_preserves_all_v1_facts_and_input(self):
        with ZipFile(sample_zip(n=12, opponents=87)) as archive:
            digest = build_selection_digest(archive, focus_opponents=['Corsola'],
                                            include_tradeoffs=True)
        before = deepcopy(digest)
        encoded = decision_digest_v2(digest)
        names = encoded['opponents']
        restored = deepcopy(encoded)
        restored['format'] = 'decision-v1'
        restored['example_columns'][0] = 'opponent'
        for examples in restored['examples_by_iv'].values():
            for row in examples:
                row[0] = names[row[0]]
        restored['crossover_columns'][1] = 'opponent'
        restored['crossover_columns'][3:] = ['above500_ivs', 'best', 'second', 'worst']
        for row in restored['crossover_rows']:
            row[1] = names[row[1]]
            row[3] = [encoded['candidate_ivs'][i] for i in row[3]]
            for col in (4, 5, 6):
                if row[col] is not None:
                    row[col][0] = encoded['candidate_ivs'][row[col][0]]
        restored['focus_matchups'] = [
            {'opponent': names[row['opponent_index']], 'by_iv': row['by_iv']}
            for row in restored['focus_matchups']
        ]
        for key in ('opponents', 'opponent_index_base', 'candidate_ivs', 'tradeoff_columns',
                    'tradeoff_example_columns', 'tradeoff_rows', 'tradeoff_scope'):
            restored.pop(key)
        legacy = decision_digest({k: v for k, v in digest.items()
                                  if k != 'candidate_tradeoffs'})
        self.assertEqual(restored, legacy)
        self.assertEqual(digest, before)
        for iv, row in zip(encoded['candidate_ivs'], encoded['tradeoff_rows']):
            item = dict(zip(encoded['tradeoff_columns'], row))
            item['ivs'] = iv
            event = item['example']
            if event:
                event = dict(zip(encoded['tradeoff_example_columns'], event))
                event['opponent'] = names[event.pop('opponent_index')]
                item['example'] = event
            self.assertIn(item, digest['candidate_tradeoffs'])

    def test_tradeoff_counts_match_brute_force_all_candidates(self):
        with ZipFile(sample_zip(n=12, opponents=87)) as archive:
            data = load_selection_matrix(archive, 'default')
        actual = candidate_tradeoffs(data, data.candidates, ['Corsola'])
        self.assertEqual(len(actual), 12)
        for row in actual:
            iv = row['ivs']
            lower = lost = 0
            for shield in SHIELDS:
                for pos in range(len(data.opponents)):
                    best = max(data.ratings[shield][other][pos] for other in data.candidates)
                    rating = data.ratings[shield][iv][pos]
                    lower += int(rating < best)
                    lost += int(rating <= 500 < best)
            self.assertEqual((row['lower_than_best'], row['lost_gt500']), (lower, lost))
            event = row['example']
            if event:
                pos = data.opponents.index(event['opponent'])
                self.assertEqual(event['rating'], data.ratings[event['shield']][iv][pos])
                self.assertEqual(event['best_rating'],
                                 data.ratings[event['shield']][event['best_iv']][pos])

    def test_equal_ratings_single_candidate_and_500_boundary(self):
        for n in (1, 2):
            ivs = ['0/0/0', '1/1/1'][:n]
            data = SelectionMatrix(['Test'], ivs,
                {s: {iv: [500] for iv in ivs} for s in SHIELDS}, {})
            for row in candidate_tradeoffs(data, ivs, []):
                self.assertEqual(row['lower_than_best'], 0)
                self.assertEqual(row['lost_gt500'], 0)
                self.assertIsNone(row['example'])
        data.ratings['s0']['1/1/1'] = [501]
        del data.ordered_scores
        row = candidate_tradeoffs(data, ivs, [])[0]
        self.assertEqual(row['lost_gt500'], 1)
        self.assertEqual(row['example']['gap'], 1)

    def test_focus_example_can_differ_from_largest_global_gap(self):
        ivs = ['0/0/0', '1/1/1']
        data = SelectionMatrix(['Important', 'Other'], ivs,
            {s: {ivs[0]: [490, 10], ivs[1]: [510, 900]} for s in SHIELDS}, {})
        row = candidate_tradeoffs(data, ivs, ['Important'])[0]
        self.assertEqual(row['example']['opponent'], 'Important')
        self.assertEqual(row['example']['shield'], 'i0y1')
        self.assertEqual(row['lost_gt500'], 12)

    def test_explicit_v1_remains_available(self):
        backend = FakeBackend()
        workflow = IVWorkflow(backend)
        ref = workflow.run(CANDIDATE, IVS, wait_seconds=0,
                           report_format='decision-v1')['run_ref']
        backend.state = 'done'
        report = workflow.result(ref)['reports']['default']
        self.assertEqual(report['format'], 'decision-v1')
        self.assertNotIn('tradeoff_rows', report)

    def test_uppercase_hash_is_verified_through_completion(self):
        backend = FakeBackend()
        backend.sha = HASH.upper()
        workflow = IVWorkflow(backend)
        ref = workflow.run(CANDIDATE, IVS, wait_seconds=0,
                           expected_meta_sha256=HASH.upper())['run_ref']
        backend.state = 'done'
        self.assertTrue(workflow.result(ref)['meta_verified_against_project'])

    def test_matrices_must_match_ticket_even_if_summary_matches(self):
        stream = io.BytesIO()
        with ZipFile(fixture_zip()) as src, ZipFile(stream, 'w') as dst:
            for name in src.namelist():
                content = src.read(name)
                if name.startswith('default_'):
                    content = content.replace(b'2/15/13', b'1/15/13')
                dst.writestr(name, content)
        stream.seek(0)
        backend = FakeBackend()
        workflow = IVWorkflow(backend)
        ref = workflow.run(CANDIDATE, IVS, wait_seconds=0)['run_ref']
        backend.state = 'done'
        with patch.object(backend, '_zip', return_value=ZipFile(stream)):
            with self.assertRaisesRegex(ValueError, 'Matrix candidate'):
                workflow.result(ref)


if __name__ == '__main__':
    unittest.main()
