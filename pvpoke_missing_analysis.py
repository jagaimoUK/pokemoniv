"""Internal plans and read-only evidence for missing-IV analysis.

Plans pin exact normalized matchups and versions. BattleStore remains the
source of facts. Ownership is checked against separate explicit inventory records.
"""
import json
import re
import sqlite3
import time

from pvpoke_battle_service import _canonical_json, _json_hash
from pvpoke_battle_store import BattleStore, BattleStoreError, COMPLETENESS
from pvpoke_ownership import Ownership, _iv_index, _unpack, build_id

MAX_MATCHUPS = 128
MAX_PLAN_BYTES = 512 * 1024
PLAN_SCHEMA = 'missing-analysis-plan-v1'
PLAN_TABLE = 'missing_analysis_plans_v1'


class AnalysisUnavailable(ValueError):
    """A plan could not be loaded or saved safely."""


def _versions(value):
    if type(value) is not dict or set(value) != {'engine', 'game_data'} or any(
        type(item) is not str or not re.fullmatch(r'[0-9a-f]{64}', item) for item in value.values()
    ):
        raise ValueError('Invalid analysis calculation versions')
    return dict(value)



def battle_facts(result):
    facts = {field: result[field] for field in ('outcome', 'rating', 'terminal', 'shields_used', 'damage', 'turns')}
    facts['charged_moves_resolved'] = [
        sum(event['actor'] == side and event['kind'] == 'charged' for event in result['executed_moves'])
        for side in (0, 1)
    ]
    return facts


def candidate_gl_mega_ranking(species_id, *, species_catalog=None, mega_scores=None, all_species_mode=False):
    """Resolve Normal GL / Mega GL 70-point OR verdict from pinned PvPoke ranking snapshot."""
    from pvpoke_mega import resolve_gl_mega_ranking_70_or

    return resolve_gl_mega_ranking_70_or(
        species_id,
        species_catalog=species_catalog,
        mega_scores=mega_scores,
        all_species_mode=all_species_mode,
    )


def candidate_training_goal(combatant, matches, *, owned_records=None):
    """Compute target PL, Candy, Candy XL, Stardust, and Super MAX note for a candidate and its matches."""
    from pvpoke_mega import build_training_goal, is_shadow_form

    target_level = combatant.get('level')
    mega_level = combatant.get('mega_level')
    species_id = combatant.get('species_id', '')
    if target_level is None:
        return None, list(matches or ())

    records_by_id = owned_records or {}
    enriched_matches = []
    best_match = None
    best_rank = 99
    for match in matches or ():
        rec = records_by_id.get(match.get('instance_id'))
        goal = build_training_goal(
            rec,
            target_level=float(target_level),
            needs_evolution=bool(match.get('needs_evolution')),
            downscaled=bool(match.get('mega_downscaled')),
            mega_level=mega_level,
            shadow=is_shadow_form((rec or {}).get('species_id') or species_id),
        )
        updated = {**match, 'training_goal': goal}
        enriched_matches.append(updated)
        rank = 0 if (updated.get('state') == 'confirmed_owned' and updated.get('build_match') == 'exact') else (
            1 if updated.get('state') == 'confirmed_owned' else 2
        )
        if rank < best_rank:
            best_rank = rank
            best_match = updated

    summary = (
        dict(best_match['training_goal'])
        if best_match is not None
        else build_training_goal(
            None,
            target_level=float(target_level),
            needs_evolution=False,
            downscaled=False,
            mega_level=mega_level,
            shadow=is_shadow_form(species_id),
        )
    )
    return summary, enriched_matches



