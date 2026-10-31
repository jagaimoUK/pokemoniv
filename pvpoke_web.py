#!/usr/bin/env python3
"""Local-only, mobile-friendly PvPoke Matrix launcher for Termux.

Requires pvpoke_batch_v2.py in the same folder and websocket-client for running.
Starts a local HTTP server on 127.0.0.1:8765, never exposed to a LAN.
"""
from __future__ import annotations

from pvpoke_input_limits import MAX_CANDIDATES, MAX_IMPORT_CHARS, MAX_APP_REQUEST_BYTES

import argparse
import csv
from collections import deque
from datetime import datetime
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import pvpoke_batch_v2 as engine
import pvpoke_iv_modes as iv_modes
import pvpoke_archive as archives
import pvpoke_result_cache as result_cache
from pvpoke_calculation_version import calculation_version, content_hash, force_recalculate
import pvpoke_meta_live as meta_live
import pvpoke_meta_presets as meta_presets
import pvpoke_flashcards as flashcards
import pvpoke_meta_variants as meta_variants
from pvpoke_party_backend import PartyBuilder
from pvpoke_app_input import app_presets
from pvpoke_app_catalog import enrich_catalog
from pvpoke_flashcards import public_catalog

HOST = '127.0.0.1'
PORT = 8765
HOME = Path.home()
ROOT = (HOME / 'storage' / 'downloads') if (HOME / 'storage' / 'downloads').exists() else HOME
WORK = ROOT / 'pvpoke_automation_web'
CAND = WORK / 'candidates.csv'
OPPS = WORK / 'opponents.csv'
LAST_CONFIG = WORK / 'last_input.json'
LATEST_ZIP = WORK / 'pvpoke_results_latest.zip'
BATCH_CONFIG = WORK / 'batch24_input.json'
BATCH_OUTPUT = WORK / 'batch24_results'
MAX_CAND = MAX_CANDIDATES
MAX_OPPS = 100
PARTY = PartyBuilder(WORK)
PRESETS = [
    ('マリルリ', 'azumarill', 'BUBBLE', 'ICE_BEAM', 'PLAY_ROUGH'),
    ('オーダイル', 'feraligatr', 'SHADOW_CLAW', 'HYDRO_CANNON', 'ICE_BEAM'),
    ('ドオー', 'clodsire', 'POISON_STING', 'EARTHQUAKE', 'STONE_EDGE'),
    ('デカヌチャン', 'tinkaton', 'FAIRY_WIND', 'GIGATON_HAMMER', 'BULLDOZE'),
    ('ガラルサニーゴ', 'corsola_galarian', 'ASTONISH', 'NIGHT_SHADE', 'POWER_GEM'),
    ('カラマネロ', 'malamar', 'PSYWAVE', 'FOUL_PLAY', 'SUPERPOWER'),
    ('ヌオー', 'quagsire', 'MUD_SHOT', 'AQUA_TAIL', 'STONE_EDGE'),
    ('チルタリス', 'altaria', 'DRAGON_BREATH', 'SKY_ATTACK', 'MOONBLAST'),
]

# Status data is process-local; output ZIP survives server restarts.
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.RLock()
STATUS = {
    'state': 'idle', 'message': '入力を準備してね', 'logs': deque(maxlen=120),
    'exit_code': None, 'started_at': None, 'finished_at': None, 'batch24': False,
}
CATALOG = {'ready': False, 'error': None, 'species': {}, 'presets': [], 'timestamp': None}


def configure_engine():
    """Keep existing engine and game data, but isolate web inputs/output from previous tests."""
    engine.DIR = WORK
    engine.OUT = WORK / 'results'
    engine.CAND = CAND
    engine.OPPS = OPPS
    # Reuse already fetched game data to avoid unnecessary network transfers.
    engine.DATA = ROOT / 'pvpoke_automation' / 'game_data'
    WORK.mkdir(parents=True, exist_ok=True)


def load_catalog():
    try:
        configure_engine()
        gm, cpms, species = engine.game_data()
        payload = {
            sid: {
                'name': p.get('speciesName'),
                'dex': p.get('dex'),
                'baseStats': p.get('baseStats'),
                'types': p.get('types', []),
                'fastMoves': p.get('fastMoves', []),
                'chargedMoves': engine.charged_move_pool(p),
            }
            for sid, p in species.items()
        }
        presets = []
        enrich_catalog(payload, species)
        for ja, sid, fast, c1, c2 in PRESETS:
            p = payload.get(sid)
            if not p:
                continue
            if fast not in p['fastMoves'] or c1 not in p['chargedMoves'] or c2 not in p['chargedMoves']:
                # Never silently substitute a different move set.
                continue
            presets.append({'name': ja, 'species': sid,
                            'fast': fast, 'charged1': c1, 'charged2': c2})
        # Share the already-bundled Japanese move dictionary with the Party UI.
        # Persist only canonical move IDs; localized labels never enter calculations.
        move_ja = public_catalog().get('moves', {})
        with LOCK:
            CATALOG.update({'ready': True, 'error': None, 'species': payload,
                            'moves': {m['moveId']: {**{k: m[k] for k in (
                                'type', 'power', 'energy', 'energyGain', 'cooldown',
                                'buffs', 'buffTarget', 'buffApplyChance') if k in m},
                                'name': m.get('name') or m['moveId'],
                                'name_ja': move_ja.get(m['moveId'], {}).get('ja')}
                                      for m in gm.get('moves', []) if m.get('moveId')},
                            'presets': presets, 'timestamp': gm.get('timestamp')})
        meta_variants.start(WORK, LOCK, STATUS)
    except Exception as exc:
        with LOCK:
            CATALOG.update({'ready': False, 'error': str(exc)})


def parse_ivs(raw):
    if not isinstance(raw, str):
        raise ValueError('個体値リストがありません')
    lines = [s.strip() for s in raw.replace('，', ',').replace('、', ',').splitlines() if s.strip()]
    if not lines or len(lines) > MAX_CAND:
        raise ValueError(f'自分の個体値は1〜{MAX_CAND}体で入力してください')
    result, seen = [], set()
    for n, line in enumerate(lines, 1):
        parts = line.split(',')
        if len(parts) != 3 or any(not s.strip().isdigit() for s in parts):
            raise ValueError(f'{n}行目は「0,15,15」の形式で入力してください')
        iv = tuple(int(s.strip()) for s in parts)
        if any(not 0 <= v <= 15 for v in iv):
            raise ValueError(f'{n}行目: 個体値は0〜15です')
        if iv in seen:
            raise ValueError(f'{n}行目: 同じ個体値 {iv} が重複しています')
        seen.add(iv)
        result.append(iv)
    return result


