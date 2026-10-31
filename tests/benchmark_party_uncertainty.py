"""Bounded sensitivity timing using the local engine and isolated SQLite.

Run: PYTHONPATH=.:tests python tests/benchmark_party_uncertainty.py
Fixture measurements are not a production-wide throughput claim.
"""
import copy
import json
import statistics
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from pvpoke_party_backend import PartyBuilder
from pvpoke_party_uncertainty import selected_ivs
from test_party_strategy import ROWS, GM, CATALOG, SPECIES, CPMS, engine


def measure():
    selected_ivs.cache_clear()
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work/'gamemaster.json').write_text(json.dumps(GM))
        source = work/'meta.csv'
        source.write_text(''.join(','.join(r[k] for k in engine.HEADER[:4])+'\n' for r in ROWS))
        extra = dict(species='primeape', fast='COUNTER', charged1='ICE_PUNCH', charged2='CLOSE_COMBAT')
        alternative = dict(ROWS[0], charged2='SLUDGE_BOMB')
        request = {'mode':'build', 'members':copy.deepcopy(ROWS), 'locked_slots':[0],
                   'candidate_pool':copy.deepcopy(ROWS[1:])+[extra],
                   'group_weights':{'quagsire':4, 'clodsire':3},
                   'opponent_hypotheses':[alternative], 'opponent_uncertainty':True}
        builder = PartyBuilder(work)
        results = []
        def run(label, store, args):
            tick = time.monotonic()
            result = store._compute('benchmark', args, CATALOG, SPECIES, CPMS, engine, work)
            sensitivity = result['uncertainty']
            results.append({'case':label, 'seconds':round(time.monotonic()-tick,4),
                'detail_cache':result['refinement']['cache'],
                'sensitivity_cache':sensitivity['cache'] if sensitivity else None,
                'requested_cells':sensitivity['requested_cells'] if sensitivity else 0})
        with patch.object(engine,'DATA',work), \
             patch('pvpoke_party_backend.presets.snapshot',return_value=(source,{'sha256':'fixture'})), \
             patch('pvpoke_party_backend.calculation_version',return_value='uncertainty-benchmark-v1'):
            previous=PartyBuilder(work/'previous')
            run('previous_detail_cold',previous,dict(request,opponent_uncertainty=False))
            run('previous_detail_warm',previous,dict(request,opponent_uncertainty=False))
            run('sensitivity_cold',builder,request)
            run('sensitivity_warm',builder,request)
            changed = copy.deepcopy(request);changed['members'][0]['atk']=1
            run('one_member_iv_change',builder,changed)
            run('weights_only_same_targets',builder,dict(request,
                group_weights={r['species']:request['group_weights'].get(r['species'],1)*2 for r in ROWS}))
            run('one_alternative_move_changed',builder,dict(request,
                opponent_hypotheses=[dict(alternative,charged2='MUD_BOMB')]))
        return results


if __name__=='__main__':
    samples=[measure() for _ in range(3)]
    print(json.dumps({'fixture':'7 candidates / 6 meta rows / 2 groups / 1 additional moveset',
        'samples':samples,
        'median_seconds':{row['case']:round(statistics.median(s[i]['seconds'] for s in samples),4)
                          for i,row in enumerate(samples[0])}},indent=2))
