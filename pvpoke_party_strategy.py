"""Stage D orchestration, exact-cell cache, and predeclared work criteria.

No UI code or calls to the external ChatGPT PvPoke connector. Reuses the party
worker's shared execution reservation, but never IV inputs, results or ZIPs.
"""
from __future__ import annotations
import json
import hashlib
import math
import time
from pvpoke_party_core import digest
from pvpoke_direct_backend import DirectMatrixClient

SCHEMA = 'strategy-detail-v1'
DETAIL_BUDGET = 16 * 1024 * 1024
COMBAT_FIELDS = ('species', 'fast', 'charged1', 'charged2', 'atk', 'def', 'hp', 'level', 'cp')


def combat(row):
    return {k: row[k] for k in COMBAT_FIELDS}


def integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{name}は{low}〜{high}の整数で指定してください')
    return value


def normalize_config(raw, own, enemy):
    if not isinstance(raw, dict):
        raise ValueError('詳細戦略の条件が必要です')
    cfg = {}
    for key, default, maximum in [('self_index', 0, len(own)-1),
                                  ('opponent_index', 0, len(enemy)-1),
                                  ('lead_index', 1, len(own)-1),
                                  ('closer_index', 2, len(own)-1)]:
        cfg[key] = integer(raw.get(key, default), 0, maximum, key)
    for key in ('self_bait', 'opponent_bait', 'public_moves', 'include_branch'):
        value = raw.get(key, key != 'include_branch')
        if type(value) is not bool:
            raise ValueError(key + 'は真偽値で指定してください')
        cfg[key] = value
    for key in ('manual_self', 'manual_opponent'):
        value = raw.get(key, [False, True, False, True])
        if not isinstance(value, list) or len(value) > 24 or any(type(v) is not bool for v in value):
            raise ValueError('手動シールドは24回以内の真偽値配列です')
        cfg[key] = value
    cfg['lead_turns'] = integer(raw.get('lead_turns', 2), 0, 12, '初手経過ターン')
    cfg['chase_delay_turns'] = integer(raw.get('chase_delay_turns', 2), 0, 12, '後追い遅延ターン')
    cfg['danger_ratio'] = raw.get('danger_ratio', .95)
    if (type(cfg['danger_ratio']) not in (int, float) or
            not math.isfinite(cfg['danger_ratio']) or not .5 <= cfg['danger_ratio'] <= 1):
        raise ValueError('温存危険閾値は0.5〜1です')
    cfg['reserve'] = integer(raw.get('reserve', 1), 0, 2, '温存枚数')
    work = raw.get('work', {'kind': 'charged', 'move_id': own[cfg['self_index']]['charged1']})
    if not isinstance(work, dict) or work.get('kind') not in ('charged', 'fast_damage', 'force_shield'):
        raise ValueError('受け後の仕事の条件を指定してください')
    cfg['work'] = {'kind': work['kind']}
    if work['kind'] == 'charged':
        move = work.get('move_id')
        if move not in [own[cfg['self_index']]['charged1'], own[cfg['self_index']]['charged2']]:
            raise ValueError('仕事のゲージ技は対象ポケモンの技を指定してください')
        cfg['work']['move_id'] = move
    if work['kind'] == 'fast_damage':
        value = work.get('hp_fraction', .15)
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 1:
            raise ValueError('通常技の削り条件は0より大きく1以下です')
        cfg['work']['hp_fraction'] = value
    if cfg['include_branch']:
        if len(enemy) != 6:
            raise ValueError('後追い分析には相手6体が必要です')
        trio = [own[cfg[k]] for k in ('self_index', 'lead_index', 'closer_index')]
        if len({p['roster_clause_id'] for p in trio}) != 3:
            raise ValueError('初手・引き先・残り1体は異なる種族枠で指定してください')
    return cfg