def normalize_pokemon(row, species, label):
    if not isinstance(row, dict):
        raise ValueError(f'{label}の内容が正しくありません')
    sid = str(row.get('species') or '').strip().lower()
    p = species.get(sid)
    if not p:
        raise ValueError(f'{label}: ポケモンID「{sid}」が見つかりません')
    moves = [str(row.get(key) or '').strip().upper() for key in ('fast', 'charged1', 'charged2')]
    if moves[0] not in p['fastMoves']:
        raise ValueError(f'{label}: 通常技 {moves[0]} は選択できません')
    if any(m not in p['chargedMoves'] for m in moves[1:]) or moves[1] == moves[2]:
        raise ValueError(f'{label}: ゲージ技2つを別々に正しく選択してください')
    return [sid, *moves]


def prepare_payload(payload):
    with LOCK:
        if not CATALOG['ready']:
            raise ValueError('ゲームデータがまだ読み込まれていません')
        catalog = CATALOG['species']
    if not isinstance(payload, dict):
        raise ValueError('入力形式が正しくありません')
    species = normalize_pokemon(payload.get('candidate'), catalog, '自分のポケモン')
    ivs = parse_ivs(payload.get('ivs'))
    opponents = payload.get('opponents')
    if not isinstance(opponents, list) or not 1 <= len(opponents) <= MAX_OPPS:
        raise ValueError(f'対戦相手を1〜{MAX_OPPS}体登録してください')

    # Only these four modes are automatic. Source IVs require an explicit
    # per-opponent iv_mode='source', even when source data contains IVs.
    requested_mode = payload.get('opponent_iv_mode')
    global_mode = str(requested_mode).strip().lower() if requested_mode is not None else ''
    if global_mode and global_mode not in iv_modes.AUTO_IV_MODES:
        raise ValueError('共通の自動個体値設定は default / rank1 / attack / defense の4種類です')
    scenario = str(payload.get('shields') or 'all')
    if scenario not in engine.SCENARIOS:
        raise ValueError('シールド条件が正しくありません')

    _, cpms, full_species = engine.game_data()
    crows = [species + list(iv) for iv in ivs]
    orows, odict, saved_opponents, modes = [], [], [], []
    iv_names = ('atk', 'def', 'hp')

    def numeric_ivs(raw, label):
        if not isinstance(raw, dict) or any(k not in raw or raw[k] is None or str(raw[k]).strip() == '' for k in iv_names):
            raise ValueError(f'{label}: 攻撃・防御・HPを3つとも指定してください')
        values = []
        for key in iv_names:
            value = raw[key]
            if isinstance(value, bool) or not str(value).strip().isdigit():
                raise ValueError(f'{label}: 個体値は0〜15の整数です')
            number = int(value)
            if not 0 <= number <= 15:
                raise ValueError(f'{label}: 個体値は0〜15です')
            values.append(number)
        return values

    for i, row in enumerate(opponents, 1):
        mons = normalize_pokemon(row, catalog, f'相手{i}体目')
        if not isinstance(row, dict):
            raise ValueError(f'相手{i}体目: 入力が不正です')
        any_direct_iv = any(k in row and row[k] is not None and str(row[k]).strip() != '' for k in iv_names)
        full_direct_iv = all(k in row and row[k] is not None and str(row[k]).strip() != '' for k in iv_names)
        direct_values = numeric_ivs(row, f'相手{i}体目') if full_direct_iv else None

        source_raw = row.get('source_ivs')
        if source_raw is not None:
            source_values = numeric_ivs(source_raw, f'相手{i}体目の情報源個体値')
        elif direct_values is not None and str(row.get('iv_mode') or '').strip().lower() not in iv_modes.AUTO_IV_MODES:
            # Only manual/legacy fields may represent source IVs. Old client schemas
            # require dummy ATK/DEF/HP for auto modes; never persist those as source.
            source_values = list(direct_values)
        else:
            source_values = None

        explicit_mode = str(row.get('iv_mode') or '').strip().lower()
        if explicit_mode == 'inherit':
            explicit_mode = ''
        if explicit_mode and explicit_mode not in iv_modes.IV_MODES:
            raise ValueError(f'相手{i}体目: 未対応の個体値モード {explicit_mode}')
        if explicit_mode:
            mode = explicit_mode
        elif global_mode:
            # A selected automatic mode overrides existing source IVs.
            mode = global_mode
        else:
            # Preserve old integrations which passed three explicit IVs and no mode.
            mode = 'custom' if any_direct_iv else 'default'

        level_override = None
        if mode == 'source':
            if source_values is None:
                raise ValueError(f'相手{i}体目: 情報源の個体値が未登録です。手動で指定してください')
            values = source_values
        elif mode == 'custom':
            if direct_values is None:
                raise ValueError(f'相手{i}体目: 直接指定には攻撃・防御・HPの3値が必要です')
            values = direct_values
        else:
            poke = full_species[mons[0]]
            try:
                attack, defense, hp, level_override = iv_modes.select_opponent_ivs(
                    poke, cpms, mode, moves=mons[1:],
                    cp_cap=engine.CP_CAP, level_cap=engine.MAX_LEVEL,
                )
            except ValueError as exc:
                raise ValueError(f'相手{i}体目: {exc}') from exc
            values = [attack, defense, hp]

        full_row = mons + values
        orows.append(full_row + [level_override if level_override is not None else ''])
        prepared = dict(zip(engine.HEADER, full_row))
        if level_override is not None:
            prepared['level_override'] = level_override
        odict.append(prepared)
        saved = dict(zip(engine.HEADER[:4], mons))
        # Remember manual choices, but never silently promote source IVs.
        manual_selected = bool(explicit_mode) or (not global_mode and mode == 'custom')
        saved['iv_mode'] = mode if manual_selected else 'inherit'
        saved['manual_override'] = manual_selected
        if source_values is not None:
            saved['source_ivs'] = dict(zip(iv_names, source_values))
        if mode == 'custom':
            saved.update(dict(zip(iv_names, values)))
        saved_opponents.append(saved)
        modes.append(mode)

    cdict = [dict(zip(engine.HEADER, row)) for row in crows]
    cand_prepared = engine.optimize(cdict, full_species, cpms, 'candidates.csv')
    opp_prepared = engine.optimize(odict, full_species, cpms, 'opponents.csv')
    cleaned = {
        'candidate': dict(zip(engine.HEADER[:4], species)),
        'ivs': '\n'.join(','.join(map(str, iv)) for iv in ivs),
        'opponents': saved_opponents,
        'opponent_iv_mode': global_mode or 'default',
        'shields': scenario,
    }
    preview = {
        'candidates': [{'ivs': f'{p["atk"]}/{p["def"]}/{p["hp"]}',
                        'level': p['level'], 'cp': p['cp']} for p in cand_prepared],
        'opponents': [{'species': p['species'], 'ivs': f'{p["atk"]}/{p["def"]}/{p["hp"]}',
                       'level': p['level'], 'cp': p['cp'], 'iv_mode': mode}
                      for p, mode in zip(opp_prepared, modes)],
        'battles': len(crows) * len(orows) * len(engine.SCENARIOS[scenario]),
        'candidate_count': len(crows), 'opponent_count': len(orows),
    }
    return cleaned, crows, orows, preview


