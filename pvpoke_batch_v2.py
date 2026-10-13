#!/usr/bin/env python3
"""Termux + Chromium CDP: PvPoke Great League CP preparation and shield matrix export.
Usage: python pvpoke_batch_v2.py --setup | --prepare | --run --shields all
Requirements: python -m pip install websocket-client
"""
import argparse
import csv
import io
import hashlib
import json
import shutil
import math
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
DOWNLOADS = HOME / 'storage' / 'downloads'
ROOT = DOWNLOADS if DOWNLOADS.exists() else HOME
DIR = ROOT / 'pvpoke_automation'
DATA = DIR / 'game_data'
OUT = DIR / 'results'
CDP = 'http://127.0.0.1:9222'
CAND = DIR / 'candidates.csv'
OPPS = DIR / 'opponents.csv'
HEADER = ['species', 'fast', 'charged1', 'charged2', 'atk', 'def', 'hp']
RAW = 'https://raw.githubusercontent.com/pvpoke/pvpoke/master/src/'
MAX_LEVEL = 50
CP_CAP = 1500
CAND_CHUNK = 8
OPP_CHUNK = 8
SCENARIOS = {
    'equal': ((0, 0), (1, 1), (2, 2)),
    'disadvantage': ((0, 1), (0, 2), (1, 2)),
    'all': ((0, 0), (1, 1), (2, 2), (0, 1), (0, 2), (1, 2)),
}


def result_filename(pair):
    left, right = pair
    return f'pvpoke_s{left}.csv' if left == right else f'pvpoke_i{left}y{right}.csv'



