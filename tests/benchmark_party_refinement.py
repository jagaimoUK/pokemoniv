"""Reproducible small-fixture timing (local engine, isolated SQLite, no service/MCP).

Run: PYTHONPATH=.:tests python tests/benchmark_party_refinement.py
These are sampled wall-clock measurements, not a production throughput claim.
"""
import copy
import json
import statistics
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from pvpoke_party_backend import PartyBuilder
from test_party_strategy import ROWS, GM, CATALOG, SPECIES, CPMS, engine


def measure():
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / 'gamemaster.json').write_text(json.dumps(GM))
        meta = home / 'meta.csv'
        def write_meta(rows):
            meta.write_text(''.join(','.join(r[k] for k in engine.HEADER[:4]) + '\n' for r in rows))
        write_meta(ROWS)
        extra = dict(species='primeape', fast='COUNTER', charged1='ICE_PUNCH', charged2='CLOSE_COMBAT')
        request = {'mode': 'build', 'members': copy.deepcopy(ROWS), 'locked_slots': [0],
                   'candidate_pool': copy.deepcopy(ROWS[1:]) + [extra]}
        builder = PartyBuilder(home)
        measurements = []
        def run(label, store, args):
            tick = time.monotonic()
            result = store._compute('benchmark', args, CATALOG, SPECIES, CPMS, engine, home)
            detail = result['refinement']
            measurements.append({'case': label, 'seconds': round(time.monotonic() - tick, 4),
                'static': result['cache'], 'detail': detail['cache'] if detail else None,
                'detail_seconds': detail['elapsed_seconds'] if detail else 0,
                'finalists': len(detail['finalists']) if detail else 0,
                'detail_cells': len(detail['cells']) * 4 if detail else 0})
        with patch.object(engine, 'DATA', home), \
             patch('pvpoke_party_backend.presets.snapshot', return_value=(meta, {'sha256': 'fixture'})), \
             patch('pvpoke_party_backend.calculation_version', return_value='benchmark-v1'):
            run('static_cold', PartyBuilder(home / 'static'), dict(request, strategy_refinement=False))
            run('integrated_cold', builder, request)
            run('integrated_warm', builder, request)
            changed = copy.deepcopy(request)
            changed['members'][0]['atk'] = 1
            run('one_member_iv_change', builder, changed)
            run('weights_only_same_normalized_targets', builder,
                dict(request, group_weights={r['species']: 2 for r in ROWS}))
            write_meta(ROWS + [extra])
            run('one_meta_row_added', builder, request)
        return measurements


if __name__ == '__main__':
    samples = [measure() for _ in range(3)]
    print(json.dumps({'fixture': '7 candidates / 6 then 7 meta rows / 3 finalists / 3 targets',
        'samples': samples,
        'median_seconds': {row['case']: round(statistics.median(sample[i]['seconds'] for sample in samples), 4)
                           for i, row in enumerate(samples[0])}}, indent=2))
