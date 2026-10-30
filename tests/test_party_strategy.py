import copy
import json
import os
import re
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pvpoke_batch_v2 as engine
from pvpoke_direct_backend import DirectMatrixClient
from pvpoke_party_backend import PartyBuilder
from pvpoke_party_strategy import StrategyAnalysis, normalize_config, cell_key, work_after_hit, combat

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / 'tests/fixtures'
ROWS = json.loads((FIX/'strategy_rows.json').read_text())
GM = json.loads((FIX/'strategy_gamemaster.json').read_text())
SPECIES = {p['speciesId']:p for p in GM['pokemon']}
CPMS = [float(x) for x in re.search(r'var\s+cpms\s*=\s*\[([^\]]+)\]',
        (ROOT/'vendor/pvpoke/src/js/pokemon/Pokemon.js').read_text(), re.S)[1].split(',') if x.strip()]
CATALOG = {k: {'fastMoves':p['fastMoves'], 'chargedMoves':p['chargedMoves']} for k,p in SPECIES.items()}


class EngineStrategyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.c=DirectMatrixClient(gamemaster=FIX/'strategy_gamemaster.json',log_dir=Path(self.tmp.name))
        self.addCleanup(self.c.close)

    def detail(self, a=0, b=1, **options):
        return self.c.strategy('detail',dict(self=ROWS[a],opponent=ROWS[b],shields=[2,2],**options))

    def test_standard_matrix_and_details_match_prechange_324_cells(self):
        golden=json.loads((FIX/'strategy_standard_ratings.json').read_text())
        for n,(a,b) in enumerate(( (a,b) for a in range(3) for b in range(3))):
            matrix=self.c.simulate(ROWS,ROWS,(a,b))
            self.assertEqual([row[1:7] for row in matrix[1:]],golden[n])
            for i,p in enumerate(ROWS):
                for j,q in enumerate(ROWS):
                    r=self.c.strategy('detail',dict(self=p,opponent=q,shields=[a,b]))
                    self.assertEqual(r['rating'],golden[n][i][j],(a,b,i,j))

    def test_fast_only_actual_damage_and_opponent_charged(self):
        r=self.detail(3,2,attack_policies=['fast_only','standard'])
        self.assertTrue(any(e['kind']=='charged' and e['actor']==1 for e in r['events']))
        self.assertFalse(any(e['kind']=='charged' and e['actor']==0 for e in r['events']))
        self.assertEqual(r['damage'][0]['fast'],r['initial'][1]['hp']-r['terminal'][1]['hp'])
        f=r['pressure'];self.assertEqual(f['hp_fraction_per_turn'],f['damage_per_fast']/f['fast_turns']/f['opponent_max_hp'])
        self.assertLessEqual(r['damage'][0]['fast'],r['initial'][1]['hp'])

    def test_terminal_states_asymmetric_and_initial_resources(self):
        req=dict(self=ROWS[1],opponent=ROWS[0],shields=[1,0],
            initial=[{'hp_fraction':.75,'energy_points':40,'buffs':[1,-1]},{}])
        r=self.c.strategy('detail',req)
        self.assertEqual(r['initial'][0]['hp'],int(r['initial'][0]['max_hp']*.75))
        self.assertEqual(r['initial'][0]['energy_points'],40)
        self.assertEqual(r['initial'][0]['buffs'],[1,-1])
        for i in (0,1):
            self.assertEqual(r['terminal'][i]['hp'],r['initial'][i]['hp']-sum(e['damage'] for e in r['events'] if e['actor']==1-i))
            self.assertEqual(r['terminal'][i]['shields'],req['shields'][i]-sum(e['shielded'] for e in r['events'] if e['actor']==1-i))
        self.assertEqual(r['terminal'][1]['shields'],0)

    def test_simultaneous_ko_and_timeout_are_explicit(self):
        r=self.c.strategy('detail',dict(self=ROWS[0],opponent=ROWS[0],shields=[0,0],
            initial=[{'hp_points':1},{'hp_points':1}],attack_policies=['fast_only']*2))
        self.assertEqual(r['outcome'],'simultaneous_ko')
        # Extreme negative attack / positive defense produces a real engine timeout.
        r=self.c.strategy('detail',dict(self=ROWS[2],opponent=ROWS[2],shields=[0,0],
            initial=[{'buffs':[-4,4]}]*2,attack_policies=['fast_only']*2))
        self.assertEqual(r['outcome'],'timeout')
        self.assertTrue(all(p['hp']>0 for p in r['terminal']))

    def test_reload_gamemaster_when_same_path_content_changes(self):
        dest=Path(self.tmp.name)/'gm.json';dest.write_text(json.dumps(GM))
        self.c.gamemaster=dest
        a=self.detail(3,2)
        changed=copy.deepcopy(GM)
        for m in changed['moves']:
            if m['moveId']=='PECK':m['power']+=5
        dest.write_text(json.dumps(changed))
        b=self.detail(3,2)
        self.assertNotEqual(a['gamemaster_hash'],b['gamemaster_hash'])
        self.assertNotEqual(a['pressure']['damage_per_fast'],b['pressure']['damage_per_fast'])

    def test_observable_hidden_move_invariance_in_real_engine(self):
        r=subprocess.run(['node','tests/test_battle_policy.cjs'],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(r.returncode,0,r.stderr)

    def test_branch_resources_are_carried_and_shields_shared(self):
        req=dict(lead=ROWS[0],safe=ROWS[2],opponent_lead=ROWS[1],chaser=ROWS[3],
                 shields=[2,2],lead_turns=10,chase_delay_turns=10)
        r=self.c.strategy('switch_branch',req)
        self.assertEqual(r['status'],'calculated',r.get('reason'))
        self.assertEqual(r['delay']['initial'][1]['hp'],r['opening']['terminal'][1]['hp'])
        self.assertEqual(r['delay']['initial'][1]['energy_points'],r['opening']['terminal'][1]['energy_points'])
        self.assertEqual(r['chase']['initial'][0]['hp'],r['delay']['terminal'][0]['hp'])
        self.assertEqual(r['chase']['initial'][0]['energy_points'],r['delay']['terminal'][0]['energy_points'])
        self.assertEqual(r['chase']['initial'][0]['buffs'],r['delay']['terminal'][0]['buffs'])
        for i in (0,1):
            used=sum(r[stage]['shields_used'][i] for stage in ('opening','delay','chase'))
            self.assertLessEqual(used,2);self.assertEqual(r['team_shields_remaining'][i],2-used)
            self.assertEqual(r['delay']['initial'][i]['shields'],r['opening']['terminal'][i]['shields'])
            self.assertEqual(r['chase']['initial'][i]['shields'],r['delay']['terminal'][i]['shields'])
        self.assertEqual(r['chase']['initial'][1]['energy_points'],0)
        self.assertGreaterEqual(r['realized']['chase_delay_turns'],10)
        self.assertEqual(r['remaining_two_outlook']['status'],'unknown')

    def test_probability_effect_accumulator_survives_segment_boundary(self):
        row=engine.optimize([dict(zip(engine.HEADER,
            ['primeape','KARATE_CHOP','NIGHT_SLASH','CLOSE_COMBAT',0,15,15]))],SPECIES,CPMS,'test')[0]
        base=dict(self=row,opponent=ROWS[2],shields=[0,0],attack_policies=['fast_only']*2)
        first=self.c.strategy('detail',dict(base,initial=[{
            'energy_points':20,'buffs':[1,0],'move_buff_meters':{'NIGHT_SLASH':.7}},{}],boundary_after_turns=2))
        carried=first['terminal'][0]
        second=self.c.strategy('detail',dict(base,initial=[{
            'hp_points':carried['hp'],'energy_points':carried['energy_points'],
            'buffs':carried['buffs'],'cooldown_ms':carried['cooldown_ms'],
            'move_buff_meters':carried['move_buff_meters']},{}],boundary_after_turns=2))
        self.assertEqual(second['initial'][0]['move_buff_meters']['NIGHT_SLASH'],.7)
        self.assertEqual(second['initial'][0]['buffs'],[1,0])

    def test_unreachable_switch_is_unknown_not_reset(self):
        req=dict(lead=ROWS[0],safe=ROWS[2],opponent_lead=ROWS[3],chaser=ROWS[1],
                 shields=[0,0],lead_turns=1000,chase_delay_turns=0)
        r=self.c.strategy('switch_branch',req)
        self.assertEqual(r['status'],'unknown');self.assertNotIn('chase',r)


class StrategyServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name);self.builder=PartyBuilder(self.home)
        (self.home/'gamemaster.json').write_text(json.dumps(GM))
        self.fake=SimpleNamespace(DATA=self.home)
        self.own=PartyBuilder._normalize(ROWS,CATALOG,SPECIES,CPMS,engine,'test')
        self.cfg=normalize_config({},self.own,self.own)

    def analysis(self):return StrategyAnalysis(self.builder,'test-job','engine-hash',self.fake,self.home)

    def test_detailed_cache_reuses_battle_when_only_work_changes(self):
        one=self.analysis().compute(self.own,self.own,self.cfg)
        cfg=copy.deepcopy(self.cfg);cfg['work']={'kind':'fast_damage','hp_fraction':.33}
        two=self.analysis().compute(self.own,self.own,cfg)
        self.assertEqual(one['cache']['computed'],9)
        self.assertEqual(two['cache']['hits'],9);self.assertEqual(two['cache']['computed'],0)
        self.assertEqual(two['absorb'][0]['work']['criterion'],cfg['work'])
        self.assertFalse((self.home/'latest.zip').exists())
        self.assertEqual(one['coverage']['calculated_detail_conditions'],9)

    def test_key_invalidates_policy_state_timing_data_and_schema(self):
        req={'self':combat(self.own[0]),'opponent':combat(self.own[1]),'shields':[2,2]}
        key=cell_key('v1','detail',req)
        self.assertNotEqual(key,cell_key('v2','detail',req))
        for k,v in [('initial',[{'energy_points':1},{}]),('bait',[False,True]),
                    ('shields',[1,2]),('shield_policies',[{'kind':'manual','decisions':[]}]*2),
                    ('attack_policies',['fast_only','standard']),('timing','other'),('seed',123)]:
            self.assertNotEqual(key,cell_key('v1','detail',dict(req,**{k:v})),k)
        with patch('pvpoke_party_strategy.SCHEMA','next'):
            self.assertNotEqual(key,cell_key('v1','detail',req))
        changed=copy.deepcopy(req);changed['opponent']['cp']-=1
        self.assertNotEqual(key,cell_key('v1','detail',changed))

    def test_branch_candidates_are_legal_and_no_variant_duplication(self):
        cfg=normalize_config({'include_branch':True},self.own,self.own)
        r=self.analysis().compute(self.own,self.own,cfg)
        self.assertEqual(len(r['branches']),5)
        self.assertTrue(all(e['chaser_species']!=self.own[0]['species'] for e in r['branches']))
        invalid=copy.deepcopy(self.own);invalid[1]['roster_clause_id']=invalid[0]['roster_clause_id']
        with self.assertRaises(ValueError):normalize_config({'include_branch':True},invalid,self.own)

    def test_untrusted_clause_id_cannot_evade_species_rule(self):
        rows=copy.deepcopy(ROWS[:2]);rows[1]=dict(rows[0],roster_clause_id='fake')
        p=PartyBuilder._normalize(rows,CATALOG,SPECIES,CPMS,engine,'test')
        self.assertEqual(p[0]['roster_clause_id'],p[1]['roster_clause_id'])

    def test_cancel_no_computation_and_worker_global_reservation(self):
        self.builder._cancel=True
        with self.assertRaisesRegex(ValueError,'cancelled'):
            self.analysis().resolve('detail',{})
        with patch.dict(os.environ,{'PVP_ENGINE':'direct'}):
            with self.assertRaises(RuntimeError):
                self.builder.start({'mode':'strategy'},catalog={},species={},cpms=[],engine=engine,
                    work=self.home,global_lock=threading.RLock(),global_status={'state':'running'})

    def test_worker_error_restores_existing_global_state(self):
        previous={'state':'idle','message':'Existing IV result','output':'keep.zip'}
        state=dict(previous)
        with patch.dict(os.environ,{'PVP_ENGINE':'direct'}):
            job=self.builder.start({'mode':'strategy','members':[],'opponents':[]},
                catalog=CATALOG,species=SPECIES,cpms=CPMS,engine=engine,work=self.home,
                global_lock=threading.RLock(),global_status=state)
            for _ in range(100):
                if not self.builder.running:break
                time.sleep(.005)
        self.assertFalse(self.builder.running)
        self.assertEqual(self.builder.run_status(job['job_id'])['status'],'error')
        self.assertEqual(state,previous)

    def test_gamemaster_update_during_job_fails_without_cache_write(self):
        analysis=self.analysis()
        changed=copy.deepcopy(GM);changed['timestamp']='different-data'
        (self.home/'gamemaster.json').write_text(json.dumps(changed))
        try:
            with self.assertRaisesRegex(ValueError,'GameMaster'):
                analysis.resolve('detail',dict(self=combat(self.own[0]),opponent=combat(self.own[1]),shields=[2,2]))
        finally:
            if analysis.client:analysis.client.close()
        with self.builder._db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM strategy_cells').fetchone()[0],0)

    def test_work_excludes_actions_before_received_hit(self):
        events=[{'index':0,'actor':0,'kind':'charged','move_id':'A','damage':1,'shielded':True,'turn':1,'target_hp':90},
                {'index':1,'actor':1,'kind':'charged','move_id':'B','damage':10,'shielded':False,'turn':2,'target_hp':80},
                {'index':2,'actor':0,'kind':'fast','move_id':'F','damage':15,'shielded':False,'turn':3,'target_hp':75}]
        battle={'events':events,'initial':[{'max_hp':100},{'max_hp':100}],
                'terminal':[{'hp':80,'energy_points':10},{'hp':75}],'shields_used':[0,1]}
        r=work_after_hit(battle,{'kind':'charged','move_id':'A'});self.assertFalse(r['achieved'])
        self.assertTrue(work_after_hit(battle,{'kind':'fast_damage','hp_fraction':.15})['achieved'])
        self.assertFalse(work_after_hit(battle,{'kind':'force_shield'})['achieved'])
        battle['events']=[]
        self.assertIsNone(work_after_hit(battle,{'kind':'force_shield'})['achieved'])

    def test_strategy_settings_saved_and_revision_preserved(self):
        s=self.builder.save_party({'name':'Stage D','members':ROWS,'strategy':self.cfg})
        self.assertEqual(self.builder.get_party(s['id'])['strategy'],self.cfg)

    def test_cache_budget_and_no_old_rating_inference(self):
        a=self.analysis();base=dict(self=combat(self.own[0]),opponent=combat(self.own[1]),shields=[2,2])
        with self.builder._db() as db:db.execute('INSERT INTO cells VALUES(?,?,?)',('old-rating-only',600,0))
        with patch('pvpoke_party_strategy.DETAIL_BUDGET',100):
            r=a.resolve('detail',base)
        with self.builder._db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM strategy_cells').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT rating FROM cells').fetchone()[0],600)
        self.assertIn('terminal',r)
        if a.client:a.client.close()

    def test_invalid_config_and_predeclared_work_rejected(self):
        for raw in ({'self_index':-1},{'manual_self':[1]},{'danger_ratio':float('nan')},
                    {'work':{'kind':'charged','move_id':'INVALID'}},
                    {'work':{'kind':'fast_damage','hp_fraction':0}}):
            with self.assertRaises(ValueError):normalize_config(raw,self.own,self.own)


if __name__=='__main__':unittest.main()
