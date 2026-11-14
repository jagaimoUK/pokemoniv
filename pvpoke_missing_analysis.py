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
from pvpoke_ownership import Ownership, _iv_index, build_id

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

    def evidence(self, analysis_id, *, active_versions, normalizer=None):
        """Return coverage and per-matchup facts from a single SQLite snapshot."""
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
                        seen_owner_keys = set()
                        for spec in specs.values():
                            combatant = spec['combatants'][0]
                            owner_key = (combatant['species_id'], _iv_index(combatant['ivs']))
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
            max_hp_by_build = {}
            for key, spec in specs.items():
                combatant = spec['combatants'][0]
                build = build_id(combatant)
                cell = {'battle_key': key, 'build_id': build, 'spec': spec,
                        'state': 'unknown', 'facts': None, 'ownership': 'unknown',
                        'inventory_matches': [], 'recommendation': 'unreviewed',
                        'gap_state': 'evidence_pending'}
                if normalizer is not None and versions == current:
                    if build not in max_hp_by_build:
                        full = {**combatant, 'initial': {**combatant['initial'], 'hp': 'full'}}
                        normalized, row = normalizer._combatant(full)
                        max_hp_by_build[build] = (normalized['initial']['hp'], row['cp'])
                    max_hp, cp = max_hp_by_build[build]
                    cell['starts_at_full_hp'] = combatant['initial']['hp'] == max_hp
                else:
                    cp = None
                if has_inventory and versions == current:
                    if build not in matches_by_build:
                        owner_key = (combatant['species_id'], _iv_index(combatant['ivs']))
                        matches_by_build[build] = Ownership._match_rows(
                            owner_rows_by_key.get(owner_key, ()), combatant, cp)
                    cell['inventory_matches'] = matches_by_build[build]
                    if any(match['state'] == 'confirmed_owned' and match['build_match'] == 'exact'
                           for match in cell['inventory_matches']):
                        cell['ownership'] = 'confirmed_owned'
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
        state = ('stale' if versions != current else 'complete' if completed == len(cells)
                 else 'partial' if completed else 'unknown')
        return {'analysis_id': analysis_id, 'versions': versions, 'state': state,
                'coverage': {'requested': len(cells), 'completed': completed},
                'ledger_revision': ledger_revision, 'cells': cells}