def urlget(url, timeout=35):
    req = urllib.request.Request(url, headers={'User-Agent': 'PvPoke-Termux-automation/0.2'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def setup():
    DIR.mkdir(parents=True, exist_ok=True)
    if not CAND.exists():
        with CAND.open('w', encoding='utf-8', newline='') as f:
            w = csv.writer(f)
            w.writerow(HEADER)
            w.writerow(['azumarill', 'BUBBLE', 'ICE_BEAM', 'PLAY_ROUGH', 0, 15, 15])
            w.writerow(['azumarill', 'BUBBLE', 'ICE_BEAM', 'PLAY_ROUGH', 1, 15, 14])
    if not OPPS.exists():
        with OPPS.open('w', encoding='utf-8', newline='') as f:
            w = csv.writer(f)
            w.writerow(HEADER)
            w.writerow(['clodsire', 'POISON_STING', 'EARTHQUAKE', 'STONE_EDGE', 0, 15, 15])
    print('入力ファイル:', CAND)
    print('対戦相手:', OPPS)
    print('日本語名ではなくPvPokeの英語species IDを指定してください。')


def game_data(refresh=False):
    DATA.mkdir(parents=True, exist_ok=True)
    master = DATA / 'gamemaster.json'
    pokemon_js = DATA / 'Pokemon.js'
    for fn, url in [
        (master, RAW + 'data/gamemaster.json'),
        (pokemon_js, RAW + 'js/pokemon/Pokemon.js'),
    ]:
        if not fn.exists() or refresh:
            print('最新データ取得:', fn.name, flush=True)
            temp = fn.with_suffix(fn.suffix + '.tmp')
            try:
                temp.write_bytes(urlget(url))
                if temp.stat().st_size < 10000:
                    raise ValueError('取得ファイルが小さすぎます')
                temp.replace(fn)
            finally:
                temp.unlink(missing_ok=True)
    gm = json.loads(master.read_text(encoding='utf-8'))
    src = pokemon_js.read_text(encoding='utf-8')
    match = re.search(r'\bvar\s+cpms\s*=\s*\[([^\]]+)\]', src, re.S)
    if not match:
        raise ValueError('PvPokeのCP倍率配列が見つかりません。Pokemon.jsの仕様変更を確認してください')
    cpms = [float(s.strip()) for s in match.group(1).split(',') if s.strip()]
    if not 90 <= len(cpms) <= 200:
        raise ValueError('CP倍率の数が異常です')
    species = {p['speciesId']: p for p in gm['pokemon']}
    return gm, cpms, species


def get_rows(path):
    if not path.exists():
        raise ValueError(f'ファイルがありません: {path}。先に --setup を実行してください')
    with path.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != HEADER:
            raise ValueError(f'{path.name}: 列名が不正です。必要な列: {HEADER}')
        rows = []
        for i, row in enumerate(reader, 2):
            if not any((v or '').strip() for v in row.values()):
                continue
            try:
                iv = [int(row[k]) for k in ('atk', 'def', 'hp')]
            except (ValueError, TypeError) as e:
                raise ValueError(f'{path.name} {i}行目: IVは0〜15の整数です') from e
            if any(v < 0 or v > 15 for v in iv):
                raise ValueError(f'{path.name} {i}行目: IVは0〜15です: {iv}')
            vals = {k: (row[k] or '').strip() for k in HEADER[:4]}
            vals['species'] = vals['species'].lower()
            for k in ('fast', 'charged1', 'charged2'):
                vals[k] = vals[k].upper()
            vals.update(dict(zip(('atk', 'def', 'hp'), iv)))
            rows.append(vals)
    if not rows:
        raise ValueError(f'{path.name}: データ行がありません')
    return rows


def optimize(rows, species, cpms, fname):
    prepared = []
    for idx, row in enumerate(rows, 2):
        p = species.get(row['species'])
        if p is None:
            raise ValueError(f'{fname} {idx}行目: species未登録: {row["species"]}')
        allowed_fast = set(p['fastMoves'])
        allowed_charged = set(p['chargedMoves'])
        for key, allowed in [('fast', allowed_fast), ('charged1', allowed_charged), ('charged2', allowed_charged)]:
            if row[key] not in allowed:
                raise ValueError(f'{fname} {idx}行目: 未対応の技: {key}={row[key]} ({row["species"]})')
        if row['charged1'] == row['charged2']:
            raise ValueError(f'{fname} {idx}行目: 同じゲージ技が2つ指定されています')
        stats = p['baseStats']
        maxlevel = min(MAX_LEVEL, float(p.get('levelCap', MAX_LEVEL)))
        floorlevel = max(1.0, float(p.get('levelFloor', 1.0)))
        possibilities = []
        # Exact half-level increments per PvPoke CPM table, no approximation.
        for half in range(math.ceil(floorlevel * 2), math.floor(maxlevel * 2) + 1):
            level = half / 2
            index = half - 2
            if index < 0 or index >= len(cpms):
                continue
            cpm = cpms[index]
            cp = max(10, math.floor(
                (stats['atk'] + row['atk']) *
                math.sqrt(stats['def'] + row['def']) *
                math.sqrt(stats['hp'] + row['hp']) * cpm ** 2 / 10
            ))
            if cp <= CP_CAP:
                possibilities.append((level, cp))
        if not possibilities:
            raise ValueError(f'{fname} {idx}行目: CP{CP_CAP}以下の適正レベルが見つかりません')
        level, cp = possibilities[-1]
        prepared.append({**row, 'level': level, 'cp': cp})
    return prepared


def pvpline(row):
    return ','.join(map(str, [row['species'], row['fast'], row['charged1'], row['charged2'],
                              f'{row["level"]:g}', row['atk'], row['def'], row['hp']]))


def canonical_export_species(species_id):
    """Normalize only PvPoke's shadow export suffix (e.g. _shadow-shadow).

    Preserve the distinction between regular and shadow Pokemon.
    """
    species_id = species_id.strip().lower()
    return species_id[:-len('-shadow')] if species_id.endswith('_shadow-shadow') else species_id


def export_row_matches(actual, expected):
    """Verify move, IV and level fields while accepting shadow export notation."""
    if len(actual) < 8 or len(expected) < 8:
        return False
    if canonical_export_species(actual[0]) != canonical_export_species(expected[0]):
        return False
    if actual[1:4] != expected[1:4] or actual[5:8] != expected[5:8]:
        return False
    try:
        return abs(float(actual[4]) - float(expected[4])) <= .001
    except (ValueError, TypeError):
        return False


def prepare(refresh=False):
    setup()
    gm, cpms, species = game_data(refresh=refresh)
    candidates = optimize(get_rows(CAND), species, cpms, CAND.name)
    opponents = optimize(get_rows(OPPS), species, cpms, OPPS.name)
    DIR.mkdir(exist_ok=True)
    for stem, rows in [('prepared_candidates', candidates), ('prepared_opponents', opponents)]:
        with (DIR / (stem + '.csv')).open('w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['species', 'fast', 'charged1', 'charged2', 'level', 'atk', 'def', 'hp', 'cp'])
            for r in rows:
                w.writerow([r[k] for k in ('species', 'fast', 'charged1', 'charged2', 'level', 'atk', 'def', 'hp', 'cp')])
    print(f'\nCP調整完了: 自分{len(candidates)}体、相手{len(opponents)}体 (CP上限={CP_CAP}; Lv上限={MAX_LEVEL})')
    print('使用ゲームデータ:', gm.get('timestamp', '更新日時不明'))
    for side, rows in [('自分', candidates), ('相手', opponents)]:
        for r in rows[:15]:
            print(f' {side}: {r["species"]} {r["atk"]}/{r["def"]}/{r["hp"]} => Lv{r["level"]:g} CP{r["cp"]}')
    return gm, candidates, opponents


def call_json(path, method='GET', timeout=10):
    req = urllib.request.Request(CDP + path, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def chromium_connect():
    try:
        return call_json('/json/version', timeout=3)
    except Exception:
        print('Chromiumをヘッドレス起動中...', flush=True)
        log = (DIR / 'chromium.log').open('ab')
        try:
            subprocess.Popen([
                'chromium-browser', '--headless', '--no-sandbox', '--disable-gpu',
                '--disable-dev-shm-usage', '--no-first-run',
                '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=9222',
                '--user-data-dir=' + str(HOME / 'chromium-pvpoke-headless'), 'about:blank'
            ], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        finally:
            log.close()
        for _ in range(30):
            time.sleep(1)
            try:
                return call_json('/json/version', timeout=2)
            except Exception:
                pass
        raise RuntimeError('Chromiumへ接続できません。chromium.logを確認してください')


class Page:
    def __init__(self):
        import websocket
        target_url = urllib.parse.quote('https://pvpoke.com/battle/matrix/', safe='')
        self.target = call_json('/json/new?' + target_url, method='PUT')
        self.id = self.target['id']
        self.ws = websocket.create_connection(self.target['webSocketDebuggerUrl'], timeout=150, suppress_origin=True)
        self.n = 0

    def eval(self, js, promise=False):
        self.n += 1
        rid = self.n
        self.ws.send(json.dumps({'id': rid, 'method': 'Runtime.evaluate', 'params': {
            'expression': js, 'returnByValue': True, 'awaitPromise': promise}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get('id') != rid:
                continue
            if 'error' in msg:
                raise RuntimeError(str(msg['error']))
            r = msg.get('result', {})
            if 'exceptionDetails' in r:
                raise RuntimeError(str(r['exceptionDetails']))
            val = r.get('result', {})
            if val.get('type') == 'undefined':
                raise RuntimeError('JavaScriptがundefinedを返しました')
            return val.get('value')

    def wait_ready(self):
        for _ in range(90):
            state = self.eval('''(() => ({
              ready:document.readyState,
              mode:document.querySelector('.mode-select a.selected')?.getAttribute('data'),
              groups:document.querySelectorAll('.poke-select-container .poke.multi').length,
              battle:!!document.querySelector('.battle-btn')
            }))()''')
            if state['ready'] == 'complete' and state['groups'] == 2 and state['battle'] and state['mode'] == 'matrix':
                return
            time.sleep(1)
        raise RuntimeError(f'PvPoke Matrixが読み込めません: {state}')

    def import_group(self, group_index, rows):
        csvtext = '\n'.join(pvpline(r) for r in rows)
        js = r'''(() => {
          const groups=[...document.querySelectorAll('.poke-select-container .poke.multi')];
          const g=groups[__INDEX__];
          if(!g) return {error:'対象グループなし'};
          if(Number(g.querySelector('.poke-count')?.textContent)!==0) return {error:'空グループではない'};
          if(typeof closeModalWindow==='function') {try{closeModalWindow()}catch(e){}}
          document.querySelectorAll('.modal').forEach(m=>m.remove());
          const b=g.querySelector('.export-btn');
          if(!b) return {error:'Import/Exportボタンなし'};
          b.click();
          const field=document.querySelector('.modal textarea.list-text');
          const btn=document.querySelector('.modal .button.import');
          if(!field || !btn) return {error:'Importモーダルなし'};
          field.value=__CSV__;
          btn.click();
          return {count:Number(g.querySelector('.poke-count')?.textContent)};
        })()'''.replace('__INDEX__', str(group_index)).replace('__CSV__', json.dumps(csvtext))
        result = self.eval(js)
        if not isinstance(result, dict) or result.get('count') != len(rows):
            raise RuntimeError(f'グループ{group_index+1} Import検証失敗: {result}')
        # Verify round-tripped CSV and IV / level data, not only the count.
        verify_js = r'''(() => {
          const g=[...document.querySelectorAll('.poke-select-container .poke.multi')][__INDEX__];
          if(typeof closeModalWindow==='function') {try{closeModalWindow()}catch(e){}}
          document.querySelectorAll('.modal').forEach(m=>m.remove());
          g.querySelector('.export-btn').click();
          const f=document.querySelector('.modal textarea.list-text');
          return f ? f.value : null;
        })()'''.replace('__INDEX__', str(group_index))
        exported = self.eval(verify_js)
        if not isinstance(exported, str):
            raise RuntimeError('Export検証でCSVが取得できません')
        parsed = [line for line in csv.reader(io.StringIO(exported)) if line]
        expected = [next(csv.reader([pvpline(r)])) for r in rows]
        # Compare canonical fields; PvPoke may normalize level formatting.
        if len(parsed) != len(expected):
            raise RuntimeError(f'Export行数不一致: {len(parsed)}/{len(expected)}')
        for i, (a,b) in enumerate(zip(parsed, expected), 1):
            if not export_row_matches(a, b):
                raise RuntimeError(f'Export照合失敗 行{i}: {a} != {b}')

    def simulate(self, nleft, nright, pair):
        left_shield, right_shield = pair
        js = r'''(async() => {
          const required=[__LEFT_SHIELD__, __RIGHT_SHIELD__];
          const groups=[...document.querySelectorAll('.poke-select-container .poke.multi')];
          if(groups.length!==2)return {error:'Matrixのグループが2個ではありません'};
          if(typeof closeModalWindow==='function') {try{closeModalWindow()}catch(e){}}
          document.querySelectorAll('.modal').forEach(m=>m.remove());
          for(let i=0;i<2;i++){
            const opt=groups[i].querySelector('.shield-picker .option[value="'+required[i]+'"]');
            if(!opt)return {error:'シールド設定項目なし',group:i};
            opt.click();
          }
          const selected=groups.map(g=>g.querySelector('.shield-picker .option.on')?.getAttribute('value'));
          if(!selected.every((s,i)=>s===String(required[i])))return {error:'シールド設定失敗',selected,required};
          const table=document.querySelector('.matrix-table.rating-table');
          const button=document.querySelector('.battle-btn');
          if(!table||!button)return {error:'Battle画面なし'};
          let changed=false;
          const observer=new MutationObserver(()=>{changed=true});
          observer.observe(table,{childList:true,subtree:true,characterData:true});
          button.click();
          for(let i=0;i<480;i++){
            await new Promise(resolve=>setTimeout(resolve,250));
            const rows=[...table.querySelectorAll('tbody tr')];
            const label=button.querySelector('.btn-label')?.textContent.trim();
            if(changed && label==='Battle' && rows.length===__LEFT__ &&
               rows.every(r=>r.querySelectorAll('td a.rating').length>=__RIGHT__)){
              await new Promise(resolve=>setTimeout(resolve,550));
              observer.disconnect();
              const post=groups.map(g=>g.querySelector('.shield-picker .option.on')?.getAttribute('value'));
              if(!post.every((s,i)=>s===String(required[i])))return {error:'計算後のシールド設定が変更された',post,required};
              const link=document.querySelector('.battle-results.matrix a.download-csv');
              if(!link?.href)return {error:'CSVダウンロードリンクなし'};
              try{
                const response=await fetch(link.href);
                if(!response.ok)return {error:'CSVダウンロード失敗'};
                return {required,selected:post,csv:await response.text()};
              }catch(e){return {error:String(e)}}
            }
          }
          observer.disconnect();
          return {error:'計算時間切れ'};
        })()'''.replace('__LEFT_SHIELD__', str(left_shield)).replace('__RIGHT_SHIELD__', str(right_shield)).replace('__LEFT__', str(nleft)).replace('__RIGHT__', str(nright))
        result = self.eval(js, promise=True)
        if not isinstance(result, dict) or not isinstance(result.get('csv'), str):
            raise RuntimeError(f'{pair} の計算/出力失敗: {result}')
        if result.get('selected') != [str(left_shield), str(right_shield)]:
            raise RuntimeError(f'{pair}: シールド設定の照合失敗 {result.get("selected")}')
        csvrows = list(csv.reader(io.StringIO(result['csv'].lstrip('\ufeff'))))
        if len(csvrows) != nleft + 1:
            raise RuntimeError(f'{pair}: CSV行数が違います ({len(csvrows)}/{nleft+1})')
        if len(csvrows[0]) != nright + 5:
            raise RuntimeError(f'{pair}: CSV列数が違います ({len(csvrows[0])}/{nright+5})')
        if not all(len(row) == nright+5 for row in csvrows):
            raise RuntimeError(f'{pair}: CSV列が欠けています')
        for row in csvrows[1:]:
            for cell in row[1:nright+1]:
                rating = float(cell)
                if not 0 <= rating <= 1000:
                    raise RuntimeError(f'{pair}: レーティング異常: {cell}')
            counts = [int(x) for x in row[1+nright:4+nright]]
            if sum(counts) != nright:
                raise RuntimeError(f'{pair}: 勝敗数が対戦相手数と一致しません {counts}')
        return csvrows

    def close(self):
        try:
            self.ws.close()
        finally:
            try:
                urllib.request.urlopen(CDP + '/json/close/' + self.id, timeout=5).close()
            except Exception:
                pass


def chunks(array, size):
    return [(n, array[n:n+size]) for n in range(0, len(array), size)]


def run(refresh=False, shield_set='all'):
    gm, candidates, opponents = prepare(refresh=refresh)
    pairs = SCENARIOS[shield_set]
    info = chromium_connect()
    OUT.mkdir(parents=True, exist_ok=True)
    print('Chromium:', info.get('Browser'))
    # A fresh cache ID whenever game data, inputs, or scenario choices change.
    gamemaster_hash = hashlib.sha256((DATA/'gamemaster.json').read_bytes()).hexdigest()
    pokemonjs_hash = hashlib.sha256((DATA/'Pokemon.js').read_bytes()).hexdigest()
    fingerprint = hashlib.sha256(json.dumps({
        'candidates': candidates, 'opponents': opponents,
        'cp_cap': CP_CAP, 'max_level': MAX_LEVEL,
        'gamemaster_hash': gamemaster_hash, 'pokemonjs_hash': pokemonjs_hash,
        'pairs': pairs, 'version': 3
    }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    parts_dir = OUT / ('parts_' + fingerprint)
    parts_dir.mkdir(parents=True, exist_ok=True)
    run_dir = OUT / ('run_' + fingerprint)
    run_dir.mkdir(parents=True, exist_ok=True)
    data = {pair: {'labels': [None] * len(candidates), 'ratings': [[] for _ in candidates],
                   'counts': [[0,0,0] for _ in candidates], 'headers': []} for pair in pairs}
    total = math.ceil(len(candidates) / CAND_CHUNK) * math.ceil(len(opponents) / OPP_CHUNK)
    n = 0
    for ci, cpart in chunks(candidates, CAND_CHUNK):
        for oi, opart in chunks(opponents, OPP_CHUNK):
            n += 1
            print(f'\nBatch {n}/{total}: 自分{ci+1}-{ci+len(cpart)}, 相手{oi+1}-{oi+len(opart)}', flush=True)
            part_paths = {pair: parts_dir / f"c{ci:05d}_o{oi:05d}_{result_filename(pair)}" for pair in pairs}
            rows_by_pair = {}
            pending = []
            for pair, path in part_paths.items():
                if path.exists():
                    with path.open(encoding='utf-8-sig', newline='') as f:
                        rows_by_pair[pair] = list(csv.reader(f))
                    print(f'  保存済み {result_filename(pair)} を再利用')
                else:
                    pending.append(pair)
            if pending:
                page = Page()
                try:
                    page.wait_ready()
                    page.import_group(0, cpart)
                    page.import_group(1, opart)
                    for pair in pending:
                        print(f'  自分{pair[0]}枚 / 相手{pair[1]}枚 計算中...', flush=True)
                        result = page.simulate(len(cpart), len(opart), pair)
                        rows_by_pair[pair] = result
                        temp = part_paths[pair].with_suffix('.tmp')
                        with temp.open('w', newline='', encoding='utf-8-sig') as f:
                            csv.writer(f).writerows(result)
                        temp.replace(part_paths[pair])
                finally:
                    page.close()
            for pair in pairs:
                result = rows_by_pair[pair]
                if len(result) != len(cpart)+1 or len(result[0]) != len(opart)+5:
                    raise RuntimeError(f'{pair}: 保存済みCSVの形式が不正です')
                for j, r in enumerate(result[1:]):
                    candidate = cpart[j]
                    expected_ivs = f'{candidate["atk"]}/{candidate["def"]}/{candidate["hp"]}'
                    if expected_ivs not in r[0]:
                        raise RuntimeError(f'Row {j}: CSVの個体値を照合できません: {r[0]} / {expected_ivs}')
                    a = ci+j
                    old = data[pair]['labels'][a]
                    if old is not None and old != r[0]:
                        raise RuntimeError(f'Row {j}: 同じ候補のCSV行名が一致しません')
                    data[pair]['labels'][a] = r[0]
                    data[pair]['ratings'][a].extend(r[1:1+len(opart)])
                    counts = [int(x) for x in r[1+len(opart):4+len(opart)]]
                    if sum(counts) != len(opart):
                        raise RuntimeError(f'勝敗数が対戦相手数と一致しません: {counts}')
                    for k in range(3):
                        data[pair]['counts'][a][k] += counts[k]
                heads = result[0][1:1+len(opart)]
                if ci == 0:
                    data[pair]['headers'].extend(heads)
                elif data[pair]['headers'][oi:oi+len(opart)] != heads:
                    raise RuntimeError('相手ラベルがチャンク間で一致しません')
                print(f'  {result_filename(pair)} OK')
    exports = []
    for pair in pairs:
        dest = run_dir / result_filename(pair)
        # Validate ALL rows before writing outputs to avoid half-correct files.
        for i, label in enumerate(data[pair]['labels']):
            ratings = data[pair]['ratings'][i]
            counts = data[pair]['counts'][i]
            if label is None or len(ratings) != len(opponents) or sum(counts) != len(opponents):
                raise RuntimeError(f'{pair}: {i}番目のデータ数が違います')
        temp = dest.with_suffix('.tmp')
        with temp.open('w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow([''] + data[pair]['headers'] + ['Wins','Losses','Draws','Average'])
            for i, label in enumerate(data[pair]['labels']):
                ratings = data[pair]['ratings'][i]
                counts = data[pair]['counts'][i]
                avg = sum(map(float, ratings)) / len(ratings)
                w.writerow([label] + ratings + counts + [round(avg, 2)])
        temp.replace(dest)
        exports.append(dest)
        print('保存:', dest)
    manifest = {
        'created_at': datetime.now(timezone.utc).isoformat(),
        'cp_cap': CP_CAP, 'max_level': MAX_LEVEL,
        'gamemaster_timestamp': gm.get('timestamp'),
        'gamemaster_sha256': gamemaster_hash, 'pokemonjs_sha256': pokemonjs_hash,
        'candidate_count': len(candidates), 'opponent_count': len(opponents),
        'shield_pairs': [list(p) for p in pairs], 'fingerprint': fingerprint,
        'description': 'CP <= 1500; maximal legal 0.5 step; score interpretation delegated to ChatGPT.'
    }
    (run_dir/'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    archive = run_dir / 'pvpoke_results.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for path in exports + [run_dir/'manifest.json', CAND, OPPS,
                               DIR/'prepared_candidates.csv', DIR/'prepared_opponents.csv']:
            z.write(path, arcname=path.name)
    latest = DIR / 'pvpoke_results_latest.zip'
    shutil.copy2(archive, latest)
    print(f'\n完了: {len(pairs)}条件のCSVと一括アップロード用ZIP: {latest}')
    print(f'今回の計算結果の保存場所: {run_dir}')



def main():
    parser = argparse.ArgumentParser(description='PvPoke Matrix 個体値一括シミュレーション')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--setup', action='store_true', help='入力CSV雛形を作る')
    group.add_argument('--prepare', action='store_true', help='レベル・CPだけ計算し事前確認')
    group.add_argument('--run', action='store_true', help='PvPokeで指定シールド条件を実行してCSV保存')
    parser.add_argument('--refresh', action='store_true', help='PvPokeデータを再取得')
    parser.add_argument('--shields', choices=['all', 'equal', 'disadvantage'], default='all', help='6条件／同枚数3条件／不利3条件（--runに使用）')
    args = parser.parse_args()
    try:
        if args.setup:setup()
        elif args.prepare:prepare(args.refresh)
        elif args.run:run(args.refresh, args.shields)
    except KeyboardInterrupt:
        print('\n中断しました')
        sys.exit(130)
    except Exception as e:
        print('\nエラー:', e)
        print('入力CSV、PvPokeの画面構造、Chromium接続を確認してください。')
        sys.exit(1)

if __name__ == '__main__':
    main()
