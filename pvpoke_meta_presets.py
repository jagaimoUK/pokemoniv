"""Named meta collections; legacy CSV stays intact, each run gets an immutable file.

Only stdlib. Call mutations under the web server's existing execution lock.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import uuid

import pvpoke_archive as archives
import pvpoke_meta_live as live
import pvpoke_meta_sync as meta

MAX_CUSTOM = 50
BUNDLED = Path(__file__).resolve().parent / 'data' / 'pvpoke_meta_presets.json'


@lru_cache(maxsize=1)
def bundled() -> dict:
    return json.loads(BUNDLED.read_text(encoding='utf-8'))


def store_path(work: Path) -> Path:
    return archives.archive_dir(work) / 'meta_presets.json'


def _read(work: Path) -> dict:
    path = store_path(work)
    if not path.exists():
        return {'version': 1, 'revision': 0, 'default_id': 'legacy',
                'favorite_ids': [], 'items': []}
    try:
        obj = json.loads(path.read_text(encoding='utf-8'))
        if (obj['version'] != 1 or not isinstance(obj['revision'], int)
                or not isinstance(obj['items'], list) or len(obj['items']) > MAX_CUSTOM
                or not isinstance(obj['favorite_ids'], list)
                or not isinstance(obj['default_id'], str)):
            raise ValueError('Invalid preset store')
        for p in obj['items']:
            if not (isinstance(p, dict) and isinstance(p.get('id'), str)
                    and p['id'].startswith('custom:') and isinstance(p.get('name'), str)
                    and isinstance(p.get('csv'), str)):
                raise ValueError('Invalid preset entry')
        return obj
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError('プリセット保存データを読めません。変更せずバックアップから復旧してください') from exc


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as fp:
            fp.write(content)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write(work: Path, obj: dict) -> None:
    path = store_path(work)
    # Preserve the last valid revision; a failed replacement leaves live data intact.
    if path.exists():
        _atomic_write(path.with_suffix('.json.bak'), path.read_text(encoding='utf-8'))
    obj['revision'] += 1
    _atomic_write(path, json.dumps(obj, ensure_ascii=False))


def _entries(work: Path, obj: dict) -> list[dict]:
    return [{'id': 'legacy', 'name': 'これまでのカスタムメタ', 'cp': 1500,
             'source': 'legacy', 'csv': live.active_path(work).read_text(encoding='utf-8-sig')},
            *obj['items'], *bundled()['items']]


@lru_cache(maxsize=128)
def _content_metadata(content: str, available: bool) -> tuple[str, int]:
    rendered = meta.serialize(live._parse(content, trusted=True)) if available else content
    return hashlib.sha256(rendered.encode('utf-8')).hexdigest(), len(rendered.strip().splitlines())


def _metadata(entry: dict, obj: dict) -> dict:
    checksum, count = _content_metadata(entry['csv'], entry.get('available') is not False)
    return {k: v for k, v in entry.items() if k not in ('csv', 'source_csv')} | {
        'sha256': checksum, 'rows': count,
        'favorite': entry['id'] in obj['favorite_ids'],
        'default': entry['id'] == obj['default_id'],
    }


def listing(work: Path) -> dict:
    obj = _read(work)
    return {'revision': obj['revision'], 'default_id': obj['default_id'],
            'items': [_metadata(p, obj) for p in _entries(work, obj)],
            'max_custom': MAX_CUSTOM, 'retrieved': bundled()['retrieved']}


def resolve(work: Path, preset_id: str) -> dict:
    if not isinstance(preset_id, str):
        raise ValueError('メタプリセットを選択してください')
    obj = _read(work)
    for p in _entries(work, obj):
        if p['id'] == preset_id:
            return p | _metadata(p, obj)
    raise ValueError('メタプリセットが見つかりません。一覧を再取得してください')


def save(work: Path, args: dict, species: dict) -> dict:
    obj = _read(work)
    if type(args.get('revision')) is not int or args['revision'] != obj['revision']:
        raise ValueError('別の画面でプリセットが更新されました。一覧を再取得してください')
    action = args.get('action')
    input_info = {}
    if action == 'create':
        name = args.get('name')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
            raise ValueError('名前は1〜60文字で入力してください')
        name = name.strip()
        if any(p['name'].casefold() == name.casefold() for p in _entries(work, obj)):
            raise ValueError('同じ名前があります。別の名前で保存してください')
        if len(obj['items']) >= MAX_CUSTOM:
            raise ValueError('カスタムプリセットは最大50件です')
        _, content, input_info = live._validated_upload(work, args.get('csv'), species)
        checksum = hashlib.sha256(content.encode('utf-8')).hexdigest()
        if args.get('expected_sha256') != checksum:
            raise ValueError('プレビューと内容が異なります。もう一度確認してください')
        preset_id = 'custom:' + uuid.uuid4().hex
        obj['items'].append({'id': preset_id, 'name': name, 'cp': 1500,
                             'source': 'custom', 'csv': content})
    elif action in ('default', 'favorite'):
        preset_id = args.get('id')
        entry = next((p for p in _entries(work, obj) if p['id'] == preset_id), None)
        if entry is None:
            raise ValueError('メタプリセットが見つかりません')
        if entry.get('available') is False:
            raise ValueError(entry['unavailable_reason'])
        if action == 'default':
            obj['default_id'] = preset_id
        else:
            if not isinstance(args.get('favorite'), bool):
                raise ValueError('お気に入りの指定が不正です')
            obj['favorite_ids'] = [x for x in obj['favorite_ids'] if x != preset_id]
            if args['favorite']:
                obj['favorite_ids'].append(preset_id)
    else:
        raise ValueError('未対応のプリセット操作です')
    _write(work, obj)
    return listing(work) | {'saved_id': preset_id, **input_info}


def snapshot(work: Path, preset_id: str, species: dict,
             expected_sha256: str | None = None) -> tuple[Path, dict]:
    entry = resolve(work, preset_id)
    if entry.get('available') is False:
        raise ValueError(entry['unavailable_reason'])
    if expected_sha256 is not None and entry['sha256'] != expected_sha256:
        raise ValueError('選択したメタが更新されました。一覧を再取得してください')
    # Validate against the running GameMaster; never silently skip invalid opponents.
    _, content = live._validated_rows(work, entry['csv'], species, trusted=True)
    path = archives.archive_dir(work) / 'meta_snapshots' / (entry['sha256'] + '.csv')
    if not path.exists():
        _atomic_write(path, content)
    elif path.read_text(encoding='utf-8') != content:
        raise ValueError('計算用メタの保存内容が一致しません')
    return path, {k: v for k, v in entry.items() if k not in ('csv', 'source_csv')}


# PvPoke's battle/matrix custom-group selector currently accepts 100 entries.
PVP_IMPORT_LIMIT = 100


def export_preset(work: Path, preset_id: str, expected_sha256: str) -> dict:
    """Read-only adapter to PvPoke PokeMultiSelect.quickFillCSV (four columns)."""
    entry = resolve(work, preset_id)
    if entry.get('available') is False:
        raise ValueError(entry['unavailable_reason'])
    if expected_sha256 != entry['sha256']:
        raise ValueError('プリセットの内容が更新されました。一覧を再取得してからコピーしてください')
    rows = []
    for species, fast, charged1, charged2 in live._parse(entry['csv'], trusted=True):
        sid = species.lower()
        # _shadow is the species ID; -shadow tells PvPoke to apply shadow damage.
        if sid.endswith('_shadow-shadow'):
            sid = sid.removesuffix('-shadow')
        if sid.endswith('_shadow'):
            sid += '-shadow'
        rows.append((sid, fast.upper(), charged1.upper(), charged2.upper()))
    parts = [
        {'start': i + 1, 'end': min(i + PVP_IMPORT_LIMIT, len(rows)),
         'csv': meta.serialize(rows[i:i + PVP_IMPORT_LIMIT]).rstrip('\n')}
        for i in range(0, len(rows), PVP_IMPORT_LIMIT)
    ]
    return {'id': entry['id'], 'name': entry['name'], 'sha256': entry['sha256'],
            'rows': len(rows), 'csv': meta.serialize(rows).rstrip('\n'),
            'parts': parts, 'max_import_rows': PVP_IMPORT_LIMIT}
