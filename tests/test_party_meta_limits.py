"""Exercise the complete analysis path past the old 100-row preview limit."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pvpoke_party_core as core
from pvpoke_party_backend import PartyBuilder, SHIELDS_META


class PartyMetaLimitTests(unittest.TestCase):
    def test_full_analysis_accepts_101_and_500_rows_and_excludes_zero_weight(self):
        for count in (101, 500, 501):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp)
                store = PartyBuilder(work)
                own = [dict(species=f'own{i}', fast='A', charged1='B', charged2='C')
                       for i in range(6)]
                targets = [dict(species=f'm{i}', fast='A', charged1='B', charged2='C')
                           for i in range(count)]
                catalog = {r['species']: {'fastMoves': ['A'], 'chargedMoves': ['B', 'C']}
                           for r in own + targets}
                species = {sid: {'dex': i} for i, sid in enumerate(catalog)}
                engine = SimpleNamespace(HEADER=['species', 'fast', 'charged1', 'charged2', 'atk', 'def', 'hp'],
                    DATA=work, CP_CAP=1500, MAX_LEVEL=50,
                    optimize=lambda rows, *args: [dict(r, level=20, cp=1490) for r in rows])
                source = work / 'meta.csv'
                source.write_text(''.join(f'{r["species"]},A,B,C\n' for r in targets))
                observed = []
                def matrix(jid, pool, opponents, *args, **kwargs):
                    observed.extend(p['species'] for p in opponents)
                    values = {(p['id'], q['id'], shield): 600
                              for p in pool for q in opponents for shield in core.ALL_SHIELDS}
                    return values, {'hits': 0, 'computed': len(pool)*len(opponents)*len(SHIELDS_META)}
                request = {'mode':'analyze', 'members':own, 'group_weights':{'m0':0}}
                with patch('pvpoke_party_backend.presets.snapshot', return_value=(source, {'sha256':'fixture'})), \
                     patch('pvpoke_party_backend.calculation_version', return_value='fixture'), \
                     patch('pvpoke_party_backend.iv_modes.select_opponent_ivs', return_value=(0,15,15,20)), \
                     patch.object(store, '_matrix', side_effect=matrix):
                    if count > 500:
                        with self.assertRaisesRegex(ValueError, '500'):
                            store._compute('fixture', request, catalog, species, [], engine, work)
                        self.assertEqual(observed, [])
                    else:
                        result = store._compute('fixture', request, catalog, species, [], engine, work)
                        self.assertEqual(len(observed), count-1)
                        self.assertNotIn('m0', observed)
                        self.assertEqual(result['meta']['hypotheses'], count-1)
                        self.assertEqual(result['team']['unknown_weight'], 0)
                        self.assertEqual(result['cache']['computed'], 6*(count-1)*6)
