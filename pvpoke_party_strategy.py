"""Stage D orchestration, exact-cell cache, and predeclared work criteria.

No UI code or calls to the external ChatGPT PvPoke connector. Reuses the party
worker's shared execution reservation, but never IV inputs, results or ZIPs.
"""
from __future__ import annotations
import json
import hashlib
import math
import time
from pvpoke_party_core import digest, lookup, rank_partial, team_summary
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


REFINEMENT_VERSION = 'party-roles-v1'
MAX_FINALISTS = 3
MAX_TARGETS = 3


def refinement_targets(rosters, opponents, matrix, weights):
    """One shared stress set, chosen BEFORE details; no per-plan cherry picking."""
    def risk(row):
        bests = [[lookup(matrix, p, row['id']) for p in roster] for roster in rosters]
        known = all(v is not None for values in bests for v in values)
        weakest = min(max(values) for values in bests) if known else None
        return (not known, -(weights.get(row['id'], 0)),
                weakest if known else 1001, row['id'])
    # Collapse exact duplicates only. Different legal move/IV hypotheses stay separate.
    return sorted({p['id']: p for p in opponents}.values(), key=risk)[:MAX_TARGETS]


def compact_roles(normal, fast, absorb, conserve):
    """Facts from fixed policies; no best-policy oracle and no Rating inference."""
    results = (normal, fast, absorb, conserve)
    if any(r.get('status') != 'calculated' for r in results):
        return {'status': 'unknown', 'pressure': None, 'absorb': None, 'conserve': None}
    fast_fraction = fast['damage'][0]['fast'] / fast['initial'][1]['max_hp']
    work = work_after_hit(absorb, {'kind': 'fast_damage', 'hp_fraction': .15})
    shield_work = work_after_hit(absorb, {'kind': 'force_shield'})
    received = work['received_charged']
    return {'status': 'calculated',
        'standard_rating': normal['rating'],
        'pressure': fast_fraction >= .5,
        'fast_damage_fraction': round(fast_fraction, 6),
        'fast_breakthrough': fast['breakthrough'],
        'absorb': (work['survived_first_hit'] and
                   (work['achieved'] or shield_work['achieved'])) if received else None,
        'work': work, 'shield_work': shield_work,
        'conserve': conserve['rating'] > 500,
        'conserve_rating': conserve['rating'],
        'conserve_shields_remaining': conserve['terminal'][0]['shields']}


def role_team_summary(roster, targets, cells, weights):
    """Coverage of declared roles in sampled conditions, not match win chance."""
    metrics, evidence = {}, {}
    for role in ('pressure', 'absorb', 'conserve'):
        covered = known = 0.0
        evidence[role] = []
        for target in targets:
            tid = target['id']
            vals = [cells.get((p, tid), {}).get(role) for p in roster]
            responders = [p for p, v in zip(roster, vals) if v]
            if responders:
                known += weights[tid]
                covered += weights[tid]
                evidence[role].append({'opponent': tid, 'members': responders})
            elif all(v is not None for v in vals):
                known += weights[tid]
        metrics[role] = {'coverage': round(covered, 6), 'known_weight': round(known, 6)}
    return {'metrics': metrics, 'evidence': evidence}


def rank_refined(plans, opponents, matrix, weights, *, include_chase):
    """Unknown never lowers a candidate: hold the ENTIRE shortlist order instead."""
    roles = {'pressure': .25, 'absorb': .25, 'conserve': .35}
    if include_chase:
        roles['chase'] = .15
    complete = all(team_summary(p['roster'], opponents, matrix, weights)['complete'] and
                   all(p['detail']['metrics'][k]['known_weight'] >= 1 - 1e-9
                       for k in roles) for p in plans)
    for p in plans:
        metrics = p['detail']['metrics']
        p['detail']['score'] = round(sum(w * metrics[k]['coverage'] for k, w in roles.items()) /
                                           sum(roles.values()), 6) if complete else None
    if complete:
        # Preserve known coverage holes and their depth. Details discriminate
        # between comparable shortlists; they cannot erase a sole static answer.
        plans.sort(key=lambda p: (*rank_partial(p['roster'], opponents, matrix, weights)[:3],
                                 -p['detail']['score'],
                                 *rank_partial(p['roster'], opponents, matrix, weights)[3:],
                                 p['static_rank']))
    for i, p in enumerate(plans, 1):
        p['rank'] = i
    return complete