def work_after_hit(result, criterion):
    """Evaluate the criterion AFTER the first opposing charged attack resolves.

    It is deliberately absent from the battle key: changing a report threshold
    must not rerun a battle. Survival and completed work are independent facts.
    """
    hit = next((e for e in result['events'] if e['actor'] == 1 and e['kind'] == 'charged'), None)
    later = [e for e in result['events'] if hit and e['index'] > hit['index'] and e['actor'] == 0]
    fast = sum(e['damage'] for e in later if e['kind'] == 'fast')
    shields = sum(e['shielded'] for e in later if e['kind'] == 'charged')
    charged = [e['move_id'] for e in later if e['kind'] == 'charged']
    achieved = None
    if hit:
        achieved = (criterion['move_id'] in charged if criterion['kind'] == 'charged' else
                    fast >= result['initial'][1]['max_hp'] * criterion['hp_fraction']
                    if criterion['kind'] == 'fast_damage' else shields > 0)
    return {'criterion': criterion, 'received_charged': hit is not None,
            'received_turn': hit['turn'] if hit else None,
            'survived_first_hit': hit['target_hp'] > 0 if hit else None,
            'survived_battle': result['terminal'][0]['hp'] > 0,
            'achieved': achieved, 'fast_damage_after_hit': fast,
            'charged_after_hit': charged, 'shields_taken_after_hit': shields,
            'hp_remaining': result['terminal'][0]['hp'],
            'energy_points_remaining': result['terminal'][0]['energy_points'],
            'opponent_shields_taken_total': result['shields_used'][1],
            'safe_switch': 'unknown'}


def cell_key(version, action, request):
    return digest([SCHEMA, version, action, request, 'optimal', 'pvpoke-default-deterministic'])


