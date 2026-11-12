"""Read-only comparison of bounded scripted tactics with a saved missing-role evaluation.

This module deliberately never changes the standard battle, ownership, or role
evaluation. A verified native script is counterfactual evidence, not a claim
that the tactic is reproducible using information available to a live player.
"""
from __future__ import annotations

from collections import defaultdict

from pvpoke_battle_service import _json_hash
from pvpoke_battle_store import BattleStoreError
from pvpoke_missing_analysis import MissingAnalysis, battle_facts
from pvpoke_ownership import build_id
from pvpoke_role_evaluation import RoleEvaluation, _hash, _meets, condition_id
from pvpoke_tactic_search import TacticSearch, TacticSearchError

SCHEMA = 'missing-tactic-evidence-v1'
MAX_SEARCHES = 6
MAX_PATHS_SHOWN = 8


class TacticEvidenceUnavailable(ValueError):
    """The saved role or tactic evidence is stale, corrupt, or no longer complete."""


def _required_slots(cell, requirements):
    """One normalized saved matchup may match an exact or full-HP role anchor."""
    slots = [condition_id(cell['spec'])]
    if cell.get('starts_at_full_hp'):
        slots.append(condition_id(cell['spec'], full_hp=True))
    return [slot for slot in slots if slot in requirements]


def compare_tactics(service, evaluation_id, search_ids):
    """Associate independently persisted Sandbox outcomes with exact declared roles.

    The return never upgrades covered/gap status and does not start a battle.
    The approved owner is derived exclusively from service.store.
    """
    _hash(evaluation_id)
    if (type(search_ids) is not list or not 1 <= len(search_ids) <= MAX_SEARCHES or
            any(type(value) is not str for value in search_ids) or len(set(search_ids)) != len(search_ids)):
        raise ValueError('Expected 1–6 distinct saved tactic searches')
    for search_id in search_ids:
        _hash(search_id)

    role = RoleEvaluation(service.store).history(evaluation_id)
    if role is None:
        raise ValueError('Role evaluation is not available for this owner')
    if role['active_versions'] != service.versions or role['plan_versions'] != service.versions:
        raise TacticEvidenceUnavailable('Role evaluation uses an older calculation version')
    evidence = MissingAnalysis(service.store).evidence(
        role['analysis_id'], active_versions=service.versions, normalizer=service)
    if (evidence is None or evidence['ledger_revision'] != role['ledger_revision']
            or _json_hash(evidence['cells']) != role['evidence_digest']):
        raise TacticEvidenceUnavailable('Role evaluation evidence changed; evaluate it again')

    requirements = role['definition']['requirements']
    eligible = defaultdict(list)
    standard = {}
    for cell in evidence['cells']:
        build = cell['build_id']
        for slot in _required_slots(cell, requirements):
            eligible[build, slot].append(cell)
            standard[build, slot] = {
                'status': cell['state'],
                'battle_key': cell['battle_key'],
                'meets': _meets(requirements[slot], cell['facts']) if cell['state'] == 'complete' else None,
            }

    search = TacticSearch(service)
    active_version = search._version()
    candidate_rows = defaultdict(list)
    checked = defaultdict(int)
    matches = defaultdict(int)
    seen = set()
    for search_id in search_ids:
        saved = search._load(search_id)
        if saved is None:
            raise ValueError('Tactic search is not available for this owner')
        plan, _, cells = saved
        if plan['version'] != active_version:
            raise TacticEvidenceUnavailable('Tactic search uses an older native calculation version')
        seed = plan['seed']
        build = build_id(seed['combatants'][0])
        paired = [(slot, cell) for (candidate, slot), rows in eligible.items() if candidate == build
                  for cell in rows if cell['spec']['combatants'] == seed['combatants']
                  and cell['spec']['rules'] == seed['rules']]
        if not paired:
            raise ValueError('Tactic search does not correspond to any required matchup')
        for index, cell in enumerate(cells):
            candidate = plan['candidates'][index]
            tactic_spec, _ = search.sandbox.prepare(candidate['spec'])
            if tactic_spec != candidate['spec']:
                raise TacticEvidenceUnavailable('Tactic normalization changed')
            key = _json_hash(tactic_spec)
            # Every returned complete cell must still have validated owner-scoped native evidence.
            actual = search.sandbox._get(key, tactic_spec) if cell['status'] == 'complete' else None
            if cell['status'] == 'complete' and (actual is None or
                    actual['summary']['battle_key'] != cell['battle_key'] or
                    actual['summary']['outcome'] != cell['outcome']):
                raise TacticEvidenceUnavailable('Completed tactic fact is no longer verifiable')
            actions = {row['action_id']: row['status']
                       for row in actual['summary']['action_results']} if actual is not None else {}
            self_executed = actual is not None and all(
                actions.get(action_id) == 'executed' for action_id in candidate['self_actions'])
            opponent_executed = actual is not None and (
                candidate['opponent_alternate_id'] is None or
                actions.get(candidate['opponent_alternate_id']) == 'executed')
            if actual is not None and (self_executed != cell['all_self_executed'] or
                    opponent_executed != cell['opponent_response_executed']):
                raise TacticEvidenceUnavailable('Tactic action coverage is inconsistent')

            for slot, standard_cell in paired:
                distinct = (build, slot, key)
                if distinct in seen:
                    continue
                seen.add(distinct)
                checked[build, slot] += 1
                eligible_result = actual is not None and self_executed and opponent_executed
                meets = _meets(requirements[slot], battle_facts(actual['summary'])) if eligible_result else None
                if meets:
                    matches[build, slot] += 1
                candidate_rows[build, slot].append({
                    'battle_key': key,
                    'search_id': search_id,
                    'strategy': candidate['strategy'],
                    'opponent_response': candidate['response'],
                    'result_status': cell['status'],
                    'outcome': actual['summary']['outcome'] if actual is not None else None,
                    'meets': meets,
                    'all_requested_actions_executed': eligible_result,
                    'classification': 'opponent_response_dependent'
                        if candidate['response'] != 'original' else 'specific_fixed_script',
                    'reproducibility': 'not_verified',
                })
    builds = []
    for candidate in role['candidates']:
        build = candidate['build_id']
        conditions = []
        supported = set()
        for slot in requirements:
            if (build, slot) not in eligible:
                continue
            items = candidate_rows[build, slot]
            positive = [item for item in items if item['meets'] is True]
            if positive:
                supported.add(slot)
            # Show complete counterexamples as well as possible wins, without
            # needing a large horizontal table or claiming unshown exhaustive coverage.
            rest = [item for item in items if item['meets'] is not True]
            conditions.append({
                'condition_id': slot,
                'standard': standard[build, slot],
                'tested_scripts': checked[build, slot],
                'matching_scripts': matches[build, slot],
                'paths': (positive + rest)[:MAX_PATHS_SHOWN],
                'truncated': len(items) > MAX_PATHS_SHOWN,
            })
        builds.append({
            'build_id': build,
            'standard_meets': candidate['meets'],
            'standard_role_state': role['state'],
            'theoretical_all_conditions': bool(requirements) and len(supported) == len(requirements),
            'conditions': conditions,
            'practical_role_covered': False,
        })
    return {
        'schema': SCHEMA, 'evaluation_id': evaluation_id, 'standard_state': role['state'],
        'status': 'counterfactual_only', 'information_fairness': 'not_established',
        'live_reproducibility': 'not_verified', 'new_battles': 0,
        'searched_count': len(search_ids), 'builds': builds,
        'note': 'Specific scripted outcomes never overwrite standard results or establish live role coverage.',
    }
