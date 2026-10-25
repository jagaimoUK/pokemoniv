"""Keep import, direct run and both calculation backends above 150 rows."""
import json
import tempfile
import unittest
from itertools import product
from pathlib import Path

from pvpoke_app_input import parse_import
from pvpoke_input_limits import MAX_CANDIDATES
from pvpoke_iv_workflow import _canonical
from pvpoke_web import parse_ivs
from pvpoke_24_workflow import input_config
from test_app_input import CANDIDATE, CATALOG


class LargeInputTests(unittest.TestCase):
    def test_all_legal_ivs_survive_each_entry_point(self):
        all_rows = list(product(range(16), repeat=3))
        for count in (151, 500, MAX_CANDIDATES):
            with self.subTest(count=count):
                rows = all_rows[:count]
                text = '\n'.join(','.join(map(str, row)) for row in rows)
                imported = parse_import('個体値厳選\n# ヌオー\n' + text, CATALOG)
                self.assertEqual(imported['candidate_count'], count)
                self.assertEqual(imported['ivs'], text)
                self.assertEqual(parse_ivs(text), rows)
                self.assertEqual(_canonical(CANDIDATE, text, 'simple')[2], tuple(rows))
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / 'job.json'
                    path.write_text(json.dumps({'candidate': CANDIDATE, 'ivs': text}))
                    self.assertEqual(input_config(path)[1], text)

    def test_cp_records_survive_duplicate_ivs_and_multiple_evolutions(self):
        catalog = {**CATALOG, 'presets': [*CATALOG['presets'],
            {'species': 'blastoise', 'fast': 'BITE', 'charged1': 'HYDRO_CANNON', 'charged2': 'SKULL_BASH'}]}
        rows = list(product(range(16), repeat=3))[:200]
        text = '個体値厳選\n# Quagsire Blastoise\n' + '\n'.join(
            ','.join(map(str, row)) + f' CP{500+i} | quagsire' for i, row in enumerate(rows))
        text += '\n0,0,0 CP900 | quagsire'
        imported = parse_import(text, catalog)
        self.assertEqual(imported['group_count'], 2)
        for job in imported['jobs']:
            self.assertEqual(job['candidate_count'], 200)
            self.assertEqual(len(job['source_records']), 201)
            self.assertEqual(job['source_records'][-1]['cp'], 900)

    def test_invalid_and_duplicate_direct_input_still_fail(self):
        for bad in ('0,16,0', '0,0,0\n0,0,0'):
            with self.assertRaises(ValueError):
                parse_ivs(bad)
            with self.assertRaises(ValueError):
                _canonical(CANDIDATE, bad, 'simple')


if __name__ == '__main__':
    unittest.main()
