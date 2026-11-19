"""Explicit authenticated app operations for scoped missing Pokémon comparison."""
import os

from pvpoke_battle_service import _integer, _json_hash, _object
from pvpoke_iv_search import BOUNDARY_NAMES, IVSearch, _pool
from pvpoke_missing_analysis import AnalysisUnavailable, MissingAnalysis
from pvpoke_ownership import Ownership, OwnershipConflict, build_id
from pvpoke_role_evaluation import RoleEvaluation, _definition, _hash, condition_id
from pvpoke_sandbox_workspace import enabled as sandbox_enabled, search_enabled, observed_enabled
from pvpoke_tactic_evidence import compare_tactics
from pvpoke_observed_evidence import compare_observed

API_PATH = '/api/missing-analysis'
APP_PATH = '/app-api/missing-analysis'
PAGE_PATH = '/app/missing'
MAX_REQUEST_BYTES = 64 * 1024


def enabled():
    return os.environ.get('PVP_MISSING_ANALYSIS_ENABLED') == '1'


def _can_calculate():
    return os.environ.get('PVP_BATTLE_API_ENABLED') == '1'


def _build(value):
    return _object(value, 'candidate build', ('species_id', 'ivs', 'level', 'moves'))


def _spec(candidate, opponent, shields, energy):
    combatants = []
    for build, shield, starting_energy in zip((candidate, opponent), shields, (energy, 0)):
        combatants.append({**build, 'initial': {'hp': 'full', 'energy': starting_energy,
                                              'shields': shield, 'stages': [0, 0]}})
    return {'schema': 'battle-spec-v1', 'mode': 'standard', 'rules': {'league': 'great', 'cp_cap': 1500},
            'combatants': combatants}


def _plan(service, payload):
    _object(payload, 'missing comparison', ('action', 'candidates', 'scenarios', 'role'))
    raw_builds = payload['candidates']
    scenarios = payload['scenarios']
    role = _object(payload['role'], 'role', ('role_id', 'revision', 'priority'))
    if type(raw_builds) is not list or not 1 <= len(raw_builds) <= 8:
        raise ValueError('Specify 1–8 candidate builds')
    if type(scenarios) is not list or not 1 <= len(scenarios) <= 6:
        raise ValueError('Specify 1–6 matchup conditions')
    builds = [_build(value) for value in raw_builds]
    specs, requirements = [], {}
    for scenario in scenarios:
        _object(scenario, 'matchup condition', ('opponent', 'shields', 'requirement'), ('energy',))
        shields = scenario['shields']
        if type(shields) is not list or len(shields) != 2:
            raise ValueError('Specify both shield counts')
        energy = _integer(scenario.get('energy', 0), 'starting energy', 0, 100)
        opponent = _build(scenario['opponent'])
        normalized, _ = service._prepare(_spec(builds[0], opponent, shields, energy))
        slot = condition_id(normalized, full_hp=True)
        if slot in requirements:
            raise ValueError('Duplicate matchup condition')
        requirements[slot] = scenario['requirement']
        specs.extend(_spec(build, opponent, shields, energy) for build in builds)
    definition = _definition({**role, 'meta_snapshot': _json_hash(sorted(requirements)),
                              'requirements': requirements})
    first = [service._prepare(spec)[0]['combatants'][0] for spec in specs[:len(builds)]]
    order = [build_id(combatant) for combatant in first]
    if len(set(order)) != len(order):
        raise ValueError('Duplicate candidate build')
    return specs, definition, order


