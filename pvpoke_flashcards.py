"""Read-only flashcard data adapters. Never invoke ChatGPT's PvPoke MCP."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path

import pvpoke_meta_presets as presets
import pvpoke_meta_live as live

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data' / 'flashcard_catalog.json'


@lru_cache(maxsize=1)
def public_catalog():
    return json.loads(DATA.read_text(encoding='utf-8'))


def rows_from_csv(content):
    grouped = {}
    for sid, fast, c1, c2 in live._parse(content, trusted=True):
        sid = sid.removesuffix('-shadow') if sid.endswith('_shadow-shadow') else sid
        # Keep each selected fast/charged combination; no cross-product across unrelated rows.
        key = (sid, fast)
        row = grouped.setdefault(key, {'species': sid, 'fast': [fast], 'charged': []})
        row['charged'] = list(dict.fromkeys([*row['charged'], c1, c2]))
    return list(grouped.values())


def private_decks(work):
    listing = presets.listing(work)
    decks = []
    for info in listing['items']:
        if info.get('available') is False:
            continue
        entry = presets.resolve(work, info['id'])
        decks.append({'id': 'meta:' + entry['id'], 'name': entry['name'],
                      'source': 'meta', 'revision': entry['sha256'],
                      'rows': rows_from_csv(entry['csv'])})
    return {'decks': decks, 'revision': listing['revision']}


@lru_cache(maxsize=1)
def page():
    template = (ROOT / 'flashcards.html').read_text(encoding='utf-8')
    for token, filename in [('/*CORE*/', 'flashcards_core.js'), ('/*UI*/', 'flashcards_ui.js')]:
        template = template.replace(token, (ROOT / filename).read_text(encoding='utf-8'))
    bootstrap = json.dumps(public_catalog(), ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    return template.replace('/*BOOTSTRAP*/', 'window.FLASHCARD_BOOTSTRAP=' + bootstrap + ';')


def etag():
    return '"' + public_catalog()['revision'] + '"'
