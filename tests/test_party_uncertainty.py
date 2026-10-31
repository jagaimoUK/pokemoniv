import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pvpoke_party_backend import PartyBuilder
from pvpoke_party_uncertainty import analyze, summarize_roster, rank_plans, select_groups, MAX_CELLS
from test_party_strategy import ROWS, GM, CATALOG, SPECIES, CPMS, engine


class UncertaintyMetricsTests(unittest.TestCase):
    def test_fixed_responder_prevents_hidden_moveset_oracle(self):
        groups = [{'id': 'g', 'species': 'x', 'weight': 1,
                   'hypotheses': [{'key': 'h1'}, {'key': 'h2'}]}]
        cells = {('a','h1'): 700, ('a','h2'): 400, ('b','h1'): 400, ('b','h2'): 700}
        result = summarize_roster(['a','b'], groups, cells)
        self.assertEqual(result['groups'][0]['best_fixed_responder_rating'], 400)
        self.assertEqual(result['uncovered_weight'], 1)
        self.assertEqual(result['unique_answers'], [])
        cells['a','h2'] = 600
        result = summarize_roster(['a','b'], groups, cells)
        self.assertEqual(result['unique_answers'], [{'member': 'a', 'group': 'g'}])
        cells.pop(('b','h1'))
        unknown = summarize_roster(['a','b'], groups, cells)
        self.assertEqual(unknown['status'], 'unknown')
        self.assertIsNone(unknown['guaranteed_rating'])

    def test_ranking_unknown_and_static_holes_are_protected(self):
        matrix = {(p,'x',(2,2)): 600 for p in 'abcdefg'}
        plans = [{'roster': list('abcdef'), 'before_uncertainty_rank': 1,
                  'uncertainty': {'status': 'calculated', 'uncovered_weight': 1, 'guaranteed_rating': 400}},
                 {'roster': list('abcdeg'), 'before_uncertainty_rank': 2,
                  'uncertainty': {'status': 'calculated', 'uncovered_weight': 0, 'guaranteed_rating': 600}}]
        ordered = copy.deepcopy(plans)
        self.assertTrue(rank_plans(ordered,['x'],matrix,{'x':1}))
        self.assertEqual(ordered[0]['before_uncertainty_rank'], 2)
        ordered = copy.deepcopy(plans);ordered[0]['uncertainty']['status']='unknown'
        self.assertFalse(rank_plans(ordered,['x'],matrix,{'x':1}))
        self.assertEqual(ordered[0]['before_uncertainty_rank'],1)
        matrix = {(p,'x',(2,2)): 400 for p in 'abcdefg'};matrix['f','x',(2,2)] = 600
        ordered = copy.deepcopy(plans);rank_plans(ordered,['x'],matrix,{'x':1})
        self.assertEqual(ordered[0]['before_uncertainty_rank'],1)

    def test_group_weight_not_variant_count_and_no_reversed_move_duplicates(self):
        meta = [{'id': str(i), 'meta_group_id': 'a', 'species': 'a', 'fast':'F',
                 'charged1':'C', 'charged2':'D'} for i in range(5)]
        meta += [{'id':'b','meta_group_id':'b','species':'b','fast':'F','charged1':'C','charged2':'D'},
                 {'id':'c','meta_group_id':'c','species':'c','fast':'F','charged1':'C','charged2':'D'}]
        weights = {str(i):.1 for i in range(5)} | {'b':.3,'c':.2}
        groups = select_groups([['self']],meta,{('self',p['id'],(2,2)):600 for p in meta},weights,
                               [dict(meta[0],charged1='D',charged2='C')])
        self.assertEqual([g['id'] for g in groups],['a','b'])
        self.assertEqual(groups[0]['available_movesets'],1)
        groups = select_groups([['self']],meta,{},dict.fromkeys(weights,0)|{'b':1},[])
        self.assertEqual([g['id'] for g in groups],['b'],'Zero-weight groups are not calculated')


class UncertaintyEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.work=Path(self.tmp.name)
        (self.work/'gamemaster.json').write_text(json.dumps(GM))
        self.builder=PartyBuilder(self.work)
        self.own=PartyBuilder._normalize(ROWS,CATALOG,SPECIES,CPMS,engine,'test')
        self.ids=[p['id'] for p in self.own]
        self.matrix={(p['id'],q['id'],(2,2)):550 for p in self.own for q in self.own}
        self.weights={p['id']:1/6 for p in self.own}

    def run_analysis(self, alternatives=()):
        with patch.object(engine,'DATA',self.work):
            return analyze(self.builder,'u','v',engine,self.work,self.ids,[{'roster':self.ids}],
                {p['id']:p for p in self.own},self.own,self.matrix,self.weights,
                list(alternatives),CATALOG,SPECIES,CPMS)

    def test_actual_iv_modes_moves_cache_and_immutable_inputs(self):
        before=copy.deepcopy(self.own)
        # A legal alternative from the frozen GameMaster; charged slot swaps
        # alone are not considered a different physical move hypothesis.
        base=self.own[0]
        other=next(m for m in CATALOG[base['species']]['chargedMoves'] if m not in (base['charged1'],base['charged2']))
        alt=PartyBuilder._normalize([dict(base,charged2=other)],CATALOG,SPECIES,CPMS,engine,'alt')[0]
        # Force the species with an explicit alternative into the shared stress set.
        self.weights[base['id']]=10
        one=self.run_analysis([alt]);two=self.run_analysis([alt])
        self.assertEqual(self.own,before)
        self.assertEqual(len(one['groups']),2)
        self.assertEqual(one['groups'][0]['available_movesets'],2)
        modes={m for h in one['groups'][0]['hypotheses'] for m in h['iv_modes']}
        self.assertEqual(modes,{'source','rank1','attack','defense'})
        self.assertTrue(all(h['combatant']['cp']<=1500 for g in one['groups'] for h in g['hypotheses']))
        self.assertEqual(two['cache']['computed'],0)
        self.assertEqual(two['cache']['hits'],one['evaluated_cells'])
        self.assertLessEqual(one['requested_cells'],MAX_CELLS)
        self.assertFalse((self.work/'latest.zip').exists())

    def test_unknown_and_cancel_do_not_fabricate_ivs_or_losing_ratings(self):
        with patch('pvpoke_party_uncertainty.selected_ivs',side_effect=ValueError('no supported preset')):
            result=self.run_analysis()
        self.assertEqual(result['status'],'unknown')
        self.assertTrue(any(h['status']=='unknown' for g in result['groups'] for h in g['hypotheses']))
        self.assertIsNone(result['finalists'][0]['uncertainty']['guaranteed_rating'])
        self.builder._cancel=True
        with self.assertRaisesRegex(ValueError,'cancelled'):self.run_analysis()

    def test_large_meta_uses_shared_subset_and_at_most_384_cells(self):
        rows={str(i):dict(self.own[i%6],id=str(i)) for i in range(24)}
        meta=self.own[:2]+[dict(self.own[2],id=f'm{i}',meta_group_id=f'g{i}') for i in range(498)]
        weights={p['id']:1 if i<2 else .001 for i,p in enumerate(meta)}
        matrix={(pid,p['id'],(2,2)):600 for pid in rows for p in meta}
        alternatives=[dict(self.own[0],charged2='MUD_BOMB'),dict(self.own[1],charged2='SLUDGE_BOMB')]
        plans=[{'roster':[str(i) for i in range(start,start+6)]} for start in (6,12,18)]
        def ivs(_pokemon,_cpms,mode,*_rest):
            return ({'rank1':1,'attack':2,'defense':3}[mode],12,13,None)
        with patch.object(engine,'DATA',self.work), \
             patch('pvpoke_party_uncertainty.selected_ivs',side_effect=ivs), \
             patch('pvpoke_party_uncertainty.StrategyAnalysis') as runner:
            runner.return_value.stats={};runner.return_value.client=None
            runner.return_value.resolve.return_value={'status':'calculated','rating':600}
            report=analyze(self.builder,'u','v',engine,self.work,[str(i) for i in range(6)],
                plans,rows,meta,matrix,weights,alternatives,CATALOG,SPECIES,CPMS)
        self.assertEqual(report['requested_cells'],MAX_CELLS)
        self.assertEqual(runner.return_value.resolve.call_count,MAX_CELLS)
        self.assertEqual(len(report['groups']),2)
        self.assertEqual(report['status'],'calculated')

    def test_one_unknown_cell_is_visible_without_skipping_other_members(self):
        calls=[]
        def result(*args):
            calls.append(args)
            return {'status':'unknown'} if len(calls)==1 else {'status':'calculated','rating':600}
        with patch('pvpoke_party_strategy.StrategyAnalysis.resolve',side_effect=result):
            report=self.run_analysis()
        self.assertEqual(report['status'],'unknown')
        hypothesis=report['groups'][0]['hypotheses'][0]
        self.assertEqual(hypothesis['status'],'unknown')
        self.assertEqual(hypothesis['evaluated_members'],5)
        self.assertGreater(len(calls),6)
        self.assertFalse(report['ranking_changed'])

    def test_full_worker_build_opt_out_and_settings_roundtrip(self):
        extra=dict(species='primeape',fast='COUNTER',charged1='ICE_PUNCH',charged2='CLOSE_COMBAT')
        source=self.work/'meta.csv'
        source.write_text(''.join(','.join(r[k] for k in engine.HEADER[:4])+'\n' for r in ROWS))
        args={'mode':'build','members':ROWS,'candidate_pool':ROWS[1:]+[extra],'locked_slots':[0],
              'opponent_uncertainty':True,'opponent_hypotheses':[], 'strategy_refinement':True}
        with patch.object(engine,'DATA',self.work), \
             patch('pvpoke_party_backend.presets.snapshot',return_value=(source,{'sha256':'fixture'})), \
             patch('pvpoke_party_backend.calculation_version',return_value='v'):
            result=self.builder._compute('u',args,CATALOG,SPECIES,CPMS,engine,self.work)
            self.assertEqual(result['roster'],result['uncertainty']['finalists'][0]['roster'])
            self.assertTrue(all(self.ids[0] in p['roster'] for p in result['uncertainty']['finalists']))
            self.assertEqual(len(result['pairs']),15)
            self.assertNotIn('相手IVの感度分析',result['not_calculated'])
            self.assertIn('技・IV感度の未評価条件（標本外を含む）',result['not_calculated'])
            args['opponent_uncertainty']=False
            self.assertIsNone(self.builder._compute('u',args,CATALOG,SPECIES,CPMS,engine,self.work)['uncertainty'])
            optimized=self.builder._compute('u',dict(args,mode='analyze',auto_complete=True,
                opponent_uncertainty=True),CATALOG,SPECIES,CPMS,engine,self.work)
            self.assertEqual(optimized['optimization']['finalists'],optimized['uncertainty']['finalists'])
            self.assertTrue(all(p['roster'][0]==self.ids[0] for p in optimized['optimization']['finalists']))
            for value in ('yes',1,None):
                with self.assertRaises(ValueError):self.builder._compute('u',dict(args,opponent_uncertainty=value),CATALOG,SPECIES,CPMS,engine,self.work)
            with self.assertRaisesRegex(ValueError,'8'):
                self.builder._compute('u',dict(args,opponent_uncertainty=True,opponent_hypotheses=[extra]*9),CATALOG,SPECIES,CPMS,engine,self.work)
            for value in ({},'quagsire',False,None):
                with self.assertRaises(ValueError):
                    self.builder._compute('u',dict(args,opponent_uncertainty=True,opponent_hypotheses=value),CATALOG,SPECIES,CPMS,engine,self.work)
            with self.assertRaisesRegex(ValueError,'技構成'):
                self.builder._compute('u',dict(args,opponent_uncertainty=True,
                    opponent_hypotheses=[dict(extra,fast='SPLASH')]),CATALOG,SPECIES,CPMS,engine,self.work)
        payload={'name':'Sensitivity','members':ROWS,'opponent_uncertainty':True,'opponent_hypotheses':[extra]}
        saved=self.builder.save_party(payload)
        restored=self.builder.get_party(saved['id'])
        self.assertTrue(restored['opponent_uncertainty'])
        self.assertEqual(restored['opponent_hypotheses'],[extra])


if __name__=='__main__':unittest.main()