class StrategyAnalysis:
    def __init__(self, builder, jid, version, engine, work):
        self.builder, self.jid, self.version = builder, jid, version
        self.engine, self.work = engine, work
        self.gamemaster_hash = hashlib.sha256((engine.DATA / "gamemaster.json").read_bytes()).hexdigest()
        self.client = None
        self.stats = {'hits': 0, 'computed': 0, 'new_battles': 0, 'compute_seconds': 0,
                      'cache_seconds': 0, 'node_peak_rss_mb': None}

    def resolve(self, action, request):
        if self.builder._cancel:
            raise ValueError('cancelled')
        key = cell_key(self.version, action, {"gamemaster_hash": self.gamemaster_hash, "request": request})
        tick = time.monotonic()
        with self.builder._db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS strategy_cells(
                key TEXT PRIMARY KEY, content TEXT NOT NULL, bytes INTEGER NOT NULL,
                accessed INTEGER NOT NULL)''')
            row = db.execute('SELECT content FROM strategy_cells WHERE key=?', (key,)).fetchone()
            if row:
                db.execute('UPDATE strategy_cells SET accessed=? WHERE key=?', (time.time_ns(), key))
                self.stats['hits'] += 1
                self.stats['cache_seconds'] += time.monotonic() - tick
                return json.loads(row[0])
        if self.client is None:
            self.client = DirectMatrixClient(gamemaster=self.engine.DATA / 'gamemaster.json', log_dir=self.work)
        value = self.client.strategy(action, request)
        if value.get('gamemaster_hash') != self.gamemaster_hash:
            raise ValueError('計算中にGameMasterが更新されました。新しい条件で再計算してください')
        self.stats['computed'] += 1
        self.stats['new_battles'] += (1 if action == 'detail' else int('chase' in value)
            if request.get('prefix') else sum(k in value for k in ('opening', 'delay', 'chase')))
        self.stats['compute_seconds'] += time.monotonic() - tick
        if self.client.memory_samples:
            self.stats['node_peak_rss_mb'] = max(s['peak_rss_mb'] for s in self.client.memory_samples)
        content = json.dumps(value, separators=(',', ':'))
        size = len(content.encode())
        with self.builder._db() as db:
            if size <= DETAIL_BUDGET:
                db.execute('INSERT OR REPLACE INTO strategy_cells VALUES(?,?,?,?)', (key, content, size, time.time_ns()))
                used = db.execute('SELECT coalesce(sum(bytes),0) FROM strategy_cells').fetchone()[0]
                for old, old_size in db.execute('SELECT key,bytes FROM strategy_cells ORDER BY accessed').fetchall():
                    if used <= DETAIL_BUDGET:
                        break
                    db.execute('DELETE FROM strategy_cells WHERE key=?', (old,))
                    used -= old_size
        self.builder._record(self.jid, 'running', {'progress': 20, 'message': '詳細条件を比較しています', 'cache': self.stats})
        return value

    def compute(self, own, enemy, cfg):
        try:
            p, q = combat(own[cfg['self_index']]), combat(enemy[cfg['opponent_index']])
            standard = {'kind': 'standard'}
            base = {'self': p, 'opponent': q, 'shields': [2, 2],
                    'initial': [{}, {}], 'bait': [True, True],
                    'attack_policies': ['standard', 'standard'],
                    'shield_policies': [standard, standard], 'public_moves': cfg['public_moves']}
            normal = self.resolve('detail', base)
            fast = self.resolve('detail', dict(base, attack_policies=['fast_only', 'standard']))
            absorb = []
            for fraction in (1, .75):
                r = self.resolve('detail', dict(base, shields=[0, 2], initial=[{'hp_fraction': fraction}, {}]))
                absorb.append({'start_hp_fraction': fraction, 'battle': r, 'work': work_after_hit(r, cfg['work'])})
            comparisons = [{'name': '標準PvPoke', 'battle': normal}]
            for a in (True, False):
                for b in (True, False):
                    if a and b:
                        continue
                    comparisons.append({'name': f'ブラフ 自分{int(a)} / 相手{int(b)}',
                        'battle': self.resolve('detail', dict(base, bait=[a, b]))})
            selected_bait = [cfg['self_bait'], cfg['opponent_bait']]
            conserve = {'kind': 'conserve', 'danger_ratio': cfg['danger_ratio'], 'reserve': cfg['reserve']}
            comparisons.append({'name': '観測情報で温存（双方）', 'battle': self.resolve('detail',
                dict(base, bait=selected_bait, shield_policies=[conserve, conserve]))})
            manual = [{'kind': 'manual', 'decisions': cfg[k]} for k in ('manual_self', 'manual_opponent')]
            comparisons.append({'name': '手動（双方）', 'battle': self.resolve('detail',
                dict(base, bait=selected_bait, shield_policies=manual))})
            branches = []
            if cfg['include_branch']:
                lead = own[cfg['lead_index']]
                enemy_lead = enemy[cfg['opponent_index']]
                # Independent lead diagnostic, never a claimed 3v3 probability.
                diagnostic = self.resolve('detail', dict(base, self=combat(lead)))
                prefix_request = {'lead': combat(lead), 'safe': p,
                    'opponent_lead': combat(enemy_lead), 'shields': [2, 2], 'bait': selected_bait,
                    'lead_turns': cfg['lead_turns'], 'chase_delay_turns': cfg['chase_delay_turns']}
                prefix = self.resolve('switch_prefix', prefix_request)
                for chaser in enemy:
                    if chaser['roster_clause_id'] == enemy_lead['roster_clause_id']:
                        continue
                    r = self.resolve('switch_branch', {'lead': combat(lead), 'safe': p,
                        'opponent_lead': combat(enemy_lead), 'chaser': combat(chaser),
                        'shields': [2, 2], 'bait': selected_bait,
                        'lead_turns': cfg['lead_turns'], 'chase_delay_turns': cfg['chase_delay_turns'], 'prefix': prefix})
                    branches.append({'chaser_id': chaser['id'], 'chaser_species': chaser['species'],
                                     'lead_disadvantage_2_2': diagnostic['rating'] < 500,
                                     'lead_diagnostic_rating': diagnostic['rating'], 'branch': r})
            calculated = sum(r['branch']['status'] == 'calculated' for r in branches)
            return {'kind': 'strategy', 'config': cfg, 'subject': p, 'opponent': q,
                'pressure': {'standard': normal, 'fast_only': fast}, 'absorb': absorb,
                'comparisons': comparisons, 'branches': branches,
                'remaining_two': [combat(own[cfg[k]]) for k in ('lead_index', 'closer_index')],
                'coverage': {'detail_conditions': 9, 'calculated_detail_conditions': 9,
                             'branch_conditions': len(branches), 'calculated_branches': calculated},
                'unknown': ['完全な3対3・実戦勝率', '交代の再開・引き直し・残り2体の実対戦', '試合全体の制限時間・交代タイマー'] +
                           (['後追い分岐（相手6体と分岐設定が必要）'] if not branches else []),
                'calculation_version': self.version, 'schema': SCHEMA, 'cache': self.stats,
                'notes': ['通常技限定は削り性能の比較条件です',
                          '受け後の仕事達成と安全な引き先は別です',
                          '温存は公開情報のダメージ上限を用いる保守ルール。確率・勝率ではありません',
                          'ブラフの1はPvPokeの選択的ブラフ、0はブラフなしです',
                          '標準PvPokeは全情報判断を含む参照値。観測温存・手動のシールド判断とは区別します',
                          '独立した方針の結果。対面ごとの最良値を単一戦略へ合成しません']}
        finally:
            if self.client:
                self.client.close()
