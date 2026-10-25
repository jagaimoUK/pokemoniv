"""Import grouped species/movesets from pasted IV commands or PvPoke CSV.

Parsing validates the entire paste before returning anything to the form.
It never starts a battle, guesses unknown species, or mixes species' ratings.
"""
from __future__ import annotations

from pvpoke_input_limits import MAX_CANDIDATES, MAX_IMPORT_CHARS, MAX_APP_REQUEST_BYTES

import csv
import io
import re
import unicodedata

from pvpoke_app_sizes import FAMILIES
from pvpoke_form_rules import battle_entry_species, battle_entry_notice
from pvpoke_app_selection import search_string

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
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_IMPORT_CHARS:
        raise ValueError('ポケモン名と個体値、またはCSVを貼り付けてください')
    species = catalog.get('species', {})
    presets = catalog.get('app_presets') or catalog.get('presets', [])
    current = current or {}
    if not isinstance(current, dict):
        raise ValueError('現在のポケモン情報が不正です')
    def normalized(word):
        return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', word).strip().casefold())
    aliases = {}
    for sid, entry in species.items():
        for name in [sid, entry.get('name'), *entry.get('aliases', [])]:
            if name:
                aliases.setdefault(normalized(name), set()).add(sid)
    for entry in catalog.get('presets', []):
        if entry.get('name'):
            aliases.setdefault(normalized(entry['name']), set()).add(entry['species'])
    def resolve(word):
        key = normalized(word)
        if key in (*FAMILIES, *FAMILIES.values()):
            raise ValueError(f'{word}: サイズを指定してください（こだましゅ/XS、ちゅうだましゅ/通常、おおだましゅ/XL、ギガだましゅ/XXL）')
        if key.endswith('_shadow-shadow'):
            key = key[:-7]
        # A generic Minior name refers to its in-battle starting (Meteor)
        # form, even if a preset happens to label Core simply as "メテノ".
        if key in ('メテノ', 'minior') and 'minior_meteor' in species:
            return 'minior_meteor'
        matches = aliases.get(key, set())
        return next(iter(matches)) if len(matches) == 1 else None
    ordered_aliases = sorted((x for x in aliases if len(aliases[x]) == 1), key=len, reverse=True)
    def targets(word):
        word = normalized(re.sub(r'^これ以降\s*', '', word))
        exact = resolve(word)
        if exact:
            return [exact]
        found = []
        while word:
            match = next((a for a in ordered_aliases if word.startswith(a)
                          and (len(word) == len(a) or word[len(a)] in ' ,、と・/')), None)
            if match is None:
                return None
            sid = resolve(match)
            if sid not in found:
                found.append(sid)
            word = word[len(match):].lstrip(' ,、と・/')
        return found or None
    sections = []
    section = {'species': None, 'moves': None, 'ivs': [], 'levels': False, 'records': []}
    sections.append(section)
    mode, header = None, None
    def change_section(sids, moves=None, force=False):
        nonlocal section
        if not force and section['species'] is None:
            section['species'], section['moves'] = sids, moves or section['moves']
        else:
            section = {'species': sids, 'moves': moves, 'ivs': [], 'levels': False, 'records': []}
            sections.append(section)
    def add_iv(parts, line):
        if len(parts) != 3 or any(not re.fullmatch(r'\d{1,2}', x.strip()) for x in parts):
            raise ValueError(f'{line}行目: 個体値は攻撃,防御,HPの3つです')
        triple = tuple(int(x) for x in parts)
        if any(x > 15 for x in triple):
            raise ValueError(f'{line}行目: 個体値は0〜15です')
        section['ivs'].append(triple)
        return triple

    def add_record(iv, cp, source, line):
        if not re.fullmatch(r'\d{1,5}', str(cp)) or not 1 <= int(cp) <= 10000:
            raise ValueError(f'{line}行目: 読み取りCPは1〜10000です')
        sid = resolve(source)
        if sid is None:
            raise ValueError(f'{line}行目: CPを読み取った元のポケモンを特定できません: {source}')
        name = species[sid].get('name', sid).removesuffix(' (Shadow)')
        iv_text = '/'.join(map(str, iv))
        shadow = 'shadow' in sid
        section['records'].append({'ivs': iv_text, 'cp': int(cp), 'species': sid,
            'search_string': search_string(name, iv_text, shadow, sid) + f'&cp{int(cp)}'})
    text = unicodedata.normalize('NFKC', text).replace('\ufeff', '').replace('、', ',')
    # Hyphens separated by whitespace are list/paragraph separators, never a
    # negative-IV sign or the export spelling "_shadow-shadow".
    text = re.sub(r'\s+[-–—]\s+', '\n', text)
    iv_pattern = r'\d{1,2}\s*[,/]\s*\d{1,2}\s*[,/]\s*\d{1,2}'
    for number, raw in enumerate(text.splitlines(), 1):
        line = re.sub(r'^[-•]\s+', '', raw.strip())
        if not line or line in ('-', '–', '—') or line.startswith('```'):
            continue
        command = re.fullmatch(r'(?:個体値厳選|個体値リスト|重要個体値)(?:\s+([ds]))?', line, re.I)
        if command:
            if command.group(1) or line == '個体値厳選':
                new_mode = 'detailed' if (command.group(1) or '').lower() == 'd' else 'simple'
                if mode and mode != new_mode:
                    raise ValueError('計算モードが混在しています')
                mode = new_mode
            continue
        observed = re.fullmatch(r'(' + iv_pattern + r')\s+CP\s*(\d+)\s*\|\s*(.+)', line, re.I)
        if observed:
            iv = add_iv(re.split(r'\s*[,/]\s*', observed[1]), number)
            add_record(iv, observed[2], observed[3], number)
            continue
        groups = re.findall(iv_pattern, line)
        if groups and not re.sub(iv_pattern, '', line).strip():
            for group in groups:
                add_iv(re.split(r'\s*[,/]\s*', group), number)
            continue
        if line.startswith('#'):
            sids = targets(re.sub(r'^#+\s*', '', line))
            if not sids:
                raise ValueError(f'{number}行目: 種名・フォルムを特定できません: {line}')
            change_section(sids, force=True)
            header = None
            continue
        cleaned = re.sub(r'^(?:ポケモン|種族|species)\s*:\s*', '', line, flags=re.I)
        sid = resolve(cleaned)
        if sid:
            if section['species'] != [sid] or section['ivs']:
                change_section([sid])
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
            if not {*FIELDS, 'atk', 'def', 'hp'} <= row.keys():
                raise ValueError('CSVにはspecies,fast,charged1,charged2,atk,def,hp列が必要です')
            sid = resolve(row['species'])
            if not sid:
                raise ValueError(f'{number}行目: ポケモンが見つかりません')
            change_section([sid], tuple(row[k].upper() for k in FIELDS[1:]), force=True)
            add_iv([row[k] for k in ('atk', 'def', 'hp')], number)
            # Only an explicitly observed CP is a search constraint. A simulator's
            # generic `cp` column may be powered-up CP and must never be inferred.
            if row.get('source_cp'):
                add_record(section['ivs'][-1], row['source_cp'], row.get('source_species') or row['species'], number)
            section['levels'] = 'level' in row
            continue
        if len(fields) in (4, 7, 8) and resolve(fields[0]):
            sid, moves = resolve(fields[0]), tuple(x.upper() for x in fields[1:4])
            if len(fields) == 4 and section['species'] == [sid] and section['moves'] is None:
                section['moves'] = moves
            else:
                change_section([sid], moves, force=section['species'] is not None)
            if len(fields) in (7, 8):
                add_iv(fields[-3:], number)
                section['levels'] = len(fields) == 8
            continue
        if len(fields) == 3 and all(re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', x) for x in fields):
            if section['moves'] is not None and section['ivs'] and section['moves'] != tuple(x.upper() for x in fields):
                raise ValueError('同じ区間内に異なる技指定があります。見出しで区間を分けてください')
            section['moves'] = tuple(x.upper() for x in fields)
            continue
        raise ValueError(f'{number}行目を読み取れません: {line[:80]}。分からない部分を修正してください')
    def valid(sid, moves):
        p = species[sid]
        return (len(moves) == 3 and moves[0] in p.get('fastMoves', [])
                and all(x in p.get('chargedMoves', []) for x in moves[1:]) and moves[1] != moves[2])
    jobs, notices = {}, []
    for index, part in enumerate(sections):
        if not part['ivs']:
            if part['moves'] is not None:
                raise ValueError('技を指定した区間に個体値がありません。対象の見出しと同じ区間に置いてください')
            continue
        sids = part['species'] or [current.get('species')]
        for observed_sid in sids:
            sid = battle_entry_species(observed_sid, species)
            if sid not in species:
                raise ValueError('個体値に対応するポケモンを指定してください')
            p, warnings = species[sid], []
            entry_notice = battle_entry_notice(observed_sid)
            if entry_notice:
                warnings.append(entry_notice)
            if part['species'] is None:
                warnings.append('ポケモン名の指定がないため現在フォームの種類を使います')
            moves, source = part['moves'], '入力で指定'
            if moves is None:
                if part['species'] is None and sid == current.get('species') and all(current.get(k) for k in FIELDS[1:]):
                    moves = tuple(current[k].upper() for k in FIELDS[1:])
                    source = '現在フォームの技構成'
                elif p.get('default_moves'):
                    moves = tuple(p['default_moves'][k] for k in FIELDS[1:])
                    source = p.get('default_moves_source', 'PvPoke GL推奨技')
                else:
                    choices = {tuple(v[k] for k in FIELDS[1:]) for v in presets if v['species'] == sid}
                    if len(choices) != 1:
                        raise ValueError(f'{p.get("name_ja") or p.get("name") or sid}: 検証済みの推奨技がありません。この種類だけ技構成を指定してください')
                    moves = next(iter(choices))
                    source = '登録済みの唯一の技構成'
                warnings.append('技省略: ' + source + ' → ' + ','.join(moves))
            if not valid(sid, moves):
                raise ValueError(f'{p.get("name_ja") or sid}: 技構成が現在のPvPokeデータと一致しません')
            key = (sid, *moves)
            if key not in jobs:
                jobs[key] = {'candidate': dict(zip(FIELDS, key)), 'name': p.get('name_ja') or p.get('name') or sid,
                             '_ivs': [], 'warnings': [], 'source_sections': [], 'moves_source': source, 'source_records': []}
            job = jobs[key]
            job['_ivs'].extend(part['ivs'])
            job['source_records'].extend(part['records'])
            job['source_sections'].append(index)
            if part['levels']:
                warnings.append('貼り付け元のレベルは使わず計算時にCP1500以下へ調整します')
            job['warnings'] = list(dict.fromkeys([*job['warnings'], *warnings]))
    if not jobs:
        raise ValueError('個体値がありません。攻撃,防御,HPの順に貼り付けてください')
    for job in jobs.values():
        job['source_records'] = list({(r['ivs'], r['species'], r['cp']): r for r in job['source_records']}.values())
        original = job.pop('_ivs')
        unique = list(dict.fromkeys(original))
        if len(unique) > MAX_CANDIDATES:
            raise ValueError(job['name'] + f': 1種類・1技構成につき{MAX_CANDIDATES}通りまでです。切り捨てずに入力を分けてください')
        if len(unique) != len(original):
            job['warnings'].append(f'重複する個体値{len(original)-len(unique)}件をまとめました')
        job.update(ivs='\n'.join(','.join(map(str, iv)) for iv in unique),
                   candidate_count=len(unique), batch_mode=mode)
    values = list(jobs.values())
    output = {'jobs': values, 'group_count': len(values), 'batch_mode': mode,
              'total_candidate_count': sum(x['candidate_count'] for x in values), 'warnings': notices}
    if len(values) == 1:
        output.update(values[0])
    return output
