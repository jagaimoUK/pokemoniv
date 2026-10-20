"""Japanese aliases and validated PvPoke defaults for the active game data."""
from collections import defaultdict

from pvpoke_app_defaults import NAMES_JA, GL_MOVES, SOURCES
from pvpoke_app_labels import assign_nickname_codes, japanese_form_suffix
from pvpoke_app_sizes import pumpkin_aliases, pumpkin_display_name


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
                    names = (['shadow ' + x for x in names] + ['シャドウ' + x for x in names]
                             + [x + gap + '(シャドウ)' for x in names for gap in ('', ' ')])
                aliases.extend(names)
            elif shadow:
                base = sid.removesuffix('_shadow')
                if base in plain:
                    aliases.extend(['shadow ' + ja, 'シャドウ' + ja, ja + ' shadow',
                                    ja + '(シャドウ)', ja + ' (シャドウ)'])
            english = entry.get('name') or sid
            suffix = english[english.find('('):] if '(' in english else ''
            if suffix:
                aliases.append(ja + suffix)
            # GO owns Minior in Core Form, but the GL engine starts in Meteor Form.
            # A plain 'メテノ' paste must unambiguously select the experimental
            # Meteor battle representation, never the standalone Core entry.
            if sid == 'minior_meteor':
                aliases.extend((ja, ja + '(流星)', ja + '（流星）',
                                ja + '(りゅうせいのすがた)', ja + '（りゅうせいのすがた）'))
            entry['name_ja'] = ja + japanese_form_suffix(suffix) if suffix else ja + ((' (' + region + ')') if region else '')
            if sid == 'minior_meteor':
                entry['name_ja'] = ja + '（りゅうせいのすがた・試験版）'
            elif sid == 'minior_core':
                entry['name_ja'] = ja + '（コアのすがた）'
        pumpkin_name = pumpkin_display_name(sid)
        if pumpkin_name:
            entry['name_ja'] = pumpkin_name
            aliases.extend(pumpkin_aliases(sid))
        entry['aliases'] = list(dict.fromkeys(aliases))
        moves = GL_MOVES.get(sid)
        if (moves and moves[0] in entry.get('fastMoves', [])
                and all(m in entry.get('chargedMoves', []) for m in moves[1:])
                and moves[1] != moves[2]):
            entry['default_moves'] = dict(zip(('fast', 'charged1', 'charged2'), moves))
            entry['default_moves_source'] = 'PvPoke GL overall / ' + SOURCES['retrieved']

    assign_nickname_codes(payload)

