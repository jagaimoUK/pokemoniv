#!/usr/bin/env python3
"""Batch PvPoke GL: choose Default-only or 4 opponent IV modes x 6 shields.

Runs one matrix per shield case with four opponent-mode sections, then
splits results into 24 CSVs. Source/custom IVs are NEVER selected implicitly.

Requires pvpoke_batch_v2.py and pvpoke_iv_modes.py in the same directory.
Typical use:
    python pvpoke_24_workflow.py --prepare
    python pvpoke_24_workflow.py --run
Optionally --config JSON of web app's last_input.json and --meta path/to/meta.csv.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import shutil
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pvpoke_batch_v2 as engine
import pvpoke_iv_modes as iv_modes

MODES = ('default', 'rank1', 'attack', 'defense')
BATCH_MODES = {'simple': ('default',), 'detailed': MODES}
SHIELDS = ('s0', 's1', 's2', 'i0y1', 'i0y2', 'i1y2')
IV_FIELDS = ('atk', 'def', 'hp')
POKE_FIELDS = ('species', 'fast', 'charged1', 'charged2')
META_NAME = 'pvpoke_meta_opponents.csv'
DEFAULT_HOME = Path.home() / 'pvpoke_automation_web'


def load_meta(path: Path, species: dict) -> tuple[list[dict], list[dict]]:
    """Keep all valid distinct move sets, including shadows; report every skip."""
    result, errors, seen = [], [], set()
    with path.open(encoding='utf-8-sig', newline='') as stream:
        for line_number, parts in enumerate(csv.reader(stream), start=1):
            if not parts or (len(parts) == 1 and not parts[0].strip()):
                continue
            if len(parts) != 4:
                errors.append({'line': line_number, 'reason': '4列ではありません', 'row': ','.join(parts)})
                continue
            sid = parts[0].strip().lower()
            # PvPoke's export-only '-shadow' suffix isn't part of the species ID.
            if sid.endswith('_shadow-shadow'):
                sid = sid[:-len('-shadow')]
            moves = [part.strip().upper() for part in parts[1:]]
            key = (sid, *moves)
            if key in seen:
                errors.append({'line': line_number, 'reason': '重複', 'row': ','.join(parts)})
                continue
            seen.add(key)
            if sid not in species:
                errors.append({'line': line_number, 'reason': '未登録species', 'row': ','.join(parts)})
                continue
            p = species[sid]
            if moves[0] not in p.get('fastMoves', ()) or any(m not in p.get('chargedMoves', ()) for m in moves[1:]) or moves[1] == moves[2]:
                errors.append({'line': line_number, 'reason': '現在のPvPokeデータにない技', 'row': ','.join(parts)})
                continue
            result.append(dict(zip(POKE_FIELDS, key)))
    if not result:
        raise ValueError('有効な対戦相手が0件です。メタファイルとGameMasterを確認してください')
    return result, errors


def input_config(path: Path) -> tuple[dict, str]:
    obj = json.loads(path.read_text(encoding='utf-8'))
    cand = obj.get('candidate') or {}
    if any(not str(cand.get(key, '')).strip() for key in POKE_FIELDS):
        raise ValueError('config.candidateにはspeciesと技3種類が必要です')
    ivs = str(obj.get('ivs') or '').replace('，', ',').replace('、', ',')
    parsed, seen = [], set()
    for number, line in enumerate(ivs.splitlines(), start=1):
        if not line.strip():
            continue
        pieces = [piece.strip() for piece in line.split(',')]
        if len(pieces) != 3 or not all(s.isdecimal() and 0 <= int(s) <= 15 for s in pieces):
            raise ValueError(f'自分の{number}行目が不正。攻撃,防御,HPの3値（0〜15）が必要です')
        item = tuple(map(int, pieces))
        if item in seen:
            raise ValueError(f'自分の{number}行目が重複しています: {item}')
        seen.add(item)
        parsed.append(item)
    if not 1 <= len(parsed) <= 150:
        raise ValueError('自分の個体値は1〜150体にしてください')
    return {k: str(cand[k]).strip() for k in POKE_FIELDS}, '\n'.join(','.join(map(str, iv)) for iv in parsed)


def generate_rows(meta: list[dict], species: dict, cpms: list, *, full_modes=MODES):
    rows, report, errors = [], [], []
    for mode in full_modes:
        for idx, opponent in enumerate(meta):
            try:
                sid = opponent['species']
                ivs = iv_modes.select_opponent_ivs(species[sid], cpms, mode,
                    moves=[opponent['fast'], opponent['charged1'], opponent['charged2']],
                    cp_cap=1500, level_cap=engine.MAX_LEVEL)
                iv_row = {**opponent, **dict(zip(IV_FIELDS, ivs[:3])), 'level_override': ivs[3]}
                prepared = engine.optimize([iv_row], species, cpms, f'{sid}/{mode}')[0]
                rows.append(iv_row)
                report.append({'mode': mode, 'meta_index': idx + 1, **opponent,
                    'atk': ivs[0], 'def': ivs[1], 'hp': ivs[2],
                    'level': prepared['level'], 'cp': prepared['cp']})
            except (KeyError, TypeError, ValueError) as error:
                errors.append({'mode': mode, 'meta_index': idx+1, **opponent, 'reason': str(error)})
    counts = {mode: sum(row['mode'] == mode for row in report) for mode in full_modes}
    if not all(counts.values()):
        raise ValueError(f'個体値モードのいずれかが0件です: {counts}')
    return rows, report, errors, counts


def write_csv(path, columns, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as fp:
        writer = csv.writer(fp)
        writer.writerow(columns)
        writer.writerows(data)


def split_matrix(raw_dir: Path, output: Path, mode_report: list[dict], candidates: list[dict], *, full_modes=MODES):
    """Convert six multi-mode matrices to 6 or 24 files, with exact averages.

    W/L/D in the 24 files are derived from Battle Rating vs 500 and are labeled
    as *estimated* (not copied from PvPoke's match-outcome counters).
    """
    groups = defaultdict(list)
    for idx, row in enumerate(mode_report):
        groups[row['mode']].append(idx)
    accumulated = defaultdict(lambda: {'ratings': [], 'equal': [], 'disadvantage': []})
    generated = []
    for shield in SHIELDS:
        original = raw_dir / ('pvpoke_' + shield + '.csv')
        with original.open(encoding='utf-8-sig', newline='') as fp:
            table = list(csv.reader(fp))
        expected = len(mode_report) + 5
        if len(table) != len(candidates) + 1 or any(len(row) != expected for row in table):
            raise ValueError(f'{original.name}: 期待する表サイズではありません')
        for mode in full_modes:
            indices = groups[mode]
            out_rows = []
            for cidx, row in enumerate(table[1:]):
                vals = [float(row[1 + idx]) for idx in indices]
                if any(not math.isfinite(value) or not 0 <= value <= 1000 for value in vals):
                    raise ValueError(f'{original.name}: 不正なBattle Ratingがあります')
                wins = sum(v > 500 for v in vals)
                losses = sum(v < 500 for v in vals)
                ties = len(vals) - wins - losses
                avg = round(sum(vals) / len(vals), 2)
                out_rows.append([row[0], *[row[1 + idx] for idx in indices], wins, losses, ties, avg])
                key = (cidx, mode)
                accumulated[key]['ratings'].extend(vals)
                target = 'disadvantage' if shield.startswith('i') else 'equal'
                accumulated[key][target].extend(vals)
            name = f'{mode}_{shield}.csv'
            write_csv(output / name,
                      ['candidate', *[table[0][idx+1] for idx in indices],
                       'rating_gt500', 'rating_lt500', 'rating_eq500', 'mean_rating'], out_rows)
            generated.append(output / name)
    summary = []
    for cidx, cand in enumerate(candidates):
        for mode in full_modes:
            values = accumulated[(cidx, mode)]
            vals = values['ratings']
            eq = values['equal']
            disadvantage = values['disadvantage']
            summary.append([*([cand[k] for k in POKE_FIELDS] + [cand[k] for k in IV_FIELDS]), mode,
                            len(vals), round(sum(vals)/len(vals), 2), round(min(vals), 2),
                            round(sum(v > 500 for v in vals)/len(vals), 4),
                            round(sum(eq)/len(eq), 2), round(sum(disadvantage)/len(disadvantage), 2)])
    write_csv(output / 'ranking_summary.csv',
              [*POKE_FIELDS, *IV_FIELDS, 'opponent_iv_mode', 'matchups', 'mean_rating',
               'min_rating', 'fraction_gt500', 'equal_shields_mean', 'disadvantage_shields_mean'], summary)
    generated.append(output / 'ranking_summary.csv')
    return generated


def record_cache_stats(engine_manifest_path: Path, batch_manifest_path: Path):
    """Include real cache usage in the final durable ZIP manifest."""
    engine_manifest = json.loads(engine_manifest_path.read_text(encoding='utf-8'))
    batch_manifest = json.loads(batch_manifest_path.read_text(encoding='utf-8'))
    cache_stats = engine_manifest.get('matchup_cache', {'enabled': False})
    if not isinstance(cache_stats, dict):
        raise ValueError('Engine cache stats are not an object')
    batch_manifest['matchup_cache'] = cache_stats
    engine_stats = engine_manifest.get('engine', {'selected': 'legacy'})
    if not isinstance(engine_stats, dict):
        raise ValueError('Engine metadata is not an object')
    batch_manifest['engine'] = engine_stats
    temp = batch_manifest_path.with_suffix('.tmp')
    try:
        temp.write_text(json.dumps(batch_manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(batch_manifest_path)
    finally:
        temp.unlink(missing_ok=True)


def main():
    p = argparse.ArgumentParser(description='PvPoke対戦相手4モード×6シールド 一括実行')
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument('--prepare', action='store_true', help='計算前確認のみ。PvPoke Matrixは起動しない')
    grp.add_argument('--run', action='store_true', help='6または24条件を計算してZIPを作成')
    p.add_argument('--config', type=Path, default=DEFAULT_HOME / 'last_input.json')
    p.add_argument('--batch-mode', choices=tuple(BATCH_MODES), default='simple',
                   help='simple = Default IV only (6); detailed = 4 IV modes (24)')
    p.add_argument('--meta', type=Path, default=Path(__file__).resolve().parent / META_NAME)
    p.add_argument('--output', type=Path, default=Path.home() / 'pvpoke_24_results')
    args = p.parse_args()
    cand, iv_text = input_config(args.config)
    gm, cpms, species = engine.game_data()
    species_id = cand['species'].lower()
    if species_id not in species:
        raise ValueError(f'自分のポケモンIDがGameMasterにありません: {species_id}')
    own = dict(zip(POKE_FIELDS, [species_id, *(cand[k].upper() for k in POKE_FIELDS[1:])]))
    own_rows = [{**own, **dict(zip(IV_FIELDS, map(int, iv.split(','))))} for iv in iv_text.splitlines()]
    own_prepared = engine.optimize(own_rows, species, cpms, 'candidates.csv')
    meta, source_errors = load_meta(args.meta, species)
    selected_modes = BATCH_MODES[args.batch_mode]
    rows, opponent_report, mode_errors, counts = generate_rows(meta, species, cpms,
                                                              full_modes=selected_modes)
    target = args.output.resolve()
    target.mkdir(parents=True, exist_ok=True)
    write_csv(target / 'opponent_modes_report.csv',
              ['mode','meta_index',*POKE_FIELDS,*IV_FIELDS,'level','cp'],
              [[r[k] for k in ['mode','meta_index',*POKE_FIELDS,*IV_FIELDS,'level','cp']] for r in opponent_report])
    errors = [{'stage':'meta', **e} for e in source_errors] + [{'stage':'mode', **e} for e in mode_errors]
    (target / 'excluded_rows.json').write_text(json.dumps(errors, ensure_ascii=False, indent=2), encoding='utf-8')
    (target / 'manifest.json').write_text(json.dumps({
        'created_at': datetime.now(timezone.utc).isoformat(),
        'source_file': args.meta.name, 'gamemaster_timestamp': gm.get('timestamp'),
        'cp_cap': engine.CP_CAP, 'max_level': engine.MAX_LEVEL,
        'batch_mode': args.batch_mode,
        'opponent_iv_modes': list(selected_modes),
        'shield_pairs': [list(pair) for pair in engine.SCENARIOS['all']],
        'source_lines': len(meta) + len(source_errors), 'valid_source_rows': len(meta),
        'mode_counts': counts, 'excluded': len(errors),
        'candidates': len(own_rows), 'shield_cases': list(SHIELDS),
        'note': 'Each base matrix uses the selected opponent modes. Source IVs are never automatically chosen. S/A grades require GPT analysis.'
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'自分{len(own_prepared)}体 / 有効なメタ技構成{len(meta)}行 / 対戦相手のモード合計{len(rows)}行')
    print('モード別:', counts, '無効・除外:', len(errors))
    print('想定評価回数:', len(own_rows) * len(rows) * 6)
    if args.prepare:
        print('準備完了。計算はまだ開始していません。レポート:', target)
        return
    # Isolate artifacts and leave the existing web application untouched.
    job = target / 'engine_job'
    job.mkdir(exist_ok=True)
    prev = (engine.DIR, engine.OUT, engine.CAND, engine.OPPS, engine.DATA)
    try:
        engine.DIR = job
        engine.OUT = job / 'results'
        engine.CAND = job / 'candidates.csv'
        engine.OPPS = job / 'opponents.csv'
        engine.DATA = prev[4]
        write_csv(engine.CAND, engine.HEADER,
                  [[row[k] for k in engine.HEADER] for row in own_rows])
        write_csv(engine.OPPS, engine.HEADER + ['level_override'],
                  [[row[k] for k in engine.HEADER] + [row['level_override']] for row in rows])
        print('PvPoke Matrixで全6シールドを実行します。', flush=True)
        engine.run(shield_set='all')
        runs = sorted((job / 'results').glob('run_*/manifest.json'), key=lambda p: p.stat().st_mtime)
        if not runs:
            raise RuntimeError('シミュレーションの結果が生成されませんでした')
        latest = runs[-1].parent
        record_cache_stats(latest / 'manifest.json', target / 'manifest.json')
        outfiles = split_matrix(latest, target, opponent_report, own_rows,
                                full_modes=selected_modes)
        (target / 'GPT_REVIEW.txt').write_text(
            f'個体値厳選: ranking_summary.csvと{len(selected_modes) * 6}本のmode_shield CSVを比較して、\n'
            '優劣だけでなく重要対面、S0/S1/S2、不利シールドを総合評価してください。\n'
            'S/Aランクを決める際は、採用候補の先頭ポケモンとその裏を想定してください。\n'
            'rating_gt500等はBattle Ratingに基づく参考値であり、PvPoke自身の勝敗数とは区別してください。\n'
            '情報源個体値は自動採用していません。\n', encoding='utf-8')
        outfiles += [target/'opponent_modes_report.csv', target/'excluded_rows.json',
                     target/'manifest.json', target/'GPT_REVIEW.txt']
        zip_path = target / 'pvpoke_24_conditions.zip'
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as archive:
            for item in outfiles:
                archive.write(item, arcname=item.name)
        print('完成:', zip_path)
    finally:
        engine.DIR, engine.OUT, engine.CAND, engine.OPPS, engine.DATA = prev


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print('ERROR:', error, file=sys.stderr)
        sys.exit(1)