def save_input(cleaned, crows, orows):
    WORK.mkdir(parents=True, exist_ok=True)
    for path, rows in ((CAND, crows), (OPPS, orows)):
        tmp = path.with_suffix('.csv.tmp')
        with tmp.open('w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(engine.HEADER + (['level_override'] if path == OPPS else []))
            writer.writerows(rows)
        tmp.replace(path)
    tmp = LAST_CONFIG.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(LAST_CONFIG)


def worker(shields):
    configure_engine()
    print('準備: 自分/相手の個体値をCP1500以下に調整', flush=True)
    engine.run(shield_set=shields)
    print('DONE:', LATEST_ZIP, flush=True)


def background_run(shields, batch24=False, batch_mode='simple', meta_file=None, cache_context=None, force=False):
    if batch24:
        command = [sys.executable, '-u', str(Path(__file__).resolve().parent / 'pvpoke_24_workflow.py'),
                   '--run', '--config', str(BATCH_CONFIG), '--output', str(BATCH_OUTPUT),
                   '--batch-mode', batch_mode, '--meta', str(meta_file or meta_live.active_path(WORK))]
    else:
        command = [sys.executable, str(Path(__file__).resolve()), '--worker', shields]
    try:
        p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, bufsize=1, cwd=str(HOME),
                             env={**os.environ, **({"PVP_FORCE_RECALCULATE":"1"} if force else {})})
        for line in p.stdout:
            line = line.rstrip('\r\n')
            if not line:
                continue
            with LOCK:
                STATUS['logs'].append(line)
                STATUS['message'] = line[-180:]
        code = p.wait()
        if code == 0 and batch24:
            # Verify all 24 files and atomically save the final ZIP first.
            # Only after durable save succeeds may we remove the temporary
            # browser CSV chunks and extracted results.
            archived = archives.preserve_and_cleanup(BATCH_OUTPUT, WORK)
            # Cache storage is best-effort; a valid completed calculation stays valid.
            if cache_context and calculation_version(engine.DATA) == cache_context['request']['calculation_version']:
                try:
                    saved = result_cache.ResultCache.configured(WORK)
                    if saved is not None:
                        saved.store(cache_context, archived)
                except (OSError, ValueError, TypeError, KeyError, __import__('zipfile').BadZipFile) as exc:
                    print(f'Result cache skipped: {exc}', flush=True)
            BATCH_CONFIG.unlink(missing_ok=True)
        result_zip = archives.archived_latest(WORK) if batch24 else LATEST_ZIP
        with LOCK:
            STATUS['exit_code'] = code
            STATUS['batch24'] = bool(batch24)
            STATUS['state'] = 'done' if code == 0 and result_zip is not None and result_zip.is_file() else 'error'
            STATUS['finished_at'] = datetime.now().isoformat(timespec='microseconds')
            STATUS['message'] = 'ZIPが完成しました' if STATUS['state']=='done' else '計算が中断されました。ログを確認してね'
    except Exception as exc:
        with LOCK:
            STATUS['logs'].append(f'ERROR: {exc}')
            STATUS['state'] = 'error'
            STATUS['message'] = str(exc)
            STATUS['finished_at'] = datetime.now().isoformat(timespec='microseconds')


