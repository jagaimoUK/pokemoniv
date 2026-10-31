"""Budgeted opponent move/IV sensitivity; fixed responder before hidden conditions.

This is a CP1500/Lv50 stress test of shortlisted rosters, not a 3v3 probability.
Raw battle cells reuse Stage D's versioned cache; weights never enter cell keys.
"""
from functools import lru_cache
import json
import time

from pvpoke_iv_modes import select_opponent_ivs
from pvpoke_party_core import lookup, rank_partial, team_summary
from pvpoke_party_strategy import StrategyAnalysis, combat

VERSION = 'party-uncertainty-v1'
MAX_GROUPS = 2
MAX_MOVESETS = 2
MAX_FINALISTS = 3
MAX_OWN = 24
IV_MODES = ('source', 'rank1', 'attack', 'defense')
MAX_CELLS = MAX_OWN * MAX_GROUPS * MAX_MOVESETS * len(IV_MODES)


def moves_key(row):
    return row['fast'], tuple(sorted((row['charged1'], row['charged2'])))


@lru_cache(maxsize=64)
def selected_ivs(pokemon_json, cpms, mode, moves, cp_cap, level_cap):
    # Immutable data and rules are part of this preparation cache's key.
    return select_opponent_ivs(json.loads(pokemon_json), cpms, mode, moves, cp_cap, level_cap)


def select_groups(rosters, meta, matrix, weights, alternatives):
    grouped = {}
    for row in meta:
        grouped.setdefault(row['meta_group_id'], []).append(row)
    def risk(row):
        values = [[lookup(matrix, p, row['id']) for p in r] for r in rosters]
        return min(max(v) for v in values) if all(x is not None for v in values for x in v) else 1001
    eligible = [g for g in grouped if sum(weights.get(p['id'], 0) for p in grouped[g]) > 0]
    chosen = sorted(eligible, key=lambda g: (-sum(weights.get(p['id'], 0) for p in grouped[g]),
                                           min(risk(p) for p in grouped[g]), g))[:MAX_GROUPS]
    result = []
    for gid in chosen:
        original = sorted(grouped[gid], key=lambda p: (risk(p), p['id']))
        anchor = original[0]
        # Form/shadow groups never get silently merged. User hypotheses take
        # priority after one baseline configuration, then saved meta variants.
        candidates = [anchor] + [p for p in alternatives if p['species'] == anchor['species']] + original
        seen, profiles = set(), []
        for p in candidates:
            key = moves_key(p)
            if key not in seen:
                seen.add(key)
                profiles.append(p)
        result.append({'id': gid, 'species': anchor['species'], 'profiles': profiles[:MAX_MOVESETS],
                       'available_movesets': len(profiles),
                       'weight': sum(weights.get(p['id'], 0) for p in grouped[gid])})
    total = sum(g['weight'] for g in result)
    for group in result:
        group['weight'] /= total
    return result


def summarize_roster(roster, groups, cells):
    """max(self responder) min(opponent hypothesis), never min(max(responder))."""
    reports, d0, guaranteed, complete = [], 0.0, 0.0, True
    unique = []
    for group in groups:
        members = []
        for pid in roster:
            ratings = [cells.get((pid, h['key'])) for h in group['hypotheses']]
            known = bool(ratings) and all(v is not None for v in ratings)
            low, high = (min(ratings), max(ratings)) if known else (None, None)
            members.append({'member': pid, 'status': 'calculated' if known else 'unknown',
                            'worst_rating': low, 'best_rating': high,
                            'spread': high - low if known else None,
                            'robust_answer': low > 500 if known else None,
                            'ratings': ratings})
        known = all(m['status'] == 'calculated' for m in members)
        responders = [m['member'] for m in members if m['robust_answer']]
        best = max(m['worst_rating'] for m in members) if known else None
        # A genuine known responder proves existence, but a missing member's
        # rating can still affect ranking; hold the complete shortlist below.
        if not known:
            complete = False
        else:
            d0 += group['weight'] * (best <= 500)
            guaranteed += group['weight'] * best
            if len(responders) == 1:
                unique.append({'member': responders[0], 'group': group['id']})
        reports.append({'group': group['id'], 'species': group['species'], 'members': members,
                        'status': 'calculated' if known else 'unknown',
                        'responders': responders, 'best_fixed_responder_rating': best})
    return {'status': 'calculated' if complete and groups else 'unknown', 'groups': reports,
            'uncovered_weight': round(d0, 6) if complete and groups else None,
            'guaranteed_rating': round(guaranteed, 3) if complete and groups else None,
            'unique_answers': unique}


def rank_plans(plans, opponents, matrix, weights):
    complete = all(p['uncertainty']['status'] == 'calculated' and
                   team_summary(p['roster'], opponents, matrix, weights)['complete'] for p in plans)
    if complete:
        plans.sort(key=lambda p: (*rank_partial(p['roster'], opponents, matrix, weights)[:3],
                                 p['uncertainty']['uncovered_weight'],
                                 -p['uncertainty']['guaranteed_rating'], p['before_uncertainty_rank']))
    for i, plan in enumerate(plans, 1):
        plan['uncertainty_rank'] = i
    return complete


