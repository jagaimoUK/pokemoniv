"""Persistent, single-worker evaluation of additional meta movesets.

The user's saved rows are retained. A bounded sample of up to six additional
profiles per species is compared against up to 32 opponents (six shields).
Adds at most one profile per species only for new sampled coverage.
No usage-frequency proxy and no ChatGPT MCP calls.
"""
import hashlib
from itertools import combinations
import json
from pathlib import Path
import queue
import threading
import time

import pvpoke_archive as archives
import pvpoke_batch_v2 as engine
import pvpoke_iv_modes as iv_modes
import pvpoke_meta_presets as presets
import pvpoke_meta_sync as csv_meta
import pvpoke_meta_live as live
from pvpoke_direct_backend import DirectMatrixClient

SHIELDS = ((0, 0), (1, 1), (2, 2), (0, 1), (0, 2), (1, 2))
_runtime = None
_queue = queue.Queue()
_queued = set()
_guard = threading.Lock()


def trusted_rows(content):
    """Internal, already validated persisted CSV; upload limits remain separate."""
    import csv, io
    rows = [tuple(x) for x in csv.reader(io.StringIO(content)) if x]
    if not rows or any(len(r) != 4 or not all(r) for r in rows):
        raise ValueError('保存済みメタの形式が不正です')
    return rows


def directory(work):
    return archives.archive_dir(work) / 'meta_variant_jobs'


def start(work, lock, status):
    global _runtime
    if _runtime is not None or not (engine.DATA / 'gamemaster.json').is_file():
        return
    _runtime = (Path(work), lock, status)
    directory(work).mkdir(parents=True, exist_ok=True)
    for path in directory(work).glob('*.json'):
        try:
            job = json.loads(path.read_text())
            if job['state'] in ('queued', 'running'):
                if job.get('minimal_policy') != 1:
                    job['state'] = 'obsolete'; save(path, job)
                else:
                    enqueue(path)
        except (OSError, ValueError, KeyError):
            continue
    threading.Thread(target=worker, daemon=True, name='meta-variants').start()


def enqueue(path):
    with _guard:
        if str(path) not in _queued:
            _queued.add(str(path)); _queue.put(path)


def schedule(work, preset_id):
    if _runtime is None or Path(work) != _runtime[0] or not (engine.DATA / 'gamemaster.json').is_file():
        return {'state': 'unavailable'}
    entry = presets.resolve(work, preset_id)
    gm_sha = hashlib.sha256((engine.DATA / 'gamemaster.json').read_bytes()).hexdigest()
    cache_key = hashlib.sha256((preset_id + entry['sha256'] + gm_sha + 'variants-v3-minimal').encode()).hexdigest()
    path = directory(work) / (cache_key + '.json')
    if not path.exists():
        save(path, {'minimal_policy': 1, 'state': 'queued', 'id': preset_id, 'source_sha256': entry['sha256'],
                    'source_csv': entry.get('source_csv') or entry['csv'], 'gm_sha256': gm_sha, 'progress': 0,
                    'policy': 'sampled coverage; >=2 new species with Rating>=550 vs manual<=500; max1/species,8/meta', 'created': time.time()})
    obj = json.loads(path.read_text())
    if obj['state'] == 'complete':
        # Reapply cached evidence after an explicit restore/update of the same
        # manual source; no battle work is repeated for completed species.
        obj['state'] = 'queued'; save(path, obj)
    if obj['state'] in ('queued', 'running'):
        enqueue(path)
    return {k: obj.get(k) for k in ('state', 'progress', 'total', 'added')}


def save(path, data):
    presets._atomic_write(path, json.dumps(data, ensure_ascii=False))


def status(work):
    jobs = []
    for path in directory(work).glob('*.json'):
        try:
            d = json.loads(path.read_text())
            jobs.append({k: d.get(k) for k in ('id', 'state', 'progress', 'total', 'added', 'error', 'created')})
        except (OSError, ValueError):
            continue
    jobs.sort(key=lambda j: j['created'], reverse=True)
    latest = {}
    for j in jobs:
        latest.setdefault(j['id'], j)
    return {'running': any(j['state'] in ('queued', 'running') for j in jobs), 'jobs': list(latest.values())[:50]}


def prepared_rows(rows, species, cpms):
    result = []
    for sid, fast, c1, c2 in rows:
        sid = sid.removesuffix('-shadow') if sid.endswith('_shadow-shadow') else sid
        a, d, h, level = iv_modes.select_opponent_ivs(species[sid], cpms, 'default')
        row = dict(zip(('species', 'fast', 'charged1', 'charged2'), (sid, fast, c1, c2)))
        result.extend(engine.optimize([{**row, 'atk': a, 'def': d, 'hp': h, 'level_override': level}], species, cpms, 'meta variants'))
    return result


def row_key(row):
    return row[0].removesuffix('-shadow'), row[1], *sorted(row[2:])


def choose_variants(candidates, matrices, manual_count, opponent_species):
    """Require new wins over ALL manual profiles; count species, not shields."""
    choices = []
    for i in range(manual_count, len(candidates)):
        gains = set()
        for matrix in matrices:
            for j, sid in enumerate(opponent_species):
                value = matrix[i+1][j+1]
                baseline = [matrix[k+1][j+1] for k in range(manual_count)]
                if value is not None and all(v is not None for v in baseline) and value >= 550 and max(baseline) <= 500:
                    gains.add(sid)
        if len(gains) >= 2:
            row = tuple(candidates[i][k] for k in ('species','fast','charged1','charged2'))
            choices.append((row, sorted(gains)))
    return sorted(choices, key=lambda x: (-len(x[1]), x[0]))[:1]