def classify_pair(a, b, targets, cells, matrix):
    """Directional rescue roles plus raw role evidence, separately from static BR."""
    result = {}
    for role in ('pressure', 'absorb'):
        known, evidence, rescue = 0, [], []
        for target in targets:
            tid = target['id']
            vals = [cells.get((p, tid), {}).get(role) for p in (a, b)]
            if any(v is None for v in vals):
                continue
            known += 1
            for member, other, value in ((a, b, vals[0]), (b, a, vals[1])):
                if value:
                    evidence.append({'member': member, 'opponent': tid})
                    rating = lookup(matrix, other, tid)
                    if rating is not None and rating <= 500:
                        rescue.append({'member': member, 'covers_for': other, 'opponent': tid})
        result[role] = {'status': 'calculated' if known == len(targets) and targets else 'unknown',
                        'evaluated': known, 'total': len(targets),
                        'evidence': evidence, 'rescue': rescue}
    return result


class StrategyAnalysis:
    def __init__(self, builder, jid, version, engine, work):
        self.builder, self.jid, self.version = builder, jid, version
        self.engine, self.work = engine, work
        self.gamemaster_hash = hashlib.sha256((engine.DATA / "gamemaster.json").read_bytes()).hexdigest()
        self.client = None
        self.memo = {}
        self.progress = 20
        self.stats = {'hits': 0, 'computed': 0, 'new_battles': 0, 'compute_seconds': 0,
                      'cache_seconds': 0, 'node_peak_rss_mb': None, 'memory_hits': 0}

    def resolve(self, action, request):
        if self.builder._cancel:
            raise ValueError('cancelled')
        key = cell_key(self.version, action, {"gamemaster_hash": self.gamemaster_hash, "request": request})
        if key in self.memo:
            self.stats['memory_hits'] += 1
            return self.memo[key]
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
                self.memo[key] = json.loads(row[0])
                return self.memo[key]
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
        self.memo[key] = value
        self.builder._record(self.jid, 'running', {'progress': self.progress, 'message': '詳細条件を比較しています', 'cache': self.stats})
        return value

    def refine(self, baseline, finalists, rows, targets, matrix, weights):
        """Bounded second pass: <=24 own rows * 3 targets * 4 detail policies.

        At most four lead/switch prefixes plus eight chases. All are exact-cache
        requests; the cap is independent of the original pool/meta sizes.
        """
        started = time.monotonic()
        self.progress = 96
        plans = [dict(p, roster=list(p['roster']), static_rank=i + 1)
                 for i, p in enumerate(finalists[:MAX_FINALISTS])]
        rosters = [baseline] + [p['roster'] for p in plans]
        selected = refinement_targets(rosters, targets, matrix, weights)
        own = sorted({p for roster in rosters for p in roster})
        total = sum(weights.get(p['id'], 0) for p in selected)
        target_weights = {p['id']: weights.get(p['id'], 0) / total for p in selected} if total else {}
        cells = {}
        try:
            for pid in own:
                for target in selected:
                    tid = target['id']
                    if any(rows[x]['species'].startswith('minior') for x in (pid, tid)):
                        cells[pid, tid] = {'status': 'unknown', 'reason': 'メテノの固定戦略は未対応'}
                        continue
                    standard = {'kind': 'standard'}
                    base = {'self': combat(rows[pid]), 'opponent': combat(target), 'shields': [2, 2],
                            'initial': [{}, {}], 'bait': [True, True],
                            'attack_policies': ['standard', 'standard'],
                            'shield_policies': [standard, standard], 'public_moves': True}
                    normal = self.resolve('detail', base)
                    fast = self.resolve('detail', dict(base, attack_policies=['fast_only', 'standard']))
                    absorb = self.resolve('detail', dict(base, shields=[0, 2]))
                    conserve_policy = {'kind': 'conserve', 'danger_ratio': .95, 'reserve': 1}
                    conserve = self.resolve('detail', dict(base, public_moves=False,
                        shield_policies=[conserve_policy, conserve_policy]))
                    cells[pid, tid] = compact_roles(normal, fast, absorb, conserve)
            unique_rosters = {tuple(r): r for r in rosters}
            summaries = {}
            include_chase = len({p['roster_clause_id'] for p in selected}) >= 2
            for key, roster in unique_rosters.items():
                summary = role_team_summary(roster, selected, cells, target_weights)
                summary['branch'] = {'status': 'unknown', 'reason': '後追いの異なる種族条件が不足'}
                if include_chase:
                    summary['branch'] = self._refine_branch(roster, rows, selected, cells, matrix)
                    branch = summary['branch']
                    summary['metrics']['chase'] = {
                        'coverage': branch['worst_rating'] / 1000
                                    if branch['status'] == 'calculated' else 0,
                        'known_weight': 1 if branch['status'] == 'calculated' else 0}
                summaries[key] = summary
            for p in plans:
                p['detail'] = dict(summaries[tuple(p['roster'])])
                p['summary'] = team_summary(p['roster'], [t['id'] for t in targets], matrix, weights)
            complete = rank_refined(plans, [t['id'] for t in targets], matrix, weights,
                                    include_chase=include_chase)
            return {'version': REFINEMENT_VERSION, 'status': 'calculated' if complete else 'unknown',
                'ranking_changed': any(p['rank'] != p['static_rank'] for p in plans),
                'finalists': plans, 'targets': [p['id'] for p in selected],
                'target_weights': target_weights, 'target_count': len(targets),
                'baseline': summaries[tuple(baseline)],
                'cells': [{'member': p, 'opponent': q, **value} for (p, q), value in cells.items()],
                'cache': self.stats, 'elapsed_seconds': round(time.monotonic() - started, 3),
                'budget': {'max_finalists': MAX_FINALISTS, 'max_targets': MAX_TARGETS,
                           'max_detail_cells': 288, 'max_branch_requests': 12},
                'criteria': {'pressure': '通常技限定・2-2で相手最大HPの50%以上を削る',
                    'absorb': '0-2で最初のゲージ技を生存し、その後通常技で15%以上削るかシールドを奪う',
                    'conserve': '双方が1枚温存する固定方針・技非公開、Rating>500',
                    'chase': '固定した初手→引き先に対する標本内の最悪後追いRating / 1000（標準PvPoke参照）'},
                'ranking_rule': '未計算があれば順位維持。静的な未対応数・深刻度を優先し、同等案を役割指標で比較（通常技25・受け25・温存35・後追い15）。後追い条件なしは残りを正規化。',
                'unknown': ['標本外の詳細条件', '交代再開・残り2体の実対戦・交代タイマー',
                            '完全な3対3・実戦勝率', '相手IVの感度分析'],
                'scope': '一次探索の上位案・重要度順の最大3技/IV仮説のみ。全メタ・全選出の保証ではありません'}
        finally:
            if self.client:
                self.client.close()

    def _refine_branch(self, roster, rows, targets, cells, matrix):
        # Declare one safe switch against the entire sampled set, NOT a separate
        # best action after discovering which opponent chose to chase.
        if any(cells.get((p, t['id']), {}).get('conserve_rating') is None
               for p in roster for t in targets):
            return {'status': 'unknown', 'reason': '引き先を選ぶための詳細条件が未計算'}
        safe = max(sorted(roster), key=lambda p: min(cells[p, t['id']]['conserve_rating'] for t in targets))
        enemy_lead = targets[0]
        options = [p for p in roster if p != safe]
        if any(lookup(matrix, p, enemy_lead['id']) is None for p in options):
            return {'status': 'unknown', 'reason': '初手の標準条件が未計算'}
        lead = min(options, key=lambda p: (lookup(matrix, p, enemy_lead['id']), p))
        base = {'lead': combat(rows[lead]), 'safe': combat(rows[safe]),
                'opponent_lead': combat(enemy_lead), 'shields': [2, 2], 'bait': [True, True],
                'lead_turns': 2, 'chase_delay_turns': 2}
        prefix = self.resolve('switch_prefix', base)
        chases = []
        for target in targets:
            if target['roster_clause_id'] == enemy_lead['roster_clause_id']:
                continue
            branch = self.resolve('switch_branch', dict(base, chaser=combat(target), prefix=prefix))
            chases.append({'opponent': target['id'], 'status': branch['status'],
                           'rating': branch.get('chase', {}).get('rating'),
                           'realized': branch.get('realized'), 'reason': branch.get('reason')})
        complete = all(c['status'] == 'calculated' for c in chases)
        return {'status': 'calculated' if complete else 'unknown',
                'lead': lead, 'safe': safe, 'opponent_lead': enemy_lead['id'], 'chases': chases,
                'remaining_two': {'status': 'unknown', 'members': [lead] + [p for p in roster if p not in (lead, safe)][:1]},
                'worst_rating': min(c['rating'] for c in chases) if complete else None,
                'model': '標本内の限定分岐。初手・引き先は固定、残り2体との連携は未評価'}

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