def analyze(builder, jid, version, engine, work, baseline, finalists, rows, meta, matrix,
            weights, alternatives, catalog, species, cpms):
    tick = time.monotonic()
    plans = [dict(p, before_uncertainty_rank=i + 1) for i, p in enumerate(finalists[:MAX_FINALISTS])]
    rosters = [baseline] + [p['roster'] for p in plans]
    own = sorted({p for roster in rosters for p in roster})
    if len(own) > MAX_OWN or any(len(r) != 6 for r in rosters):
        raise ValueError('技・IV感度比較は基準6体と最大3案・合計24体までです')
    groups = select_groups(rosters, meta, matrix, weights, alternatives)
    runner = StrategyAnalysis(builder, jid, version, engine, work)
    runner.progress = 98
    cells = {}
    try:
        for group in groups:
            hypotheses = {}
            for profile in group.pop('profiles'):
                for mode in IV_MODES:
                    if builder._cancel:
                        raise ValueError('cancelled')
                    raw = combat(profile)
                    try:
                        if mode != 'source':
                            ivs = selected_ivs(json.dumps(species[raw['species']], sort_keys=True), tuple(cpms),
                                mode, (raw['fast'], raw['charged1'], raw['charged2']), engine.CP_CAP, engine.MAX_LEVEL)
                            raw.update(zip(('atk', 'def', 'hp', 'level_override'), ivs))
                        else:
                            raw['level_override'] = raw['level']
                        normalized = builder._normalize([raw], catalog, species, cpms, engine, '相手感度条件')[0]
                        key = normalized['id']
                        if key in hypotheses:
                            hypotheses[key]['iv_modes'].append(mode)
                            continue
                        h = {'key': key, 'iv_modes': [mode], 'combatant': combat(normalized), 'status': 'calculated'}
                    except ValueError as exc:
                        raw['cp'] = None
                        key = f"unknown:{profile['id']}:{mode}"
                        h = {'key': key, 'iv_modes': [mode], 'combatant': raw,
                             'status': 'unknown', 'reason': str(exc)[:200]}
                    hypotheses[key] = h
                    for pid in own:
                        if h['status'] == 'unknown' or raw['species'].startswith('minior'):
                            cells[pid, key] = None
                            h['status'] = 'unknown'
                            h.setdefault('reason', 'メテノの固定戦略は未対応です')
                            continue
                        standard = {'kind': 'standard'}
                        result = runner.resolve('detail', {
                            'self': combat(rows[pid]), 'opponent': h['combatant'], 'shields': [2, 2],
                            'initial': [{}, {}], 'bait': [True, True],
                            'attack_policies': ['standard', 'standard'],
                            'shield_policies': [standard, standard], 'public_moves': True})
                        cells[pid, key] = result['rating'] if result.get('status') == 'calculated' else None
                    h['evaluated_members'] = sum(cells.get((pid, key)) is not None for pid in own)
                    h['requested_members'] = len(own)
                    if h['evaluated_members'] < len(own):
                        h['status'] = 'unknown'
                        h.setdefault('reason', '対面結果に未評価を含みます')
            group['hypotheses'] = list(hypotheses.values())
        for plan in plans:
            plan['uncertainty'] = summarize_roster(plan['roster'], groups, cells)
        complete = rank_plans(plans, [p['id'] for p in meta], matrix, weights)
        baseline_summary = summarize_roster(baseline, groups, cells)
        return {'version': VERSION, 'status': 'calculated' if complete else 'unknown',
                'finalists': plans, 'baseline': baseline_summary, 'groups': groups,
                'ranking_changed': any(p['uncertainty_rank'] != p['before_uncertainty_rank'] for p in plans),
                'budget': {'max_groups': MAX_GROUPS, 'max_movesets': MAX_MOVESETS,
                           'max_iv_modes': len(IV_MODES), 'max_cells': MAX_CELLS},
                'evaluated_cells': sum(v is not None for v in cells.values()), 'requested_cells': len(cells),
                'cache': runner.stats, 'elapsed_seconds': round(time.monotonic() - tick, 3),
                'unused_alternatives': [p['id'] for p in alternatives if p['species'] not in {g['species'] for g in groups}],
                'notes': ['相手の技・IV仮説は使用率や発生確率ではありません',
                          '同じ担当の最悪Ratingを比較します。仮説ごとに担当を変更した最高値ではありません',
                          '一次探索の未対応重み・深刻度を優先し、同等案を頑健性で比較します',
                          'unknownがある場合は感度比較前の全候補順位を維持します',
                          '標準PvPoke・満タンHP・2-2の参照値。技非公開の実行可能方針や3対3勝率ではありません',
                          '重要度上位最大2グループ・各最大2技構成のみ。技構成はメタと追加入力から選びます']}
    finally:
        if runner.client:
            runner.client.close()