def shortlist(rows, pokemon, moves):
    """Cheap, bounded sample; manual profiles are always tested first."""
    manual = list(dict.fromkeys(rows))
    known = {row_key(r) for r in manual}
    def score(row):
        f, a, b = (moves.get(x, {}) for x in row[1:])
        fast = (f.get('power',0)+1.4*f.get('energyGain',0))/max(1,f.get('cooldown',500)/500)
        return fast + sum(m.get('power',0)/max(1,m.get('energy',1)) for m in (a,b))
    options = [(manual[0][0], f, a, b) for f in pokemon['fastMoves']
               for a,b in combinations(engine.charged_move_pool(pokemon),2)]
    if any(m not in moves for r in options for m in r[1:]):
        return manual
    options = sorted((r for r in options if row_key(r) not in known), key=lambda r: (-score(r),r))
    # Sample distinct charged type/effect roles before filling by efficiency.
    selected, roles = [], set()
    for r in options:
        role = (r[1], tuple(sorted((moves.get(m,{}).get('type',''),
                 str(moves.get(m,{}).get('buffs',[]))) for m in r[2:])))
        if role not in roles:
            roles.add(role); selected.append(r)
        if len(selected) == 6: break
    return manual + selected


def evaluate(job, client, species, cpms, lock, runtime_status, checkpoint):
    rows = trusted_rows(job['source_csv'])
    target_groups = {}
    for r in rows:
        target_groups.setdefault(r[0], r)
    targets = [r for r in target_groups.values() if not r[0].startswith('minior')][:32]
    if not targets:
        return rows, [], 0
    opponents = prepared_rows(targets, species, cpms)
    moves = None
    groups = {}
    for sid, fast, *_ in rows:
        sid = sid.removesuffix('-shadow') if sid.endswith('_shadow-shadow') else sid
        groups.setdefault(sid, []).append((sid, fast, *_[0:2]))
    extra, evidence = [], []
    groups = dict([(sid, profiles) for sid, profiles in groups.items() if not sid.startswith('minior')][:8])
    job['total'] = len(groups)
    completed = job.setdefault('evaluated', {})
    for number, (sid, fasts) in enumerate(groups.items(), 1):
        if sid in completed:
            extra.extend((tuple(r['row']), r['new_species']) for r in completed[sid]['chosen'])
            evidence.append(completed[sid])
            job['progress'] = number
            continue
        if moves is None:
            moves = {m['moveId']: m for m in json.loads((engine.DATA / 'gamemaster.json').read_text())['moves']}
        variants = shortlist(fasts, species[sid], moves)
        candidates = prepared_rows(variants, species, cpms)
        if not candidates:
            raise ValueError(sid + ': 比較できる技構成がありません')
        # Match the regular server's lock. Never overlap a user's calculation.
        while True:
            with lock:
                if runtime_status['state'] != 'running':
                    matrices = [client.simulate(candidates, opponents, shields) for shields in SHIELDS]
                    break
            threading.Event().wait(1)
        chosen = choose_variants(candidates, matrices, len(set(fasts)), [r[0] for r in targets])
        extra.extend(chosen)
        item = {'species': sid, 'tested': len(candidates),
                'chosen': [{'row': r, 'new_species': mean} for r, mean in chosen]}
        evidence.append(item)
        completed[sid] = item
        job['progress'] = number; checkpoint(job)
    known = {(r[0].removesuffix('-shadow'), r[1], *sorted(r[2:])) for r in rows}
    added = []
    for row, gains in sorted(extra, key=lambda x: (-len(x[1]), x[0]))[:max(0, min(8, 500-len(rows)))]:
        key = (row[0], row[1], *sorted(row[2:]))
        if key not in known:
            known.add(key); added.append(row)
    return rows + added, evidence, len(added)


def apply(work, job, rows):
    current = presets.resolve(work, job['id'])
    if current['sha256'] != job['source_sha256']:
        return False
    content = csv_meta.serialize(rows)
    if job['id'] == 'legacy':
        target = live.uploaded_path(work)
        presets._atomic_write(target.with_suffix('.csv.bak'), current['csv'])
        presets._atomic_write(target, content)
    else:
        obj = presets._read(work)
        entry = next(p for p in obj['items'] if p['id'] == job['id'])
        entry['source_csv'] = job['source_csv']
        entry['csv'] = content
        presets._write(work, obj)
    return True


def worker():
    work, lock, runtime_status = _runtime
    while True:
        path = _queue.get()
        job = None
        try:
            job = json.loads(path.read_text()); job['state'] = 'running'; save(path, job)
            gm_file = engine.DATA / 'gamemaster.json'
            if hashlib.sha256(gm_file.read_bytes()).hexdigest() != job['gm_sha256']:
                raise ValueError('ゲームデータが変わったため再保存して評価してください')
            _, cpms, species = engine.game_data()
            client = DirectMatrixClient(gamemaster=gm_file, log_dir=directory(work))
            try:
                rows, evidence, count = evaluate(job, client, species, cpms, lock, runtime_status, lambda j: save(path, j))
            finally:
                client.close()
            with lock:
                while runtime_status['state'] == 'running':
                    lock.release(); threading.Event().wait(1); lock.acquire()
                applied = apply(work, job, rows)
                job.update(state='complete' if applied else 'obsolete', added=count, evidence=evidence)
                save(path, job)
        except Exception as exc:
            if job is not None:
                job.update(state='failed', error=str(exc)); save(path, job)
        finally:
            with _guard:
                _queued.discard(str(path))
            _queue.task_done()
