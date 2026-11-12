"""Explicit authenticated app operations for scoped missing Pokémon comparison."""
import os

from pvpoke_battle_service import _integer, _json_hash, _object
from pvpoke_iv_search import IVSearch
from pvpoke_missing_analysis import AnalysisUnavailable, MissingAnalysis
from pvpoke_ownership import Ownership, OwnershipConflict, build_id
from pvpoke_role_evaluation import RoleEvaluation, _definition, _hash, condition_id
from pvpoke_sandbox_workspace import enabled as sandbox_enabled, search_enabled
from pvpoke_tactic_evidence import compare_tactics

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
    _object(payload, 'IV exploration request', ('action', 'evaluation_id', 'build_id', 'budget'))
    selected = _hash(payload['build_id'])
    budget = _integer(payload['budget'], 'IV exploration budget', 0, 1)
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
    explorer = IVSearch(service)
    search_id = explorer.start([slots[slot] for slot in role['requirements']])
    step = explorer.step(search_id, budget=budget, role=role)
    if step is None or step['coverage'] is None:
        raise AnalysisUnavailable('IV coverage unavailable')
    coverage = step['coverage']
    bits = int.from_bytes(bytes.fromhex(coverage['qualifying_ivs']), 'little')
    count = bits.bit_count()
    examples = []
    while bits and len(examples) < 32:
        lsb = bits & -bits
        index = lsb.bit_length() - 1
        examples.append({'attack': index >> 8, 'defense': (index >> 4) & 15, 'hp': index & 15})
        bits ^= lsb
    return {'state': step['state'], 'new_battles': step['new_battles'],
            'eligible_iv_count': coverage['eligible_iv_count'], 'qualifying_count': count,
            'completed_iv_count': coverage['all_completed_iv_count'],
            # Every IV lacking at least one required matchup is still not fully
            # tested. This can include known failures; it is *not* a count of
            # possible wins and must never be merged into qualifying_count.
            'not_fully_tested_iv_count': (
                coverage['eligible_iv_count'] - coverage['all_completed_iv_count']),
            'qualifying': examples, 'can_calculate': _can_calculate()}


def app_operation(service, payload):
    action = payload.get('action')
    if action == 'evaluate':
        return _comparison(service, payload)
    if action == 'explore':
        return _explore(service, payload)
    if action == 'tactic_evidence':
        _object(payload, 'tactic evidence', ('action', 'evaluation_id', 'search_ids'))
        if not sandbox_enabled() or not search_enabled():
            raise AnalysisUnavailable('Tactical comparison disabled')
        return compare_tactics(service, payload['evaluation_id'], payload['search_ids'])
    if action == 'ownership':
        _object(payload, 'ownership confirmation',
                ('action', 'instance_id', 'event_id', 'expected_revision', 'state'), ('observation', 'register'))
        state = payload['state']
        if state not in ('confirmed_owned', 'confirmed_absent'):
            raise ValueError('Explicit ownership confirmation is required')
        inventory = Ownership(service.store, species_ids=service.species)
        observation = payload.get('observation')
        revision = payload['expected_revision']
        register = payload.get('register', observation is not None and revision == 0)
        if type(register) is not bool:
            raise ValueError('Invalid ownership registration choice')
        if observation is not None and not register:
            observed = inventory._observation(observation)
            previous = inventory.get(payload['instance_id'])
            if previous is None or any(previous[key] != observed[key] for key in ('species_id', 'ivs')):
                raise OwnershipConflict('Observation conflicts with the individual identity')
        event = inventory.confirm(payload['event_id'], payload['instance_id'],
                                  expected_revision=revision, state=state,
                                  observation=observation, register_if_missing=register)
        return {'instance_id': event['instance_id'], 'state': event['new_state'],
                'revision': event['output_revision']}
    raise ValueError('Unknown missing comparison operation')
