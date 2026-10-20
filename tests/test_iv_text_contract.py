"""Shared reader-export/import contract, without running battles or guessing moves."""
import csv
import os
from pathlib import Path
import unittest

from pvpoke_app_catalog import enrich_catalog
from pvpoke_app_input import parse_import

FIXTURE = Path(__file__).resolve().parents[1] / 'contracts' / 'iv-text-v1.tsv'


def sample_catalog():
    raw, payload = {}, {}
    # Moves are test-only inputs. They deliberately do not claim PvPoke defaults
    # for Carvanha, which has no default in the current production snapshot.
    for base, dex, name in [('carvanha', 318, 'Carvanha'), ('sharpedo', 319, 'Sharpedo'),
                            ('raticate', 20, 'Raticate'),
                            ('raticate_alolan', 20, 'Raticate (Alolan)')]:
        for suffix in ('', '_shadow'):
            sid = base + suffix
            raw[sid] = {'dex': dex}
            payload[sid] = {'name': name + (' (Shadow)' if suffix else ''),
                            'fastMoves': ['BITE'], 'chargedMoves': ['CRUNCH', 'POISON_FANG'],
                            'default_moves': {'fast': 'BITE', 'charged1': 'CRUNCH', 'charged2': 'POISON_FANG'}}
    for sid, name in [('minior_meteor', 'Minior (Meteor)'),
                      ('minior_core', 'Minior (Core)')]:
        raw[sid] = {'dex': 774}
        payload[sid] = {
            'name': name, 'fastMoves': ['ROLLOUT'],
            'chargedMoves': ['POWER_GEM', 'ACROBATICS'],
            'default_moves': {'fast': 'ROLLOUT', 'charged1': 'POWER_GEM',
                              'charged2': 'ACROBATICS'},
        }
    enrich_catalog(payload, raw)
    return {'species': payload}


class IvTextContractTests(unittest.TestCase):
    def setUp(self):
        self.catalog = sample_catalog()

    def test_shared_export_examples_and_legacy_input_produce_identical_jobs(self):
        with FIXTURE.open(encoding='utf-8', newline='') as stream:
            for case in csv.DictReader(stream, delimiter='\t'):
                ivs = case['ivs'].replace('|', '\n')
                for heading in (case['canonical_heading'], case['stored_targets'].replace('|', ' ')):
                    with self.subTest(case=case['case'], heading=heading):
                        text = '個体値厳選\n\n# ' + heading + '\n' + ivs
                        # In CI use the real JVM serializer's exported bytes.
                        export_dir = os.environ.get('IV_READER_EXPORT_DIR')
                        if export_dir and heading == case['canonical_heading']:
                            text = (Path(export_dir) / (case['case'] + '.txt')).read_text(encoding='utf-8')
                        result = parse_import(text, self.catalog)
                        self.assertEqual([j['candidate']['species'] for j in result['jobs']],
                                         case['species_ids'].split('|'))
                        self.assertTrue(all(j['ivs'] == ivs for j in result['jobs']))

    def test_all_shadow_spellings_are_bound_to_the_exact_form(self):
        for sid, entry in self.catalog['species'].items():
            if not sid.endswith('_shadow'):
                continue
            for alias in entry['aliases']:
                with self.subTest(sid=sid, alias=alias):
                    result = parse_import('# ' + alias + '\n1,2,3', self.catalog)
                    self.assertEqual(result['candidate']['species'], sid)

    def test_normal_and_shadow_sections_never_merge(self):
        result = parse_import('# キバニア\n1,2,3\n# キバニア (シャドウ)\n1,2,3', self.catalog)
        self.assertEqual([j['candidate']['species'] for j in result['jobs']], ['carvanha', 'carvanha_shadow'])
        self.assertEqual(result['total_candidate_count'], 2)

    def test_unsupported_or_unknown_shadow_never_becomes_normal(self):
        self.catalog['species'].pop('carvanha_shadow')
        for heading in ('シャドウキバニア', 'キバニア (シャドウ)', '未知 (シャドウ)',
                        'シャドウサメハダー 未知', 'シャドウラッタ(ヒスイ)'):
            with self.subTest(heading=heading), self.assertRaises(ValueError):
                parse_import('# ' + heading + '\n1,2,3', self.catalog)

    def test_unknown_middle_text_and_invalid_iv_are_rejected(self):
        for body in ('1,16,3', '-1,2,3', '1,2,3\nこれは未知の命令'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                parse_import('# シャドウサメハダー\n' + body, self.catalog)

    def test_missing_moves_is_distinguished_from_unrecognized_shadow_name(self):
        entry = self.catalog['species']['carvanha_shadow']
        entry.pop('default_moves')
        with self.assertRaisesRegex(ValueError, '技構成を指定'):
            parse_import('# キバニア (シャドウ)\n1,2,3', self.catalog)


if __name__ == '__main__':
    unittest.main()