def _comparison(service, payload):
    specs, role, order = _plan(service, payload)
    analysis = MissingAnalysis(service.store)
    analysis_id = analysis.save_plan(service, specs)
    evidence = analysis.evidence(analysis_id, active_versions=service.versions, normalizer=service)
    snapshot = RoleEvaluation(service.store)._evaluate(evidence, role, service.versions)
    cells = {cell['battle_key']: cell for cell in evidence['cells']}
    assessed = {item['build_id']: item for item in snapshot['candidates']}
    builds = []
    slot_order = {slot: index for index, slot in enumerate(role['requirements'])}
    for bid in order:
        result = assessed[bid]
        conditions = []
        for slot, test in result['checks'].items():
            cell = cells[test['battle_key']]
            candidate, opponent = cell['spec']['combatants']
            conditions.append({**test, 'spec': cell['spec'], 'opponent': opponent,
                               'requirement': role['requirements'][slot], 'order': slot_order[slot],
                               'shields': [combatant['initial']['shields'] for combatant in (candidate, opponent)],
                               'facts': cell['facts']})
        conditions.sort(key=lambda check: check['order'])
        first = cells[conditions[0]['battle_key']]
        current = {key: value for key, value in first['spec']['combatants'][0].items() if key != 'initial'}
        # A proved win at non-neutral starting energy remains scoped to that setup.
        needs_setup = any(check['spec']['combatants'][0]['initial']['energy'] > 0 for check in conditions)
        if result['meets'] is True:
            status = 'conditional' if needs_setup else 'sufficient'
        else:
            status = 'unavailable' if result['meets'] is False else 'pending'
        inventory = first['inventory_matches']
        builds.append({**current, 'build_id': bid, 'status': status, 'party_substitution': 'pending',
                       'owned_instances': inventory[:32], 'inventory_match_count': len(inventory),
                       'conditions': conditions})
    reference = {'build_id': order[0], 'species_id': builds[0]['species_id']}
    for build in builds:
        build['comparison'] = 'same_species' if build['species_id'] == reference['species_id'] else 'cross_species'
    priority = {'sufficient': 0, 'conditional': 1, 'pending': 2, 'unavailable': 3}
    builds[1:] = sorted(builds[1:], key=lambda build: priority[build['status']])
    return {'state': snapshot['state'], 'evaluation_id': snapshot['evaluation_id'], 'analysis_id': analysis_id,
            'role': {key: role[key] for key in ('role_id', 'priority', 'revision')}, 'reference': reference,
            'candidates': builds, 'can_calculate': _can_calculate(), 'can_sandbox': sandbox_enabled()}


