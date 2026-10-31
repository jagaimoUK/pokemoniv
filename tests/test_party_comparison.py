import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pvpoke_party_core as core
from pvpoke_party_backend import PartyBuilder


class PartyComparisonTests(unittest.TestCase):
    def test_directional_shields_and_unknown_values(self):
        m = {('a','x',(0,2)):320, ('a','x',(2,0)):750}
        self.assertEqual(core.party_matchup_heatmap(['a'],['x'],m,(0,2))[0]['ratings'],[320])
        self.assertEqual(core.party_matchup_heatmap(['a'],['x'],m,(2,0))[0]['ratings'],[750])
        self.assertEqual(core.party_matchup_heatmap(['a'],['x'],m,(1,1))[0]['ratings'],[None])

    def test_swap_reason_names_the_weak_group_and_tradeoff(self):
        before=list('abcdef');after=list('abcdeg')
        m={(p,q,(2,2)):400 for p in before+['g'] for q in ['x','y']}
        m['g','x',(2,2)]=700;m['f','y',(2,2)]=650
        r=core.explain_party_swap(before,after,'f','g',['x','y'],m,{'x':.7,'y':.3})
        benefit=r['benefits'][0];cost=r['costs'][0]
        self.assertEqual(benefit['opponent'],'x')
        self.assertEqual(benefit['weak_members'],before)
        self.assertEqual((benefit['before_answers'],benefit['after_answers']),(0,1))
        self.assertEqual((benefit['out_rating'],benefit['in_rating']),(400,700))
        self.assertEqual(cost['opponent'],'y')
        self.assertEqual((cost['before_answers'],cost['after_answers']),(1,0))
        m.pop(('g','x',(2,2)))
        self.assertEqual(core.explain_party_swap(before,after,'f','g',['x'],m,{'x':1})['benefits'],[])

    def test_full_conditions_fill_only_missing_cells_and_reuse_known_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            work=Path(tmp);store=PartyBuilder(work)
            calls=[]
            class Client:
                def __init__(self,**kwargs):pass
                def simulate(self,own,opp,shield):
                    calls.append(shield)
                    return [['','x'],['a',300+shield[0]*100+shield[1]*10]]
                def close(self):pass
            own=[{'id':'a','species':'a'}];opp=[{'id':'x','species':'x'}]
            known={('a','x',(2,2)):600}
            with patch('pvpoke_party_backend.DirectMatrixClient',Client):
                matrix,stats=store._matrix('j',own,opp,'v',SimpleNamespace(DATA=work),work,
                    enemy_ids=set(),recommendation_only_ids={'a'},full_conditions=True,known=known)
                self.assertEqual(stats['computed'],8)
                self.assertEqual(len(calls),8)
                self.assertNotIn((2,2),calls)
                self.assertEqual(matrix['a','x',(2,2)],600)
                self.assertEqual(matrix['a','x',(0,2)],320)
                self.assertEqual(matrix['a','x',(2,0)],500)
                again,stats=store._matrix('j',own,opp,'v',SimpleNamespace(DATA=work),work,
                    enemy_ids=set(),full_conditions=True,known=matrix)
                self.assertEqual(again,matrix)
                self.assertEqual(stats,{'computed':0,'hits':0})
                self.assertEqual(len(calls),8)
