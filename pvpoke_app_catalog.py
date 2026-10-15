"""Japanese aliases and validated PvPoke defaults for the active game data."""
from collections import defaultdict

from pvpoke_app_defaults import NAMES_JA, GL_MOVES, SOURCES


def enrich_catalog(payload: dict, species: dict) -> None:
    by_dex = defaultdict(list)
    for sid, p in species.items():
        by_dex[p.get('dex')].append(sid)
    for sid, entry in payload.items():
        raw = species[sid]
        ja = NAMES_JA.get(raw.get('dex'))
        aliases = []
        if ja:
            siblings = by_dex[raw.get('dex')]
            plain = [x for x in siblings if '_' not in x]
            if not plain:
                plain = [x for x in siblings if not any(
                    word in x.split('_') for word in ('shadow', 'mega', 'galarian', 'alolan', 'hisuian', 'paldean'))]
            if plain == [sid]:
                aliases.append(ja)
            region = next((label for word, label in (
                ('galarian', 'ガラル'), ('alolan', 'アローラ'),
                ('hisuian', 'ヒスイ'), ('paldean', 'パルデア')) if word in sid.split('_')), None)
            shadow = 'shadow' in sid.split('_')
            if region:
                names = [region + ja, ja + '(' + region + ')']
                if shadow:
                    names = ['shadow ' + x for x in names] + ['シャドウ' + x for x in names]
                aliases.extend(names)
            elif shadow:
                base = sid.removesuffix('_shadow')
                if base in plain:
                    aliases.extend(['shadow ' + ja, 'シャドウ' + ja, ja + ' shadow'])
            english = entry.get('name') or sid
            suffix = english[english.find('('):] if '(' in english else ''
            if suffix:
                aliases.append(ja + suffix)
            entry['name_ja'] = ja + ((' (' + region + ')') if region else suffix)
        entry['aliases'] = list(dict.fromkeys(aliases))
        moves = GL_MOVES.get(sid)
        if (moves and moves[0] in entry.get('fastMoves', [])
                and all(m in entry.get('chargedMoves', []) for m in moves[1:])
                and moves[1] != moves[2]):
            entry['default_moves'] = dict(zip(('fast', 'charged1', 'charged2'), moves))
            entry['default_moves_source'] = 'PvPoke GL overall / ' + SOURCES['retrieved']