def _explore(service, payload):
    _object(payload, 'IV exploration request',
            ('action', 'evaluation_id', 'build_id', 'budget'), ('iv_floors',))
    selected = _hash(payload['build_id'])
    budget = _integer(payload['budget'], 'IV exploration budget', 0, 32)
    if budget and not _can_calculate():
        raise AnalysisUnavailable('New battle calculation is disabled')
    history = RoleEvaluation(service.store).history(payload['evaluation_id'])
    if history is None or history['active_versions'] != service.versions:
        raise ValueError('Evaluation unavailable for the active game data')
    evidence = MissingAnalysis(service.store).evidence(history['analysis_id'],
                                                       active_versions=service.versions, normalizer=service)
    if evidence is None:
        raise ValueError('Missing evaluation battle plan')
    role = history['definition']
    slots = {condition_id(cell['spec'], full_hp=True): cell['spec'] for cell in evidence['cells']
             if cell['build_id'] == selected and cell.get('starts_at_full_hp')}
    if not role['requirements'].keys() <= slots.keys():
        raise ValueError('Selected build does not contain all role conditions')
    specs = [slots[slot] for slot in role['requirements']]
    explorer = IVSearch(service)
    search_id = explorer.start(specs, iv_floors=payload.get('iv_floors', (0, 0, 0)))
    step = explorer.step(search_id, budget=budget, role=role)
    if step is None or step['coverage'] is None:
        raise AnalysisUnavailable('IV coverage unavailable')
    coverage = step['coverage']
    union_boundaries = {kind: 0 for kind in BOUNDARY_NAMES}
    condition_summaries = []
    for cond in coverage['conditions']:
        cond_boundaries = {}
        for kind in BOUNDARY_NAMES:
            mask = int.from_bytes(bytes.fromhex(cond['boundaries'][kind]), 'little')
            union_boundaries[kind] |= mask
            cond_boundaries[kind] = mask.bit_count()
        condition_summaries.append({
            'condition_id': cond['id'],
            'opponent': cond['opponent'],
            'shields': [cond['self_initial']['shields'], cond['opponent']['initial']['shields']],
            'energy': cond['self_initial']['energy'],
            'completed_count': cond['completed_count'],
            'remaining_count': coverage['eligible_iv_count'] - cond['completed_count'],
            'eligible_iv_count': coverage['eligible_iv_count'],
            'boundary_counts': cond_boundaries,
        })
    boundary_counts = {kind: mask.bit_count() for kind, mask in union_boundaries.items()}
    species_id = step['candidate']['species_id']
    moves = step['candidate']['moves']
    owned_by_iv, species_confirmed_owned_count = Ownership(
        service.store, species_ids=service.species,
    ).species_rows_by_iv(species_id)
    qualifying_hex = coverage['qualifying_ivs'] or ''
    bits = int.from_bytes(bytes.fromhex(qualifying_hex), 'little') if qualifying_hex else 0
    count = bits.bit_count()
    owned_exact_count = 0
    owned_any_count = 0
    absent_recorded_count = 0
    unconfirmed_count = 0
    ranked_examples = []
    if bits:
        rows, _ = _pool(service, specs[0], step['iv_floors'])
        while bits:
            lsb = bits & -bits
            index = lsb.bit_length() - 1
            bits ^= lsb
            row = rows[index]
            ivs = {'attack': row['atk'], 'defense': row['def'], 'hp': row['hp']}
            raw_rows = owned_by_iv.get(index)
            if raw_rows:
                matches = Ownership._match_rows(
                    raw_rows,
                    {'species_id': species_id, 'ivs': ivs, 'level': row['level'], 'moves': moves},
                    row['cp'],
                )
            else:
                matches = []
            has_exact = any(m['state'] == 'confirmed_owned' and m['build_match'] == 'exact' for m in matches)
            has_owned = any(m['state'] == 'confirmed_owned' for m in matches)
            has_unknown = any(m['state'] == 'unknown' for m in matches)
            has_absent = any(m['state'] == 'confirmed_absent' for m in matches)
            if has_exact:
                owned_exact_count += 1
            if has_owned:
                owned_any_count += 1
            elif has_absent and not has_unknown:
                absent_recorded_count += 1
            else:
                unconfirmed_count += 1
            priority = 0 if has_exact else 1 if has_owned else 2
            ranked_examples.append((priority, index, {
                **ivs,
                'level': row['level'],
                'cp': row['cp'],
                'owned_instances': matches[:16],
                'inventory_match_count': len(matches),
            }))
    ranked_examples.sort(key=lambda item: (item[0], item[1]))
    examples = [entry for _, _, entry in ranked_examples[:32]]
    completed = coverage['all_completed_iv_count']
    return {'state': step['state'], 'new_battles': step['new_battles'],
            'retry_needed': any(status != 'complete' and attempts > 0
                                for status, attempts in step['attempt_outcomes'].items()),
            'raw_iv_count': coverage['raw_iv_count'],
            'iv_floors': step['iv_floors'],
            'candidate': {'species_id': species_id, 'moves': moves},
            'eligible_iv_count': coverage['eligible_iv_count'], 'qualifying_count': count,
            'completed_iv_count': completed,
            'fully_tested_nonqualifying_iv_count': completed - count,
            # Every IV lacking at least one required matchup is still not fully
            # tested. This can include known failures; it is *not* a count of
            # possible wins and must never be merged into qualifying_count.
            'not_fully_tested_iv_count': (
                coverage['eligible_iv_count'] - completed),
            'conditions': condition_summaries,
            'boundary_counts': boundary_counts,
            'ownership_summary': {
                'confirmed_owned_exact_count': owned_exact_count,
                'confirmed_owned_count': owned_any_count,
                'confirmed_absent_recorded_count': absent_recorded_count,
                'unconfirmed_count': unconfirmed_count,
                'species_confirmed_owned_count': species_confirmed_owned_count,
            },
            'qualifying': examples, 'can_calculate': _can_calculate()}


def _opponent_boundaries(service, payload):
    """Restrict static opponent profiling to one saved, same-owner matchup."""
    _object(payload, 'opponent IV boundaries', (
        'action', 'evaluation_id', 'build_id', 'battle_key'), ('iv_floors',))
    if not _can_calculate():
        raise AnalysisUnavailable('Opponent IV profiling is disabled')
    build = _hash(payload['build_id'])
    battle_key = _hash(payload['battle_key'])
    history = RoleEvaluation(service.store).history(payload['evaluation_id'])
    if (history is None or history['active_versions'] != service.versions
            or history['plan_versions'] != service.versions):
        raise ValueError('Saved role evaluation is unavailable for the active game data')
    evidence = MissingAnalysis(service.store).evidence(
        history['analysis_id'], active_versions=service.versions, normalizer=service)
    if evidence is None or evidence['versions'] != service.versions:
        raise ValueError('Saved matchup evidence is unavailable')
    candidate = next((cell for cell in evidence['cells']
                      if cell['build_id'] == build and cell['battle_key'] == battle_key
                      and cell.get('starts_at_full_hp') and
                      condition_id(cell['spec'], full_hp=True)
                      in history['definition']['requirements']), None)
    if candidate is None:
        raise ValueError('Opponent boundary matchup is not part of this saved role')
    return IVSearch(service).opponent_boundaries(
        candidate['spec'], iv_floors=payload.get('iv_floors', (0, 0, 0)))