class MissingAnalysis:
    """An internal reader bound to the server-owned BattleStore scope."""

    def __init__(self, store: BattleStore):
        self.store = store

    def save_plan(self, normalizer, requests):
        """Persist requested matchups without running a battle or mutating saved results."""
        if not isinstance(requests, (list, tuple)) or not 1 <= len(requests) <= MAX_MATCHUPS:
            raise ValueError('An analysis plan requires 1–128 matchups')
        versions = _versions(normalizer.versions)
        calculation_version = _json_hash([versions['engine'], versions['game_data']])
        specs = {}
        for request in requests:
            spec, _ = normalizer._prepare(request)
            if spec['calculation_version'] != calculation_version or spec['mode'] != 'standard':
                raise ValueError('Analysis requires standard matchups from one calculation version')
            specs[_json_hash(spec)] = spec
        plan = {'schema': PLAN_SCHEMA, 'versions': versions, 'specs': specs}
        data = _canonical_json(plan)
        if len(data) > MAX_PLAN_BYTES:
            raise ValueError('Analysis plan exceeds size limit')
        analysis_id = _json_hash(plan)
        try:
            with self.store._writer(critical=True) as db:
                # The table has its own version. Existing BattleStore readers
                # still accept this v1 database and ignore the new table.
                db.execute('''CREATE TABLE IF NOT EXISTS missing_analysis_plans_v1 (
                    owner_scope TEXT NOT NULL, analysis_id TEXT NOT NULL,
                    plan_json BLOB NOT NULL, created_at INTEGER NOT NULL,
                    PRIMARY KEY (owner_scope, analysis_id)
                ) WITHOUT ROWID''')
                old = db.execute('''SELECT plan_json FROM missing_analysis_plans_v1
                    WHERE owner_scope = ? AND analysis_id = ?''',
                    (self.store.owner_scope, analysis_id)).fetchone()
                if old is None:
                    db.execute('''INSERT INTO missing_analysis_plans_v1 VALUES (?, ?, ?, ?)''',
                               (self.store.owner_scope, analysis_id, data, int(time.time())))
                elif old[0] != data:
                    raise AnalysisUnavailable('Conflicting analysis plan')
        except (sqlite3.Error, OSError, BattleStoreError) as exc:
            raise AnalysisUnavailable('Could not store analysis plan') from exc
        return analysis_id

    def evidence(self, analysis_id, *, active_versions, normalizer=None, active_context=None):
        """Return coverage and per-matchup facts from a single SQLite snapshot."""
        from pvpoke_mega import (
            discover_reachable_forms,
            evaluate_selection_freshness,
            pre_evolutions_for_target,
        )

        if type(analysis_id) is not str or not re.fullmatch(r'[0-9a-f]{64}', analysis_id):
            raise ValueError('Invalid analysis ID')
        current = _versions(active_versions)
        if normalizer is not None and normalizer.versions != current:
            raise ValueError('Inventory build verification requires the active calculation version')
        try:
            if not self.store.path.exists():
                return None
            with self.store._reader() as db:
                if not db.execute('SELECT 1 FROM sqlite_schema WHERE type=? AND name=?',
                                  ('table', PLAN_TABLE)).fetchone():
                    return None
                row = db.execute('''SELECT plan_json FROM missing_analysis_plans_v1
                    WHERE owner_scope = ? AND analysis_id = ?''',
                    (self.store.owner_scope, analysis_id)).fetchone()
                if row is None:
                    return None
                payload = row[0]
                if type(payload) is not bytes or len(payload) > MAX_PLAN_BYTES:
                    raise ValueError('Invalid plan payload')
                plan = json.loads(payload)
                if type(plan) is not dict or plan.get('schema') != PLAN_SCHEMA:
                    raise ValueError('Invalid plan checksum or schema')
                specs = plan.get('specs')
                if type(specs) is not dict or not 1 <= len(specs) <= MAX_MATCHUPS:
                    raise ValueError('Invalid plan specs')
                versions = _versions(plan['versions'])
                inventory = Ownership(self.store)
                has_inventory = bool(inventory._exists(db))
                ledger_revision = inventory._revision(db) if has_inventory else 0
                owner_rows_by_key = {}
                saved_rows = {}
                if versions == current:
                    battle_keys = list(specs.keys())
                    if any(type(key) is not str for key in battle_keys):
                        raise ValueError('Invalid battle key in plan')
                    if has_inventory:
                        catalog = getattr(normalizer, 'species', None)
                        seen_owner_keys = set()
                        for spec in specs.values():
                            combatant = spec['combatants'][0]
                            iv_idx = _iv_index(combatant['ivs'])
                            keys_to_fetch = [(combatant['species_id'], iv_idx)]
                            for ancestor in pre_evolutions_for_target(combatant['species_id'], catalog):
                                if ancestor != combatant['species_id']:
                                    keys_to_fetch.append((ancestor, iv_idx))
                            for owner_key in keys_to_fetch:
                                if owner_key not in seen_owner_keys:
                                    seen_owner_keys.add(owner_key)
                                    owner_rows_by_key[owner_key] = db.execute(
                                        '''SELECT body, digest FROM owned_instances_v1
                                           WHERE owner_scope=? AND species_id=? AND iv_index=? ORDER BY instance_id''',
                                        (self.store.owner_scope, *owner_key),
                                    ).fetchall()
                    placeholders = ','.join('?' for _ in battle_keys)
                    saved_rows = {
                        battle_key: (result_json, result_sha256)
                        for battle_key, result_json, result_sha256 in db.execute(
                            f'''SELECT battle_key, result_json, result_sha256 FROM battle_results
                                WHERE owner_scope = ? AND completeness = ? AND battle_key IN ({placeholders})''',
                            (self.store.owner_scope, COMPLETENESS, *battle_keys),
                        )
                    }

            if _json_hash(plan) != analysis_id:
                raise ValueError('Invalid plan checksum or schema')
            cells = []
            completed = 0
            matches_by_build = {}
            goals_by_build = {}
            rankings_by_species = {}
            reachable_by_species = {}
            max_hp_by_build = {}
            catalog = getattr(normalizer, 'species', None)
            advisories = []
            seen_advisories = set()
            for key, spec in specs.items():
                combatant = spec['combatants'][0]
                build = build_id(combatant)
                sid = combatant['species_id']
                if sid not in rankings_by_species:
                    rankings_by_species[sid] = candidate_gl_mega_ranking(sid, species_catalog=catalog)
                if sid not in reachable_by_species:
                    reachable_by_species[sid] = discover_reachable_forms(sid, catalog)
                rank_info = rankings_by_species[sid]
                if rank_info.get('mega_gl_status') == 'unverified' and 'mega_ranking_unverified' not in seen_advisories:
                    seen_advisories.add('mega_ranking_unverified')
                    advisories.append('mega_ranking_unverified')
                cell = {'battle_key': key, 'build_id': build, 'spec': spec,
                        'state': 'unknown', 'facts': None, 'ownership': 'unknown',
                        'inventory_matches': [], 'recommendation': 'unreviewed',
                        'gap_state': 'evidence_pending',
                        'gl_mega_ranking': rank_info,
                        'reachable_forms': reachable_by_species[sid],
                        'training_goal': None}
                if normalizer is not None and versions == current:
                    if build not in max_hp_by_build:
                        full = {**combatant, 'initial': {**combatant['initial'], 'hp': 'full'}}
                        normalized, row = normalizer._combatant(full)
                        max_hp_by_build[build] = (normalized['initial']['hp'], row['cp'])
                    max_hp, cp = max_hp_by_build[build]
                    cell['starts_at_full_hp'] = combatant['initial']['hp'] == max_hp
                else:
                    cp = None
                goal_cache_key = (build, _json_hash(spec.get('rules')), combatant.get('mega_level'))
                if has_inventory and versions == current:
                    if goal_cache_key not in matches_by_build:
                        iv_idx = _iv_index(combatant['ivs'])
                        rows_for_match = list(owner_rows_by_key.get((sid, iv_idx), ()))
                        for ancestor in pre_evolutions_for_target(sid, catalog):
                            if ancestor != sid:
                                rows_for_match.extend(owner_rows_by_key.get((ancestor, iv_idx), ()))
                        raw_matches = Ownership._match_rows(
                            rows_for_match,
                            combatant,
                            cp,
                            species_catalog=catalog,
                            cpms=getattr(normalizer, 'cpms', None),
                            rules=spec.get('rules'),
                        )
                        owned_records = {
                            rec['instance_id']: rec
                            for rec in (_unpack(r) for r in rows_for_match)
                        }
                        summary_goal, enriched_matches = candidate_training_goal(
                            combatant, raw_matches, owned_records=owned_records,
                        )
                        matches_by_build[goal_cache_key] = enriched_matches
                        goals_by_build[goal_cache_key] = summary_goal
                    cell['inventory_matches'] = matches_by_build[goal_cache_key]
                    cell['training_goal'] = goals_by_build[goal_cache_key]
                    if any(match['state'] == 'confirmed_owned' and match['build_match'] == 'exact'
                           for match in cell['inventory_matches']):
                        cell['ownership'] = 'confirmed_owned'
                else:
                    if goal_cache_key not in goals_by_build:
                        goals_by_build[goal_cache_key], _ = candidate_training_goal(combatant, ())
                    cell['training_goal'] = goals_by_build[goal_cache_key]
                if versions != current:
                    cell['state'] = 'stale'
                else:
                    saved = saved_rows.get(key)
                    if saved is not None:
                        try:
                            result = self.store._decode(saved, key, spec, versions)
                        except BattleStoreError:
                            cell['evidence_error'] = 'invalid_saved_result'
                        else:
                            cell['state'] = 'complete'
                            cell['completeness'] = COMPLETENESS
                            cell['facts'] = battle_facts(result)
                            completed += 1
                            if cell['ownership'] == 'unknown':
                                cell['gap_state'] = 'ownership_confirmation_needed'
                cells.append(cell)
        except (sqlite3.Error, OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
            raise AnalysisUnavailable('Could not read analysis evidence') from exc

        rec_calc = plan.get('calculation_version') or _json_hash([versions['engine'], versions['game_data']])
        cur_calc = _json_hash([current['engine'], current['game_data']])
        recorded_ctx = {'versions': versions, 'calculation_version': rec_calc}
        current_ctx = {'versions': current, 'calculation_version': cur_calc}
        if isinstance(active_context, dict):
            for k in ('ranking_source_date', 'ranking_sha256', 'rules_digest', 'policy_version', 'meta_sha256'):
                if k in plan:
                    recorded_ctx[k] = plan[k]
                if k in active_context:
                    current_ctx[k] = active_context[k]
            if 'rules' in active_context:
                first_spec = next(iter(specs.values()))
                recorded_ctx['rules'] = first_spec.get('rules')
                current_ctx['rules'] = active_context['rules']
            if active_context.get('impact_provable') is False:
                current_ctx['impact_provable'] = False
        freshness = evaluate_selection_freshness(recorded_ctx, current_ctx)
        freshness['advisories'] = advisories
        stale = (versions != current) or freshness['needs_reevaluation']
        if stale:
            for cell in cells:
                cell['state'] = 'stale'
                cell['facts'] = None
                cell['gap_state'] = 'evidence_pending'
            completed = 0
        state = ('stale' if stale else 'complete' if completed == len(cells)
                 else 'partial' if completed else 'unknown')
        return {'analysis_id': analysis_id, 'versions': versions, 'state': state,
                'freshness': freshness,
                'coverage': {'requested': len(cells), 'completed': completed},
                'ledger_revision': ledger_revision, 'cells': cells}

