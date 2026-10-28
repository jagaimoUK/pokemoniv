"""Network-free smoke tests for the 24-condition PvPoke batch workflow."""
import csv
import json
import re
import tempfile
import unittest
from pathlib import Path

import pvpoke_24_workflow as batch


class Batch24Tests(unittest.TestCase):
    def test_conditional_return_and_frustration_match_pvpoke_eligibility(self):
        pool=batch.engine.charged_move_pool
        base={'chargedMoves':['SHADOW_BALL'], 'tags':['shadoweligible'], 'level25CP':1500}
        self.assertEqual(pool(base),['SHADOW_BALL','RETURN'])
        self.assertEqual(base['chargedMoves'],['SHADOW_BALL'],'do not mutate cached GameMaster')
        self.assertEqual(pool({**base,'level25CP':1501}),['SHADOW_BALL'])
        self.assertEqual(pool({**base,'tags':[]}),['SHADOW_BALL'])
        self.assertEqual(pool({**base,'tags':['shadow']}),['SHADOW_BALL','FRUSTRATION'])
        self.assertEqual(pool({**base,'chargedMoves':['RETURN','SHADOW_BALL']}),['RETURN','SHADOW_BALL'])
        self.assertEqual(pool({'chargedMoves':['SHADOW_BALL'],'tags':['shadoweligible']}),['SHADOW_BALL'])

    def test_reported_87_move_sets_prepare_with_return_and_shadows(self):
        import pvpoke_meta_live as live
        fixtures=Path(__file__).parent/'fixtures'
        species=json.loads((fixtures/'meta_pvpoke_mixed_species.json').read_text())['species']
        source=(fixtures/'meta_pvpoke_mixed_columns.csv').read_text()
        js=(Path(__file__).parent.parent/'vendor/pvpoke/src/js/pokemon/Pokemon.js').read_text()
        cpms=[float(x.strip()) for x in re.search(r'var\s+cpms\s*=\s*\[([^\]]+)\]',js).group(1).split(',') if x.strip()]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'meta.csv';path.write_text(live.normalize_input(source)['csv'])
            meta,errors=batch.load_meta(path,species)
        self.assertEqual(errors,[])
        rows,report,errors,counts=batch.generate_rows(meta,species,cpms,full_modes=('default',))
        self.assertEqual(errors,[])
        self.assertEqual(len(rows),87)
        grumpig=next(r for r in rows if r['species']=='grumpig')
        self.assertEqual(grumpig['charged2'],'RETURN')
        self.assertTrue(any(r['species']=='quagsire_shadow' for r in rows))

    def test_meta_reader_normalizes_shadow_suffix(self):
        species = {'feraligatr_shadow': {
            'fastMoves': ['SHADOW_CLAW'], 'chargedMoves': ['HYDRO_CANNON', 'ICE_BEAM']}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'meta.csv'
            path.write_text('feraligatr_shadow-shadow,SHADOW_CLAW,HYDRO_CANNON,ICE_BEAM\n'
                            'unknown,TACKLE,X,Y\n', encoding='utf-8')
            good, rejected = batch.load_meta(path, species)
        self.assertEqual(len(good), 1)
        self.assertEqual(good[0]['species'], 'feraligatr_shadow')
        self.assertEqual(len(rejected), 1)

    def test_explicit_candidate_ivs_are_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'job.json'
            path.write_text(json.dumps({
                'candidate': {'species': 'azumarill', 'fast': 'BUBBLE',
                              'charged1': 'ICE_BEAM', 'charged2': 'PLAY_ROUGH'},
                'ivs': '0,15,15\n1,15,14',
            }), encoding='utf-8')
            candidate, ivs = batch.input_config(path)
            self.assertEqual(candidate['species'], 'azumarill')
            self.assertEqual(ivs.splitlines(), ['0,15,15', '1,15,14'])

    def test_simple_mode_splits_into_six_csvs_and_one_mode_summary(self):
        self.assertEqual(batch.BATCH_MODES["simple"], ("default",))
        self.assertEqual(batch.BATCH_MODES["detailed"], batch.MODES)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw"
            raw.mkdir()
            report = [{"mode": "default"} for _ in range(2)]
            header = ["candidate", "opp_0", "opp_1", "Wins", "Losses", "Draws", "Average"]
            for shield in batch.SHIELDS:
                batch.write_csv(raw / f"pvpoke_{shield}.csv", header, [
                    ["quagsire_0/11/12", "560", "440", "1", "1", "0", "500"]
                ])
            candidates = [{"species": "quagsire", "fast": "MUD_SHOT",
                           "charged1": "AQUA_TAIL", "charged2": "STONE_EDGE",
                           "atk": 0, "def": 11, "hp": 12}]
            paths = batch.split_matrix(raw, root / "results", report, candidates,
                                       full_modes=batch.BATCH_MODES["simple"])
            self.assertEqual(len(paths), 7)
            self.assertEqual(len(list((root / "results").glob("default_*.csv"))), 6)
            self.assertFalse((root / "results" / "rank1_s0.csv").exists())
            with (root / "results" / "ranking_summary.csv").open(encoding="utf-8-sig") as fp:
                rows = list(csv.DictReader(fp))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["opponent_iv_mode"], "default")
            self.assertEqual(rows[0]["matchups"], "12")

    def test_six_matrices_split_into_24_csvs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / 'raw'
            raw.mkdir()
            report = [{'mode': mode} for mode in batch.MODES for _ in range(2)]
            header = ['candidate'] + [f'opp_{i}' for i in range(8)] + ['Wins', 'Losses', 'Draws', 'Average']
            for shield in batch.SHIELDS:
                batch.write_csv(raw / f'pvpoke_{shield}.csv', header,
                                [[f'azumarill_{i}', *[str(450 + j*10 + i*20) for j in range(8)],
                                  '2', '6', '0', '500'] for i in range(2)])
            candidates = [{'species': 'azumarill', 'fast': 'BUBBLE',
                           'charged1': 'ICE_BEAM', 'charged2': 'PLAY_ROUGH',
                           'atk': i, 'def': 15, 'hp': 15-i} for i in range(2)]
            files = batch.split_matrix(raw, root / 'results', report, candidates)
            self.assertEqual(len(files), 25)
            with (root / 'results' / 'default_s0.csv').open(encoding='utf-8-sig') as fp:
                self.assertEqual(len(list(csv.reader(fp))), 3)
            with (root / 'results' / 'ranking_summary.csv').open(encoding='utf-8-sig') as fp:
                self.assertEqual(len(list(csv.reader(fp))), 9)


if __name__ == '__main__':
    unittest.main()
