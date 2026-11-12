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
from pvpoke_tactic_search import TacticSearch, TacticSearchError, _requested_actions_completed

SCHEMA = 'missing-tactic-evidence-v1'
MAX_SEARCHES = 6
MAX_PATHS_SHOWN = 8


class TacticEvidenceUnavailable(ValueError):
    """The saved role or tactic evidence is stale, corrupt, or no longer complete."""


def _information_assumptions(candidate):
    """Conservatively disclose unobserved choices a fixed script assumes.

    This is an *explanation of counterfactual inputs*, never a prediction of
    live reproducibility or proof that a hidden choice is necessary to win.
    """
    spec = candidate['spec']
    actions = spec['actions']
    decisions = spec['shield_decisions']
    assumptions = ['fixed_timed_self_actions']
    if any(action['actor'] == 1 for action in actions):
        assumptions.append('prespecified_opponent_actions')
    # Even an "original" seed may prescribe an exact enemy charged move.
    # The current move name cannot be observed at shield-commitment time.
    if any(action['actor'] == 1 and action['kind'] == 'charged'
           for action in actions):
        assumptions.append('unrevealed_opponent_charged_move_assumed')
    if any(choice['defender'] == 1 for choice in decisions):
        assumptions.append('assumed_opponent_shield_choice')
    if (any(choice['defender'] == 0 for choice in decisions) and
            any(action['actor'] == 1 and action['kind'] == 'charged'
                for action in actions)):
        # In GO, the charged move's identity has not been shown when the
        # defending player must commit to shielding or not shielding.
        assumptions.append('own_shield_before_opponent_move_reveal')
    return assumptions


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
            self_executed = actual is not None and _requested_actions_completed(
                candidate['spec'], actual['summary'], candidate['self_actions'])
            opponent_executed = actual is not None and _requested_actions_completed(
                candidate['spec'], actual['summary'], candidate['opponent_actions'])
            shields_honored = actual is not None and all(
                row['used'] is row['requested'] for row in actual['shield_results'])
            if actual is not None and (self_executed != cell['all_self_executed'] or
                    opponent_executed != cell['opponent_response_executed'] or
                    shields_honored != cell['all_requested_shields_honored']):
                raise TacticEvidenceUnavailable('Tactic action or shield coverage is inconsistent')

            for slot, standard_cell in paired:
                distinct = (build, slot, key)
                if distinct in seen:
                    continue
                seen.add(distinct)
                checked[build, slot] += 1
                eligible_result = actual is not None and self_executed and opponent_executed and shields_honored
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
                    'all_requested_actions_executed': bool(actual is not None and
                                                           self_executed and opponent_executed),
                    'all_requested_shields_honored': bool(shields_honored),
                    'classification': 'opponent_response_dependent'
                        if candidate['response'] != 'original' else 'specific_fixed_script',
                    'reproducibility': 'not_verified',
                    'observation_conditioned': False,
                    'information_assumptions': _information_assumptions(candidate),
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
            own, opponent = eligible[build, slot][0]['spec']['combatants']
            conditions.append({
                'condition_id': slot,
                'standard': standard[build, slot],
                'tested_scripts': checked[build, slot],
                'matching_scripts': matches[build, slot],
                'unfavorable_shields': own['initial']['shields'] < opponent['initial']['shields'],
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
    # Advisory ranking is intentionally separate from the immutable role
    # evaluation. Partial exploration, different fixed scripts per matchup and
    # unknown opponent decisions cannot establish practical substitutability.
    all_path_builds = sum(item['theoretical_all_conditions'] for item in builds)
    for item in builds:
        conditions = item['conditions']
        supported = sum(c['matching_scripts'] > 0 for c in conditions)
        tested = sum(c['tested_scripts'] > 0 for c in conditions)
        shield_advantage = sum(c['unfavorable_shields'] and c['matching_scripts'] > 0
                               for c in conditions)
        unique = item['theoretical_all_conditions'] and all_path_builds == 1
        item['advisory'] = {
            'scope': 'selected_builds_and_saved_scripts_only',
            'classification': 'conditional_theoretical' if item['theoretical_all_conditions'] else 'pending',
            'role_priority': role['definition']['priority'],
            'required_conditions': len(requirements),
            'tested_conditions': tested,
            'theoretical_supported_conditions': supported,
            'unfavorable_shield_conditions': shield_advantage,
            'only_observed_complete_build': bool(unique),
            'practical_substitution': 'not_established',
            'reason_code': ('all_declared_conditions_have_individual_fixed_script_paths'
                            if item['theoretical_all_conditions'] else
                            'unverified_or_missing_role_conditions'),
        }
    # Only a reference ordering of the submitted, saved scripts. In particular
    # do not sort the original role candidate records or update their status.
    ranked = sorted(builds, key=lambda item: (
        not item['theoretical_all_conditions'],
        -item['advisory']['unfavorable_shield_conditions'],
        -item['advisory']['theoretical_supported_conditions'],
        -item['advisory']['tested_conditions'], item['build_id']))
    for position, item in enumerate(ranked, 1):
        item['advisory']['evidence_order'] = position
    return {
        'schema': SCHEMA, 'evaluation_id': evaluation_id, 'standard_state': role['state'],
        'status': 'counterfactual_only', 'information_fairness': 'not_established',
        'live_reproducibility': 'not_verified', 'new_battles': 0,
        'searched_count': len(search_ids), 'builds': builds,
        'note': 'Specific scripted outcomes never overwrite standard results or establish live role coverage.',
    }