def _ownership_list(service, payload):
    _object(payload, 'ownership list', ('action',),
            ('after', 'limit', 'species_id', 'state', 'include_scopes', 'scope_limit'))
    inventory = Ownership(service.store, species_ids=service.species)
    return inventory.list_snapshot(
        after=payload.get('after', ''),
        limit=payload.get('limit', 64),
        species_id=payload.get('species_id'),
        state=payload.get('state'),
        include_scopes=payload.get('include_scopes', True),
        scope_limit=payload.get('scope_limit', 32),
    )


def _ownership_history(service, payload):
    _object(payload, 'ownership history', ('action', 'instance_id'), ('after_revision', 'limit'))
    inventory = Ownership(service.store, species_ids=service.species)
    history = inventory.instance_history(
        payload['instance_id'],
        after_revision=payload.get('after_revision', 0),
        limit=payload.get('limit', 32),
    )
    if history is None:
        raise ValueError('Unknown inventory instance')
    return history


def _ownership_scope(service, payload):
    _object(payload, 'ownership scope confirmation', (
        'action', 'event_id', 'expected_ledger_revision', 'species_id',
        'search', 'box_range', 'complete', 'absence_confirmed',
    ))
    inventory = Ownership(service.store, species_ids=service.species)
    event = inventory.confirm_scope(
        payload['event_id'],
        expected_ledger_revision=payload['expected_ledger_revision'],
        species_id=payload['species_id'],
        search=payload['search'],
        box_range=payload['box_range'],
        complete=payload['complete'],
        absence_confirmed=payload['absence_confirmed'],
    )
    status = inventory.scope_status(event['event_id'])
    return status if status is not None else {**event, 'current': False}


def app_operation(service, payload):
    action = payload.get('action')
    if action == 'evaluate':
        return _comparison(service, payload)
    if action == 'explore':
        return _explore(service, payload)
    if action == 'opponent_boundaries':
        return _opponent_boundaries(service, payload)
    if action == 'tactic_evidence':
        _object(payload, 'tactic evidence', ('action', 'evaluation_id', 'search_ids'))
        if not sandbox_enabled() or not search_enabled():
            raise AnalysisUnavailable('Tactical comparison disabled')
        return compare_tactics(service, payload['evaluation_id'], payload['search_ids'])
    if action == 'observed_evidence':
        _object(payload, 'observed evidence', ('action', 'evaluation_id', 'search_ids'))
        if not sandbox_enabled() or not observed_enabled():
            raise AnalysisUnavailable('Observed comparison disabled')
        return compare_observed(service, payload['evaluation_id'], payload['search_ids'])
    if action == 'ownership':
        _object(payload, 'ownership confirmation',
                ('action', 'instance_id', 'event_id', 'expected_revision', 'state'), ('observation', 'register'))
        state = payload['state']
        if state not in ('confirmed_owned', 'confirmed_absent'):
            raise ValueError('Explicit ownership confirmation is required')
        inventory = Ownership(service.store, species_ids=service.species)
        observation = payload.get('observation')
        if observation is not None and state != 'confirmed_owned':
            raise ValueError('Observation updates require confirmed_owned state')
        revision = payload['expected_revision']
        register = payload.get('register', observation is not None and revision == 0)
        if type(register) is not bool:
            raise ValueError('Invalid ownership registration choice')
        event = inventory.confirm(payload['event_id'], payload['instance_id'],
                                  expected_revision=revision, state=state,
                                  observation=observation, register_if_missing=register,
                                  preserve_identity=True)
        return {'instance_id': event['instance_id'], 'state': event['new_state'],
                'revision': event['output_revision']}
    if action == 'evaluation_history':
        _object(payload, 'role evaluation history', ('action',),
                ('limit', 'after_created_at', 'after_id'))
        return RoleEvaluation(service.store).list_history(
            limit=payload.get('limit', 24),
            after_created_at=payload.get('after_created_at'),
            after_id=payload.get('after_id'),
            active_versions=service.versions,
        )
    if action == 'ownership_list':
        return _ownership_list(service, payload)
    if action == 'ownership_history':
        return _ownership_history(service, payload)
    if action == 'ownership_scope':
        return _ownership_scope(service, payload)
    raise ValueError('Unknown missing comparison operation')
