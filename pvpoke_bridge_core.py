#!/usr/bin/env python3
"""Local, pure-standard-library bridge to existing pvpoke_web.py.

SECURITY: local-only API (127.0.0.1). Do not expose this bridge over the
public Internet without a proper authenticated MCP gateway.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import urllib.error
import urllib.request
import zipfile
from typing import Any

BASE = os.environ.get('PVP_LOCAL_URL', 'http://127.0.0.1:8765').rstrip('/')
SHIELDS = {'s0', 's1', 's2', 'i0y1', 'i0y2', 'i1y2'}


class BridgeError(RuntimeError):
    pass


def _request(path: str, payload: dict | None = None, headers: dict | None = None,
             expect_bytes: bool = False, timeout: int = 30) -> Any:
    method = 'POST' if payload is not None else 'GET'
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
    h = {'User-Agent': 'PvPoke-local-MCP-bridge/1.0'}
    if payload is not None:
        h['Content-Type'] = 'application/json; charset=utf-8'
    if headers:
        h.update(headers)
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            if expect_bytes:
                return body
            content_type = r.headers.get('Content-Type', '')
            if 'application/json' in content_type:
                return json.loads(body.decode('utf-8'))
            return body.decode('utf-8')
    except urllib.error.HTTPError as e:
        detail = e.read(800).decode('utf-8', errors='replace')
        raise BridgeError(f'ローカルアプリ HTTP {e.code}: {detail}') from e
    except urllib.error.URLError as e:
        raise BridgeError(f'ローカルアプリに接続できません: {BASE} ({e.reason})。先に pvpoke_web.py を起動してください') from e


def _token() -> str:
    page = _request('/')
    match = re.search(r"const TOKEN='([^']+)'", page)
    if not match:
        raise BridgeError('ローカル画面の接続用トークンが見つかりません')
    return match.group(1)


def catalog() -> dict:
    out = _request('/api/catalog')
    if not out.get('ready'):
        raise BridgeError('ゲームデータの読み込みが終わっていません: ' + str(out.get('error')))
    # Don't return the enormous catalog to the model; expose presets only.
    return {'ready': True, 'gamemaster_timestamp': out.get('timestamp'),
            'presets': out.get('presets', []), 'species_count': len(out.get('species', {}))}


def validate_payload(candidate: dict, ivs: str, opponents: list[dict], shields: str) -> dict:
    if shields not in ('all', 'equal', 'disadvantage'):
        raise BridgeError('shields は all / equal / disadvantage のどれかです')
    if not isinstance(ivs, str) or not ivs.strip():
        raise BridgeError('個体値リストが空です')
    if not isinstance(opponents, list) or not opponents:
        raise BridgeError('対戦相手を1体以上指定してください')
    if not isinstance(candidate, dict):
        raise BridgeError('candidate はポケモン情報の辞書で指定してください')
    # Detailed validation and CP checks are performed by the existing web app.
    return {'candidate': candidate, 'ivs': ivs, 'opponents': opponents, 'shields': shields}


def _post(path: str, candidate: dict, ivs: str, opponents: list[dict], shields: str) -> dict:
    payload = validate_payload(candidate, ivs, opponents, shields)
    result = _request(path, payload, headers={'X-PvPoke-Token': _token()}, timeout=75)
    if not result.get('ok'):
        raise BridgeError(str(result))
    return result


def preview(candidate: dict, ivs: str, opponents: list[dict], shields: str = 'all') -> dict:
    return _post('/api/prepare', candidate, ivs, opponents, shields)


def start(candidate: dict, ivs: str, opponents: list[dict], shields: str = 'all') -> dict:
    result = _post('/api/run', candidate, ivs, opponents, shields)
    return {'started': True, 'preview': result['preview'],
            'next': '少し待ってから get_status を呼び、done なら get_results で結果を取得してください'}


def status() -> dict:
    result = _request('/api/status')
    logs = result.get('logs', [])
    if isinstance(logs, list):
        result['logs'] = logs[-8:]
    return result


def _zip() -> zipfile.ZipFile:
    current = status()
    if current.get('state') != 'done':
        raise BridgeError('計算がまだ完了していません。get_status で状態を確認してください: ' + str(current.get('state')))
    blob = _request('/download', expect_bytes=True, timeout=40)
    try:
        return zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile as e:
        raise BridgeError('ダウンロードしたZIPが壊れています') from e


def results(shield: str = 's1', offset: int = 0, limit: int = 10) -> dict:
    if shield not in SHIELDS:
        raise BridgeError('shieldは s0,s1,s2,i0y1,i0y2,i1y2 のいずれかです')
    if not (isinstance(offset, int) and offset >= 0 and isinstance(limit, int) and 1 <= limit <= 20):
        raise BridgeError('offset は0以上、limit は1〜20を指定してください')
    with _zip() as z:
        filename = f'pvpoke_{shield}.csv'
        if filename not in z.namelist():
            raise BridgeError(f'{filename} はZIPにありません（実行時に選択したシールド条件を確認してください）')
        lines = list(csv.reader(io.StringIO(z.read(filename).decode('utf-8-sig'))))
        if len(lines) < 2 or len(lines[0]) < 5:
            raise BridgeError('CSVの列構成が不正です')
        header = lines[0]
        if header[-4:] != ['Wins', 'Losses', 'Draws', 'Average']:
            raise BridgeError('CSVの集計列が予想と異なります')
        opponents = header[1:-4]
        items = []
        for row in lines[offset+1:offset+1+limit]:
            if len(row) != len(header):
                raise BridgeError('CSVの列数が一致しません')
            items.append({
                'candidate': row[0],
                'ratings': [{'opponent': name, 'rating': float(rate)}
                            for name, rate in zip(opponents, row[1:-4])],
                'wins': int(row[-4]), 'losses': int(row[-3]), 'draws': int(row[-2]),
                'average': float(row[-1]),
            })
        manifest = None
        if 'manifest.json' in z.namelist():
            manifest = json.loads(z.read('manifest.json').decode('utf-8'))
        return {'shield': shield, 'total_candidates': len(lines)-1, 'opponent_count': len(opponents),
                'offset': offset, 'returned': len(items), 'has_more': offset+len(items) < len(lines)-1,
                'manifest': {k: manifest.get(k) for k in ('gamemaster_timestamp','cp_cap','max_level','shield_pairs')}
                if isinstance(manifest, dict) else None,
                'rows': items}


def healthcheck() -> dict:
    out = {'server_url': BASE, 'catalog': catalog(), 'status': status()}
    out['status']['logs'] = out['status'].get('logs', [])[-3:]
    return out


if __name__ == '__main__':
    try:
        print(json.dumps(healthcheck(), ensure_ascii=False, indent=2))
    except BridgeError as e:
        raise SystemExit('接続確認エラー: ' + str(e)) from e
