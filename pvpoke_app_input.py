"""Import one species/moveset from pasted IV commands or existing PvPoke CSV.

Parsing validates the entire paste before returning anything to the form.
It never starts a battle, guesses an unknown species, or mixes evolution groups.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata

FIELDS = ('species', 'fast', 'charged1', 'charged2')
TRIPLE = re.compile(r'^\d{1,2}\s*[,/]\s*\d{1,2}\s*[,/]\s*\d{1,2}$')


def app_presets(species: dict, legacy: list[dict], meta_text: str) -> list[dict]:
    """Use all valid active meta movesets, retaining the previous quick picks."""
    rows, seen = [], set()
    candidates = list(legacy)
    for fields in csv.reader(io.StringIO(meta_text)):
        if len(fields) == 4:
            sid, *moves = [x.strip() for x in fields]
            if sid.endswith('_shadow-shadow'):
                sid = sid[:-7]
            candidates.append(dict(zip(FIELDS, [sid, *moves])))
    for candidate in candidates:
        sid = candidate.get('species')
        p = species.get(sid, {})
        if (candidate.get('fast') not in p.get('fastMoves', [])
                or any(candidate.get(k) not in p.get('chargedMoves', []) for k in FIELDS[2:])
                or candidate['charged1'] == candidate['charged2']):
            continue
        key = tuple(candidate[k] for k in FIELDS)
        if key in seen:
            continue
        seen.add(key)
        rows.append({**candidate, 'key': '|'.join(key),
                     'name': candidate.get('name') or p.get('name') or sid})
    return rows


def parse_import(text: str, catalog: dict, current: dict | None = None) -> dict:
    if not isinstance(text, str) or not text.strip() or len(text) > 140000:
        raise ValueError('ポケモン名・技・個体値、またはCSVを貼り付けてください')
    species = catalog.get('species', {})
    presets = catalog.get('app_presets') or catalog.get('presets', [])
    current = current or {}
    if not isinstance(current, dict):
        raise ValueError('現在のポケモン情報が不正です')
    def normalized(word):
        return unicodedata.normalize('NFKC', word).strip().casefold()
    aliases = {}
    for sid, entry in species.items():
        for name in [sid, entry.get('name')]:
            if name:
                aliases.setdefault(normalized(name), set()).add(sid)
    for entry in catalog.get('presets', []):
        if entry.get('name'):
            aliases.setdefault(normalized(entry['name']), set()).add(entry['species'])
    def resolve(word):
        key = normalized(word)
        if key.endswith('_shadow-shadow'):
            key = key[:-7]
        matches = aliases.get(key, set())
        if len(matches) == 1:
            return next(iter(matches))
        return None
    chosen, chosen_moves, triples, warnings = None, None, [], []
    mode = None
    ignored_levels = False
    def set_species(sid):
        nonlocal chosen
        if chosen is not None and chosen != sid:
            raise ValueError('複数種が含まれています。1回の取り込みでは1種類ずつ貼り付けてください')
        chosen = sid
    def set_moves(values):
        nonlocal chosen_moves
        values = tuple(v.strip().upper() for v in values)
        if chosen_moves is not None and values != chosen_moves:
            raise ValueError('複数の技構成が含まれています。技構成ごとに取り込んでください')
        chosen_moves = values
    def add_iv(parts, line):
        if len(parts) != 3 or any(not re.fullmatch(r'\d{1,2}', x.strip()) for x in parts):
            raise ValueError(f'{line}行目: 個体値は攻撃,防御,HPの3つで指定してください')
        triple = tuple(int(x) for x in parts)
        if any(x > 15 for x in triple):
            raise ValueError(f'{line}行目: 個体値は0〜15です')
        triples.append(triple)
    text = unicodedata.normalize('NFKC', text).replace('\ufeff', '').replace('、', ',')
    header = None
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('```'):
            continue
        command = re.fullmatch(r'(?:個体値厳選|個体値リスト|重要個体値)(?:\s+([ds]))?', line, re.I)
        if command:
            if command.group(1):
                new_mode = 'detailed' if command.group(1).lower() == 'd' else 'simple'
                if mode and mode != new_mode:
                    raise ValueError('計算モードが混在しています')
                mode = new_mode
            continue
        if TRIPLE.fullmatch(line):
            add_iv(re.split(r'\s*[,/]\s*', line), number)
            continue
        # Support several space-separated IV triples from voice transcription.
        if re.fullmatch(r'\d{1,2},\d{1,2},\d{1,2}(?:\s+\d{1,2},\d{1,2},\d{1,2})+', line):
            for group in line.split():
                add_iv(group.split(','), number)
            continue
        cleaned = re.sub(r'^(?:ポケモン|種族|species)\s*:\s*', '', line, flags=re.I)
        cleaned = re.sub(r'^#+\s*', '', cleaned)
        sid = resolve(cleaned)
        if sid:
            set_species(sid)
            continue
        move_line = re.sub(r'^(?:技構成|技|moves)\s*:\s*', '', line, flags=re.I)
        fields = [x.strip() for x in next(csv.reader([move_line]))]
        if fields and fields[0].casefold() == 'species' and len(fields) >= 7:
            header = [x.casefold() for x in fields]
            continue
        if header is not None:
            if len(fields) != len(header):
                raise ValueError(f'{number}行目: CSVの列数が一致しません')
            row = dict(zip(header, fields))
            required = {*FIELDS, 'atk', 'def', 'hp'}
            if not required <= row.keys():
                raise ValueError('CSVにはspecies,fast,charged1,charged2,atk,def,hp列が必要です')
            sid = resolve(row['species'])
            if not sid:
                raise ValueError(f'{number}行目: ポケモンが見つかりません')
            set_species(sid)
            set_moves([row[k] for k in FIELDS[1:]])
            add_iv([row[k] for k in ('atk', 'def', 'hp')], number)
            ignored_levels |= 'level' in row
            continue
        if len(fields) in (4, 7, 8) and resolve(fields[0]):
            set_species(resolve(fields[0]))
            set_moves(fields[1:4])
            if len(fields) in (7, 8):
                add_iv(fields[-3:], number)
                ignored_levels |= len(fields) == 8
            continue
        if len(fields) == 3 and all(re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', x) for x in fields):
            set_moves(fields)
            continue
        raise ValueError(f'{number}行目を読み取れません: {line[:80]}。英語ID・英語名、技ID、個体値またはCSVで指定してください')
    if not triples:
        raise ValueError('個体値がありません。攻撃,防御,HPの順に貼り付けてください')
    if not chosen:
        chosen = current.get('species')
        warnings.append('ポケモン名の指定がないため、現在フォームで選択している種類を使います')
    if chosen not in species:
        raise ValueError('ポケモンを指定してください。プリセット外は英語ID・英語名が使えます')
    if chosen_moves is None:
        if chosen == current.get('species') and all(current.get(k) for k in FIELDS[1:]):
            chosen_moves = tuple(current[k] for k in FIELDS[1:])
            warnings.append('技の指定がないため、現在フォームの技構成を使います')
        else:
            available = [p for p in presets if p['species'] == chosen]
            configs = {tuple(p[k] for k in FIELDS[1:]) for p in available}
            if len(configs) != 1:
                raise ValueError('技構成を指定してください。このポケモンには未登録または複数の技構成があります')
            chosen_moves = next(iter(configs))
            warnings.append('技の指定がないため、登録済みの唯一の技構成を使います')
    entry = species[chosen]
    if (chosen_moves[0] not in entry.get('fastMoves', [])
            or any(m not in entry.get('chargedMoves', []) for m in chosen_moves[1:])
            or chosen_moves[1] == chosen_moves[2]):
        raise ValueError('技構成が現在のPvPokeデータと一致しません。技IDを確認してください')
    unique = list(dict.fromkeys(triples))
    if not 1 <= len(unique) <= 150:
        raise ValueError('個体値は1〜150体までです')
    if len(unique) != len(triples):
        warnings.append(f'重複する個体値{len(triples) - len(unique)}件をまとめました')
    if ignored_levels:
        warnings.append('貼り付け元のレベルは使わず、計算時にCP1500以下へ調整します')
    return {'candidate': dict(zip(FIELDS, [chosen, *chosen_moves])),
            'ivs': '\n'.join(','.join(map(str, triple)) for triple in unique),
            'candidate_count': len(unique), 'batch_mode': mode, 'warnings': warnings}
