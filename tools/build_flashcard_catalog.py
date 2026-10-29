#!/usr/bin/env python3
"""Compile downloaded PvPoke snapshots; no network or application credentials.

Usage: python tools/build_flashcard_catalog.py /directory/with/upstream/files
Input names: gamemaster.json, rankings-{1500,2500,10000}.json, move_names.csv.
"""
from datetime import datetime
from zoneinfo import ZoneInfo
import csv
import hashlib
import json
from pathlib import Path
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pvpoke_app_catalog import enrich_catalog
from pvpoke_batch_v2 import charged_move_pool
from pvpoke_flashcards import rows_from_csv
from pvpoke_meta_presets import bundled


def normal(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s).lower() if c.isalnum())


def build(source):
    gm = json.loads((source / 'gamemaster.json').read_text())
    raw_species = {p['speciesId']: p for p in gm['pokemon']}
    enriched = {sid: {'name': p['speciesName'], 'fastMoves': p['fastMoves'],
                      'chargedMoves': charged_move_pool(p, 10000)} for sid, p in raw_species.items()}
    enrich_catalog(enriched, raw_species)
    translations = {}
    for row in csv.DictReader((source / 'move_names.csv').open(encoding='utf-8')):
        translations.setdefault(row['move_id'], {})[row['local_language_id']] = row['name']
    japanese = {normal(r['9']): r.get('1', r.get('11')) for r in translations.values() if '9' in r}
    moves = {m['moveId']: {'name': m['name'], 'ja': japanese.get(normal(m['name'])) or m['name'],
                          'gain': m.get('energyGain', 0), 'cost': m.get('energy', 0),
                          'turns': m.get('turns') or m.get('cooldown', 0) // 500} for m in gm['moves']}
    species = {sid: {'name': p['name'], 'ja': p.get('name_ja', p['name']),
                     'aliases': p['aliases'], 'fast': [m for m in p['fastMoves'] if moves.get(m, {}).get('gain', 0)>0],
                     'charged': [m for m in p['chargedMoves'] if 0<moves.get(m, {}).get('cost', 0)<=100]}
               for sid, p in enriched.items()}
    leagues = []
    for cap, name in [(1500, 'スーパーリーグ'), (2500, 'ハイパーリーグ'), (10000, 'マスターリーグ')]:
        ranked = json.loads((source / f'rankings-{cap}.json').read_text())
        rows, invalid = [], []
        for p in ranked:
            sid = p['speciesId']; chosen = p['moveset']; s = species.get(sid)
            if not s or len(chosen)<3 or chosen[0] not in s['fast'] or not all(c in s['charged'] for c in chosen[1:]):
                invalid.append(sid); continue
            rows.append({'species': sid, 'fast': chosen[:1], 'charged': chosen[1:], 'score': p['score']})
        leagues.append({'id': 'rank:' + str(cap), 'name': name, 'rows': rows, 'unavailable': invalid})
    decks = [{'id': 'meta:legacy', 'name': 'これまでのカスタムメタ', 'source': 'meta',
              'rows': rows_from_csv((ROOT / 'pvpoke_meta_opponents.csv').read_text())}]
    for entry in bundled()['items']:
        if entry.get('available') is not False:
            decks.append({'id': 'meta:' + entry['id'], 'name': entry['name'], 'source': 'meta',
                          'rows': rows_from_csv(entry['csv'])})
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
              [source/'gamemaster.json', source/'move_names.csv', *(source/f'rankings-{n}.json' for n in (1500,2500,10000))]}
    data = {'version': 1, 'retrieved': datetime.now(ZoneInfo('Asia/Tokyo')).date().isoformat(), 'timestamp': gm['timestamp'],
            'sources': {'pvpoke': 'https://github.com/pvpoke/pvpoke/tree/master/src/data',
                        'move_names': 'https://github.com/PokeAPI/pokeapi/blob/master/data/v2/csv/move_names.csv', 'sha256': hashes},
            'species': species, 'moves': moves, 'leagues': leagues, 'decks': decks}
    data['revision'] = hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    target = ROOT/'data/flashcard_catalog.json'
    target.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':'))+'\n', encoding='utf-8')
    print(f'{len(species)} species, {len(moves)} moves, {len(decks)} decks; {target.stat().st_size} bytes')
    print('Rankings:', [(l['id'], len(l['rows']), len(l['unavailable'])) for l in leagues])


if __name__ == '__main__':
    build(Path(sys.argv[1]))