HTML = r'''<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>PvPoke 個体値シミュレーター</title>
<style>
:root{font-family:system-ui,-apple-system,"Noto Sans JP",sans-serif;color-scheme:dark;--bg:#101827;--card:#1b2738;--line:#34455c;--txt:#edf5ff;--sub:#a4b6cb;--blue:#69b8ff;--accent:#96debf}
*{box-sizing:border-box}body{margin:0;background:linear-gradient(155deg,#13263c 0%,#101827 43%,#101827 100%);color:var(--txt);line-height:1.5}main{max-width:830px;margin:auto;padding:18px 14px 70px}
header{margin:5px 0 25px}.eyebrow{font-size:12px;letter-spacing:.15em;color:var(--accent);font-weight:700}h1{font-size:clamp(23px,5vw,34px);letter-spacing:-.025em;margin:5px 0 6px}h2{font-size:19px;margin:0 0 8px}p{margin:4px 0 12px;color:var(--sub)}.tiny{font-size:12px}.steps{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}.step{border:1px solid var(--line);padding:6px 10px;border-radius:20px;color:var(--sub);font-size:12px}.step.current{color:var(--accent);border-color:#518876}
.card{background:var(--card);border:1px solid var(--line);border-radius:17px;padding:17px;margin-bottom:14px;box-shadow:0 8px 24px #05091015}.head{display:flex;align-items:center;gap:9px;margin-bottom:12px}.num{width:26px;height:26px;background:#284b69;color:#a7dcff;border-radius:9px;display:grid;place-items:center;font-weight:750;font-size:13px}
label{display:block;font-size:13px;color:#d0ddec;font-weight:650;margin:10px 0 5px}input,textarea,select{width:100%;min-height:43px;border:1px solid #4b627c;border-radius:10px;background:#121d2d;color:var(--txt);padding:10px 11px;font:inherit;font-size:14px;outline:0}input:focus,textarea:focus,select:focus{border-color:var(--blue);box-shadow:0 0 0 2px #69b8ff33}textarea{font-family:ui-monospace,monospace;resize:vertical;line-height:1.75;min-height:118px}.two{display:grid;grid-template-columns:1fr 1fr;gap:10px}.three{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.opponent{padding:12px;border:1px solid #40536c;border-radius:13px;margin-bottom:10px;background:#152134}.rowtop{display:flex;align-items:center;justify-content:space-between;gap:8px}.muted{color:var(--sub);font-size:12px}button,.download{border:1px solid #6c9ac4;color:#fff;background:#285780;border-radius:11px;padding:11px 15px;font:inherit;font-weight:700;cursor:pointer;text-decoration:none;display:inline-block;text-align:center}button:hover,.download:hover{filter:brightness(1.08)}button:disabled{opacity:.5;cursor:not-allowed}.outline{background:transparent;border-color:#516b86}.danger{background:transparent;border-color:#72555f;color:#f7c1c4}.primary{background:#2774b9;border:1px solid #408fd6;padding:14px 17px}.actions{display:flex;gap:9px;flex-wrap:wrap;margin-top:15px}.actions>*{flex:1}.download{background:#24765b;border-color:#5caf86}details{margin-top:14px}summary{color:var(--blue);cursor:pointer}pre{background:#0b1220;border:1px solid #2d4058;border-radius:10px;color:#cde7fb;white-space:pre-wrap;word-break:break-word;font-size:12px;padding:13px;min-height:54px;max-height:315px;overflow:auto}.message{border-radius:10px;padding:11px 13px;margin:12px 0;font-size:14px;background:#23384c}.message.error{background:#552a32;color:#ffe4e5}.message.good{background:#214538;color:#d0ffe7}.stat{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}.stat div{border:1px solid var(--line);padding:10px;border-radius:10px;text-align:center}.stat b{display:block;font-size:20px}.stat small{color:var(--sub)}[hidden]{display:none!important}footer{font-size:12px;color:var(--sub);padding:0 8px}
@media(max-width:520px){.two{grid-template-columns:1fr}.three{gap:6px}.card{padding:14px}.three label{font-size:12px}.actions>*{flex-basis:100%}}
</style></head><body><main>
<header><div class="eyebrow">LOCAL PVP SIMULATOR</div><h1>PvPoke 個体値一括計算</h1><p>スマホの画面で個体値を入力 → CP調整 → 6条件計算 → ZIP保存。採点はChatGPTで行うよ。</p>
<div class="steps"><span class="step current">1. ポケモン</span><span class="step">2. 個体値</span><span class="step">3. 対戦相手</span><span class="step">4. 計算</span></div></header>
<div id="notice" class="message">PvPokeのゲームデータを読み込んでいるよ…</div>
<section class="card"><div class="head"><div class="num">1</div><h2>自分のポケモン</h2></div>
<label for="preset">よく使うポケモンから選ぶ</label><select id="preset"><option value="">読み込み中…</option></select>
<label for="species">PvPokeの英語ID（直接入力も可能）</label><input id="species" list="species-list" value="azumarill" autocomplete="off"/><datalist id="species-list"></datalist>
<label>技構成</label><div class="three"><div><label for="fast">通常技</label><select id="fast"></select></div><div><label for="charged1">ゲージ技①</label><select id="charged1"></select></div><div><label for="charged2">ゲージ技②</label><select id="charged2"></select></div></div></section>
<section class="card"><div class="head"><div class="num">2</div><h2>個体値を貼り付け</h2></div><p class="tiny">攻撃,防御,HP の順。1行1体、最大4,096通り。重複している個体値はエラーとして表示するよ。</p><textarea id="ivs" spellcheck="false" placeholder="0,15,15&#10;1,15,14&#10;0,14,15">0,15,15&#10;1,15,14</textarea></section>
<section class="card"><div class="head"><div class="num">3</div><h2>対戦相手</h2></div><p class="tiny">自動切り替えは4種類。情報源の個体値は各相手の「手動」設定でのみ使用するよ。最大100体。</p><label for="opponentIVMode">対戦相手の共通個体値設定</label><select id="opponentIVMode"><option value="default">PvPokeデフォルト</option><option value="rank1">総合1位（Stat Product）</option><option value="attack">攻撃最大</option><option value="defense">防御最大</option></select><div id="opponents"></div>
<div class="two"><select id="add-preset" aria-label="追加する対戦相手"><option value="">相手を選ぶ</option></select><button type="button" id="addOpp">＋ 対戦相手を追加</button></div></section>
<section class="card"><div class="head"><div class="num">4</div><h2>計算する</h2></div>
<label for="batchMode">メタポケモンとの比較モード</label><select id="batchMode"><option value="simple">簡易：相手IV Defaultのみ × 6シールド（6条件）</option><option value="detailed">詳細：相手IV4種類 × 6シールド（24条件）</option></select>
<p class="tiny" id="batchModeHint">簡易：Default個体値×6シールド。詳細の約1/4の計算量</p>
<label for="shields">シールド条件</label><select id="shields"><option value="all">全6条件（同数3＋不利3）</option><option value="equal">同数3条件だけ（0-0 / 1-1 / 2-2）</option><option value="disadvantage">不利3条件だけ（0-1 / 0-2 / 1-2）</option></select>
<div class="actions"><button id="preview" class="outline">① CP・対戦数を確認</button><button id="run" class="primary">② 通常6条件を実行</button><button id="run24" class="primary">③ 簡易6条件を実行</button></div><p class="tiny">③は同梱のメタ技構成87行を使います。簡易はDefaultのみ、詳細はDefault/Rank 1/Attack/Defense。どちらも6シールド条件で、情報源IVは自動使用しません。</p>
<div id="previewPanel" hidden><div id="previewStats" class="stat"></div><details><summary>CP調整後のレベルを見る</summary><pre id="previewDetail"></pre></details></div><div id="statusMessage" class="message" hidden></div><pre id="logs" hidden></pre>
<div class="actions"><a id="download" class="download" href="/download" hidden>完成したZIPを保存</a></div></section>
<footer>この画面は端末の 127.0.0.1 だけで公開されるよ。PvPokeの計算結果をCSV化するツールで、勝敗や個体値の最終評価はChatGPTで確認してね。CP上限1500、Lv上限50。</footer></main>
<script>
'use strict';
const TOKEN='__TOKEN__'; let catalog={};let presets=[]; let busy=false;
const el=id=>document.getElementById(id);
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function notice(s,cl=''){let x=el('notice');x.textContent=s;x.className='message '+cl;}
function options(select,vals,selected){select.replaceChildren();for(const value of vals){const o=document.createElement('option');o.value=value;o.textContent=value;select.append(o);}if(vals.includes(selected))select.value=selected;}
function setMoves(sid, sels, desired={}){const p=catalog[sid]||{fastMoves:[],chargedMoves:[]};const f=p.fastMoves,c=p.chargedMoves;options(sels[0],f,desired.fast);options(sels[1],c,desired.charged1);options(sels[2],c,desired.charged2);if(sels[2].value===sels[1].value&&c.length>1)sels[2].value=c.find(v=>v!==sels[1].value);}
function setCandidate(row={}){if(row.species)el('species').value=row.species;setMoves(el('species').value,[el('fast'),el('charged1'),el('charged2')],row);el('preset').value=el('species').value;}
function getPreset(id){return presets.find(p=>p.species===id)||null;}
function addOpponent(row={}){const sid=row.species||(presets[0]&&presets[0].species)||'clodsire';const base=getPreset(sid)||{species:sid};const o={...base,...row};const div=document.createElement('div');div.className='opponent';div.innerHTML=`<div class="rowtop"><b>対戦相手 <span class="idx"></span></b><button type="button" class="danger remove">削除</button></div><label>ポケモン（PvPoke ID）</label><input class="opp-species" list="species-list" value="${esc(sid)}" autocomplete="off"/><div class="three"><div><label>通常技</label><select class="opp-fast"></select></div><div><label>ゲージ技①</label><select class="opp-c1"></select></div><div><label>ゲージ技②</label><select class="opp-c2"></select></div></div><div class="three"><div><label>攻撃</label><input type="number" min="0" max="15" step="1" class="opp-atk" value="${esc(o.atk??0)}"/></div><div><label>防御</label><input type="number" min="0" max="15" step="1" class="opp-def" value="${esc(o.def??15)}"/></div><div><label>HP</label><input type="number" min="0" max="15" step="1" class="opp-hp" value="${esc(o.hp??15)}"/></div></div>`;
const modeLabel=document.createElement('label');modeLabel.textContent='この相手の個体値設定';
const modeSelect=document.createElement('select');modeSelect.className='opp-iv-mode';
for(const [value,label] of [['inherit','共通設定（自動）'],['source','情報源の個体値（手動）'],['custom','直接指定（手動）'],['default','PvPokeデフォルト'],['rank1','総合1位'],['attack','攻撃最大'],['defense','防御最大']]){
const opt=document.createElement('option');opt.value=value;opt.textContent=label;modeSelect.append(opt);}
modeSelect.value=o.manual_override===true&&o.iv_mode&&o.iv_mode!=='inherit'?o.iv_mode:'inherit';
const ivGroup=div.querySelectorAll('.three')[1];ivGroup.classList.add('opp-iv-inputs');ivGroup.before(modeLabel,modeSelect);
modeSelect.addEventListener('change',refreshOpponentIVInputs);
const rawSource=row.source_ivs||(['atk','def','hp'].every(k=>row[k]!==undefined)?{atk:row.atk,def:row.def,hp:row.hp}:null);
if(rawSource)div.dataset.sourceIvs=JSON.stringify(rawSource);
const sourceHint=document.createElement('p');sourceHint.className='muted opp-source-hint';
sourceHint.textContent=rawSource?'情報源の個体値: '+[rawSource.atk,rawSource.def,rawSource.hp].join('/'):'情報源の個体値: 未登録';
modeSelect.after(sourceHint);
const sels=[div.querySelector('.opp-fast'),div.querySelector('.opp-c1'),div.querySelector('.opp-c2')];setMoves(sid,sels,o);
div.querySelector('.opp-species').addEventListener('change',e=>{let p=getPreset(e.target.value)||{};setMoves(e.target.value,sels,p);});div.querySelector('.remove').onclick=()=>{div.remove();renumber();};el('opponents').append(div);renumber();refreshOpponentIVInputs();}
function renumber(){[...el('opponents').children].forEach((d,i)=>d.querySelector('.idx').textContent=String(i+1));}
function refreshOpponentIVInputs(){
for(const div of el('opponents').children){
const mode=div.querySelector('.opp-iv-mode').value;
const effective=mode==='inherit'?el('opponentIVMode').value:mode;
div.querySelector('.opp-iv-inputs').hidden=effective!=='custom';
}}
function gather(){
const opponent_iv_mode=el('opponentIVMode').value;
const opponents=[...el('opponents').children].map(div=>{
const mode=div.querySelector('.opp-iv-mode').value;
const effective=mode==='inherit'?opponent_iv_mode:mode;
const o={species:div.querySelector('.opp-species').value.trim(),
fast:div.querySelector('.opp-fast').value,charged1:div.querySelector('.opp-c1').value,charged2:div.querySelector('.opp-c2').value};
// Only an explicit row choice may activate the source-IV mode.
if(mode!=='inherit')o.iv_mode=mode;
if(div.dataset.sourceIvs)o.source_ivs=JSON.parse(div.dataset.sourceIvs);
if(effective==='custom'){
o.atk=div.querySelector('.opp-atk').value;
o.def=div.querySelector('.opp-def').value;
o.hp=div.querySelector('.opp-hp').value;
}
return o;
});
return {candidate:{species:el('species').value.trim(),fast:el('fast').value,
charged1:el('charged1').value,charged2:el('charged2').value},
ivs:el('ivs').value,shields:el('shields').value,opponent_iv_mode,opponents};
}
async function api(path,data){const args=data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-PvPoke-Token':TOKEN},body:JSON.stringify(data)};const r=await fetch(path,args);const obj=await r.json();if(!r.ok)throw Error(obj.error||'通信エラー');return obj;}
function status(s,kind=''){const x=el('statusMessage');x.hidden=false;x.textContent=s;x.className='message '+kind;}
async function ready(){try{const data=await api('/api/catalog');if(!data.ready){notice(data.error?'データ取得エラー: '+data.error:'ゲームデータを読み込んでいるよ。数秒待ってね。',data.error?'error':'');setTimeout(ready,data.error?8000:1500);return;}catalog=data.species;presets=data.presets;
const names=Object.keys(catalog).sort();let dl=el('species-list');dl.replaceChildren();for(const sid of names){let o=document.createElement('option');o.value=sid;dl.append(o);}
const selectOptions=ps=>[...ps.map(p=>({id:p.species,label:p.name+' ('+p.species+')'}))];for(const id of ['preset','add-preset']){let x=el(id);x.replaceChildren();if(id==='add-preset'){const o=document.createElement('option');o.value='';o.textContent='対戦相手を選ぶ';x.append(o);}for(let p of selectOptions(presets)){const o=document.createElement('option');o.value=p.id;o.textContent=p.label;x.append(o);}}
let cfg=data.saved;if(cfg){setCandidate(cfg.candidate);el('ivs').value=cfg.ivs;el('shields').value=cfg.shields||'all';el('opponentIVMode').value=['default','rank1','attack','defense'].includes(cfg.opponent_iv_mode)?cfg.opponent_iv_mode:'default';for(const o of cfg.opponents)addOpponent(o);}else{const p=getPreset('azumarill')||presets[0];if(p)setCandidate(p);addOpponent(getPreset('clodsire')||presets[0]);}if(presets.length)el('add-preset').value=presets[0].species;notice('準備OK。個体値や相手を確認して計算できるよ。','good');
}catch(e){notice('接続確認: '+e.message,'error');setTimeout(ready,5000);}}
el('preset').addEventListener('change',e=>{const p=getPreset(e.target.value);if(p)setCandidate(p);});el('species').addEventListener('change',e=>setCandidate({species:e.target.value}));
el('opponentIVMode').addEventListener('change',refreshOpponentIVInputs);
el('addOpp').addEventListener('click',()=>{if(el('opponents').children.length>=100){status('対戦相手は最大100体だよ','error');return;}addOpponent(getPreset(el('add-preset').value)||{species:el('add-preset').value});});
function showPreview(p){if(p.batch24){el('previewPanel').hidden=false;el('previewStats').textContent=p.batch_mode==='simple'?'簡易：Defaultのみ×6シールド':'詳細：4モード×6シールド';el('previewDetail').textContent='候補:'+p.candidate_count+'体 / 登録メタ:'+p.opponent_count+'行 / 最大対戦数:'+p.battles_upper_bound+' (技の有効性で変動)';return;}el('previewPanel').hidden=false;const stats=[['自分',p.candidate_count+'体'],['相手',p.opponent_count+'体'],['合計',p.battles+'対戦']];el('previewStats').innerHTML=stats.map(v=>`<div><b>${esc(v[1])}</b><small>${esc(v[0])}</small></div>`).join('');el('previewDetail').textContent=p.candidates.map(v=>v.ivs+' → Lv'+v.level+' CP'+v.cp).join('\n')+'\n--- 相手 ---\n'+p.opponents.map(v=>v.species+' ['+(v.iv_mode||'custom')+'] '+v.ivs+' → Lv'+v.level+' CP'+v.cp).join('\n');}
function disableButtons(on){for(const id of ['preview','run','run24','addOpp','batchMode'])el(id).disabled=on;}
function refreshBatchMode(){
const simple=el('batchMode').value==='simple';
el('run24').textContent=simple?'③ 簡易6条件を実行':'③ 詳細24条件を実行';
el('batchModeHint').textContent=simple?'簡易：Default個体値×6シールド。詳細の約1/4の計算量':'詳細：Default・Rank 1・Attack・Defenseの4種類×6シールド';
}
el('batchMode').addEventListener('change',refreshBatchMode);
refreshBatchMode();
el('preview').onclick=async()=>{if(busy)return;disableButtons(true);status('CPとレベルを計算しているよ…');try{const r=await api('/api/prepare',gather());showPreview(r.preview);status('CP1500以下のレベル調整を確認できたよ','good');}catch(e){status(e.message,'error');}finally{disableButtons(busy);}};
el('run').onclick=async()=>{if(busy)return;disableButtons(true);status('計算を開始するよ…');el('download').hidden=true;try{const r=await api('/api/run',gather());showPreview(r.preview);status('計算開始。完了までこの画面は閉じずに待ってね。','good');}catch(e){status(e.message,'error');disableButtons(false);}};
el('run24').onclick=async()=>{if(busy)return;disableButtons(true);status('メタ比較の計算を準備中…');el('download').hidden=true;try{const r=await api('/api/run24',{...gather(),batch_mode:el('batchMode').value});showPreview(r.preview);status((r.preview.batch_mode==='simple'?'簡易6条件':'詳細24条件')+'を計算中。完了後にZIPを取得できるよ。','good');}catch(e){status(e.message,'error');disableButtons(false);}};
async function poll(){try{const s=await api('/api/status');busy=s.state==='running';disableButtons(busy);el('logs').hidden=!s.logs.length;el('logs').textContent=s.logs.join('\n');if(s.state==='running'){status('計算中: '+s.message);el('download').hidden=true;}else if(s.state==='done'){status('完了！ ZIPを保存してChatGPTへ送ってね。','good');el('download').hidden=false;}else if(s.state==='error'){status('エラー: '+s.message,'error');el('download').hidden=true;} }catch(e){status('状態確認に失敗: '+e.message,'error');}setTimeout(poll,1800);}
ready();poll();
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    server_version = 'PvPokeLocalUI/1.0'

    def log_message(self, fmt, *args):
        # Only log errors, not repetitive API polling.
        if not self.path.startswith('/api/status'):
            super().log_message(fmt, *args)

    def respond(self, code, body, content_type='application/json; charset=utf-8'):
        if isinstance(body, (dict, list)):
            payload = json.dumps(body, ensure_ascii=False).encode('utf-8')
        elif isinstance(body, str):
            payload = body.encode('utf-8')
        else:
            payload = body
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.end_headers()
        try:
            self.wfile.write(payload)
        except BrokenPipeError:
            pass

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/':
            self.respond(200, HTML.replace('__TOKEN__', TOKEN), 'text/html; charset=utf-8')
        elif path == '/api/catalog':
            with LOCK:
                cat = dict(CATALOG)
            saved = None
            try:
                if LAST_CONFIG.is_file():
                    saved = json.loads(LAST_CONFIG.read_text(encoding='utf-8'))
            except Exception:
                pass
            available = []
            if cat.get('ready'):
                available = app_presets(cat['species'], cat['presets'],
                                       meta_live.active_path(WORK).read_text(encoding='utf-8-sig'))
            self.respond(200, {**cat, 'app_presets': available, 'saved': saved})
        elif path == '/api/flashcards':
            if self.headers.get('X-PvPoke-Token') != TOKEN:
                return self.respond(403, {'error': '認証が必要です'})
            with LOCK:
                result = flashcards.private_decks(WORK)
            return self.respond(200, {**result, 'augmentation': meta_variants.status(WORK)})
        elif path in ('/api/meta/presets', '/api/meta/preset', '/api/meta/preset-export'):
            try:
                with LOCK:
                    if path == '/api/meta/presets':
                        result = meta_presets.listing(WORK)
                    elif path == '/api/meta/preset-export':
                        query = parse_qs(urlparse(self.path).query)
                        result = meta_presets.export_preset(WORK, query.get('id', [None])[0],
                                                            query.get('sha256', [None])[0])
                    else:
                        entry = meta_presets.resolve(WORK, parse_qs(urlparse(self.path).query).get('id', [None])[0])
                        result = {k: v for k, v in entry.items() if k not in ('csv', 'source_csv')}
                self.respond(200, result)
            except (ValueError, OSError) as exc:
                self.respond(400, {'error': str(exc)})
        elif path == '/api/meta/status':
            self.respond(200, meta_live.get_status(WORK))
        elif path == '/api/storage/status':
            self.respond(200, archives.archive_stats(WORK))
        elif path == '/api/status':
            with LOCK:
                details = {k: (list(v) if isinstance(v, deque) else v) for k, v in STATUS.items()}
            details['has_previous_archive'] = bool(archives.archived_latest(WORK)) or LATEST_ZIP.is_file()
            self.respond(200, details)
        elif path == '/download':
            with LOCK:
                state, batch24 = STATUS['state'], STATUS['batch24']
            # On a fresh server process, only verified archived ZIPs are
            # eligible: old in-memory state is intentionally not restored.
            if state == 'done':
                zip_path = archives.archived_latest(WORK) if batch24 else LATEST_ZIP
            elif state == 'idle':
                zip_path = archives.archived_latest(WORK)
            else:
                zip_path = None
            if zip_path is None or not zip_path.is_file():
                return self.respond(404, {'error':'利用可能な完成ZIPがありません'})
            data = zip_path.read_bytes()
            # Download as attachment; the web UI never exposes arbitrary filesystem paths.
            self.send_response(200)
            self.send_header('Content-Type', 'application/zip')
            self.send_header('Content-Disposition', 'attachment; filename="pvpoke_results_latest.zip"')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(data)
        else:
            self.respond(404, {'error': '見つかりません'})

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ('/api/prepare','/api/run','/api/prepare24','/api/run24','/api/meta/sync','/api/meta/preview','/api/meta/presets',
                        '/api/party/list','/api/party/get','/api/party/save',
                        '/api/party/start','/api/party/status','/api/party/cancel'):
            return self.respond(404, {'error': '見つかりません'})
        # Only same-origin JS with the random session token can start a job.
        origin = self.headers.get('Origin','')
        if origin and origin not in (f'http://{HOST}:{PORT}',f'http://localhost:{PORT}'):
            return self.respond(403, {'error':'ローカル画面以外からは操作できません'})
        if self.headers.get('X-PvPoke-Token') != TOKEN:
            return self.respond(403, {'error':'この画面を再読み込みしてください'})
        if 'application/json' not in self.headers.get('Content-Type',''):
            return self.respond(415, {'error':'JSONで送信してください'})
        try:
            n = int(self.headers.get('Content-Length','0'))
            if n < 2 or n > MAX_APP_REQUEST_BYTES:
                raise ValueError('入力が大きすぎるか空です')
            payload = json.loads(self.rfile.read(n))
            if not isinstance(payload, dict):
                raise ValueError('入力はJSONオブジェクトで指定してください')
            if path.startswith('/api/party/'):
                action = path.rsplit('/', 1)[-1]
                if action == 'list':
                    return self.respond(200, PARTY.list_parties())
                if action == 'get':
                    return self.respond(200, PARTY.get_party(payload.get('id')))
                if action == 'save':
                    try:
                        return self.respond(200, PARTY.save_party(payload))
                    except RuntimeError as exc:
                        return self.respond(409, {'error': str(exc)})
                if action == 'status':
                    return self.respond(200, PARTY.run_status(payload.get('job_id')))
                if action == 'cancel':
                    return self.respond(200, PARTY.cancel(payload.get('job_id')))
                if action == 'start':
                    with LOCK:
                        if not CATALOG.get('ready'):
                            raise ValueError('ゲームデータを読み込み中です')
                        _, cpms, full_species = engine.game_data()
                        try:
                            response = PARTY.start(payload, catalog=CATALOG['species'],
                                species=full_species, cpms=cpms, engine=engine, work=WORK,
                                global_lock=LOCK, global_status=STATUS)
                        except RuntimeError as exc:
                            return self.respond(409, {'error': str(exc)})
                    return self.respond(200, response)
            with LOCK:
                if STATUS['state'] == 'running' or PARTY.running:
                    return self.respond(409, {'error':'計算中は入力を変更できません'})
                if path == '/api/meta/presets':
                    if not CATALOG['ready']:
                        raise ValueError('ゲームデータの読み込みが完了していません')
                    result = meta_presets.save(WORK, payload, CATALOG['species'])
                    if payload.get('action') == 'create':
                        result['augmentation'] = meta_variants.schedule(WORK, result['saved_id'])
                    return self.respond(200, result)
                if path == '/api/meta/preview':
                    if not CATALOG['ready']:
                        raise ValueError('ゲームデータの読み込みが完了していません')
                    result = meta_live.preview(WORK, payload.get('csv'), CATALOG['species'])
                    return self.respond(200, {'ok': True, **result})
                if path == '/api/meta/sync':
                    if not CATALOG['ready']:
                        raise ValueError('ゲームデータの読み込みが完了していません')
                    result = meta_live.sync(
                        WORK, payload.get('csv'), CATALOG['species'],
                        expected_previous_sha256=payload.get('expected_previous_sha256'),
                        expected_sha256=payload.get('expected_sha256'))
                    result['augmentation'] = meta_variants.schedule(WORK, 'legacy')
                    return self.respond(200, {'ok': True, **result})
                if path in ('/api/prepare24','/api/run24'):
                    cand_parts = normalize_pokemon(payload.get('candidate'), CATALOG['species'], '自分')
                    iv_list = parse_ivs(payload.get('ivs'))
                    meta_file = meta_live.active_path(WORK)
                    selected_meta = None
                    if payload.get('meta_preset_id') is not None:
                        meta_file, selected_meta = meta_presets.snapshot(
                            WORK, payload['meta_preset_id'], CATALOG['species'],
                            payload.get('expected_meta_sha256'))
                    elif (payload.get('expected_meta_sha256') is not None
                          and payload['expected_meta_sha256'] != meta_live.get_status(WORK)['sha256']):
                        raise ValueError('計算前にメタが更新されました。再確認してください')
                    with meta_file.open(encoding='utf-8-sig', newline='') as fp:
                        meta_count = sum(bool(row) for row in csv.reader(fp))
                    batch_mode = str(payload.get('batch_mode') or 'simple').strip().lower()
                    if batch_mode not in ('simple','detailed'):
                        raise ValueError('メタ計算モードはsimpleまたはdetailedです')
                    mode_count = 1 if batch_mode == 'simple' else 4
                    preview = {'meta_preset': selected_meta, 'batch24': True, 'batch_mode': batch_mode, 'candidate_count': len(iv_list),
                               'opponent_count': meta_count, 'mode_count': mode_count, 'shield_cases': 6,
                               'battles_upper_bound': len(iv_list)*meta_count*mode_count*6}
                    if path == '/api/run24':
                        force = payload.get('force_recalculate', False)
                        if not isinstance(force, bool):
                            raise ValueError('force_recalculate must be true or false')
                        force = force or force_recalculate()
                        cache_context = None
                        reuse = {'reused':False}
                        version = calculation_version(engine.DATA)
                        if version is not None:
                            try:
                                saved = result_cache.ResultCache.configured(WORK)
                                if saved is not None:
                                    cache_context = result_cache.context(
                                        dict(zip(engine.HEADER[:4], cand_parts)), iv_list, batch_mode,
                                        content_hash(meta_file), version, engine.CP_CAP, engine.MAX_LEVEL)
                                    cached = None if force else saved.restore(
                                        cache_context, archives.archive_dir(WORK) / 'latest.zip')
                                    if cached is not None:
                                        now = datetime.now().isoformat(timespec='microseconds')
                                        STATUS.update({'state':'done','message':'過去の対戦結果を再利用しました',
                                            'logs':deque(maxlen=120),'exit_code':0,'started_at':now,
                                            'finished_at':now,'batch24':True,'result_cache':cached})
                                        preview['result_cache'] = cached
                                        return self.respond(200, {'ok':True,'preview':preview})
                            except (OSError, ValueError, TypeError, KeyError):
                                cache_context = None  # Always allow a normal calculation.
                        preview['result_cache'] = reuse
                        BATCH_CONFIG.parent.mkdir(parents=True, exist_ok=True)
                        temp = BATCH_CONFIG.with_suffix('.tmp')
                        temp.write_text(json.dumps({
                            'candidate': dict(zip(engine.HEADER[:4], cand_parts)),
                            'ivs': '\n'.join(','.join(map(str, iv)) for iv in iv_list),
                            'batch_mode': batch_mode,
                        }, ensure_ascii=False), encoding='utf-8')
                        temp.replace(BATCH_CONFIG)
                        STATUS.update({'state':'running', 'message':'メタ比較を準備中',
                                       'logs':deque(maxlen=120), 'exit_code':None,
                                       'started_at':datetime.now().isoformat(timespec='microseconds'),
                                       'finished_at':None, 'batch24':True, 'result_cache':reuse})
                        threading.Thread(target=background_run, args=('all', True, batch_mode, meta_file, cache_context, force),
                                         daemon=True).start()
                    return self.respond(200, {'ok':True,'preview':preview})
                cleaned, crows, orows, preview = prepare_payload(payload)
                save_input(cleaned, crows, orows)
                if path == '/api/prepare':
                    STATUS.update({'state':'idle', 'message':'入力を確認できました。計算開始を押してください',
                                   'logs':deque(maxlen=120), 'exit_code':None})
                if path == '/api/run':
                    STATUS.update({'state':'running', 'message':'計算を準備中',
                                   'logs':deque(maxlen=120), 'exit_code':None,
                                   'started_at':datetime.now().isoformat(timespec='microseconds'),
                                   'finished_at':None, 'batch24':False})
                    threading.Thread(target=background_run, args=(cleaned['shields'],),
                                     daemon=True).start()
            self.respond(200, {'ok':True,'preview':preview})
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            self.respond(400, {'error': str(exc)})
        except Exception as exc:
            self.respond(500, {'error': '内部エラー: '+str(exc)})


def main():
    parser = argparse.ArgumentParser(description='Androidブラウザで使うPvPoke個体値シミュレーター')
    parser.add_argument('--worker', choices=list(engine.SCENARIOS.keys()))
    parser.add_argument('--port', type=int, default=PORT)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker)
        return
    if args.port != PORT:
        parser.error('このバージョンではセキュリティ上ポート8765固定です')
    configure_engine()
    threading.Thread(target=load_catalog, daemon=True).start()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f'\nPvPokeブラウザ操作画面: http://{HOST}:{PORT}', flush=True)
    print('AndroidのChromeでURLを開いてね。終了はTermuxでCtrl+C。', flush=True)
    httpd.serve_forever()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n終了したにぇ。保存済みのCSVとZIPは残るよ。')




