"""TV-02 / TV-07 / TV-08 tests: isolated backup/restore compatibility and cross-app offline/conflict/resume safety."""
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from pvpoke_battle_service import BattleService
from pvpoke_battle_store import BattleStore
from pvpoke_direct_backend import DirectMatrixClient
from pvpoke_individual_sync import app_operation as sync_operation
from pvpoke_iv_search import IVSearch
from pvpoke_mega import max_level_and_cp
from pvpoke_missing_analysis import MissingAnalysis
from pvpoke_missing_comparison import app_operation as missing_operation
from pvpoke_ownership import Ownership, OwnershipConflict
from pvpoke_party_backend import PartyBuilder
from pvpoke_role_evaluation import RoleEvaluation
from pvpoke_selection_history import app_operation as selection_operation
import pvpoke_web as web
from test_battle_service import FIXTURES
from tools import cloud_migration_backup as backup


class MegaBackupAndRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.volume = self.root / 'volume'
        self.volume.mkdir()
        self.store = BattleStore(self.volume / 'battle_analysis.sqlite3')

    def _build_swablu_gamemaster(self, path: Path) -> tuple[str, list[str], dict]:
        gm = json.loads((FIXTURES / 'strategy_gamemaster.json').read_text(encoding='utf-8'))
        opp_row = json.loads((FIXTURES / 'strategy_rows.json').read_text(encoding='utf-8'))[0]
        shared_fast = opp_row['fast']
        shared_charged = [opp_row['charged1'], opp_row['charged2']]
        gm['pokemon'].extend([
            {
                'speciesId': 'swablu',
                'speciesName': 'Swablu',
                'dex': 333,
                'types': ['normal', 'flying'],
                'baseStats': {'atk': 76, 'def': 132, 'hp': 128},
                'fastMoves': [shared_fast],
                'chargedMoves': shared_charged,
                'family': {'id': 'FAMILY_SWABLU', 'evolutions': ['altaria']},
            },
            {
                'speciesId': 'altaria',
                'speciesName': 'Altaria',
                'dex': 334,
                'types': ['dragon', 'flying'],
                'baseStats': {'atk': 141, 'def': 201, 'hp': 181},
                'fastMoves': [shared_fast],
                'chargedMoves': shared_charged,
                'family': {'id': 'FAMILY_SWABLU', 'parent': 'swablu'},
            },
            {
                'speciesId': 'altaria_mega',
                'speciesName': 'Altaria (Mega)',
                'dex': 334,
                'types': ['dragon', 'fairy'],
                'baseStats': {'atk': 222, 'def': 218, 'hp': 181},
                'fastMoves': [shared_fast],
                'chargedMoves': shared_charged,
                'extraChargedMoves': ['MOONBLAST'],
                'tags': ['mega', 'supermega'],
            },
        ])
        path.write_text(json.dumps(gm), encoding='utf-8')
        return shared_fast, shared_charged, opp_row

    def test_tv02_isolated_backup_and_restore_preserves_mega_selection_missing_and_party_data(self):
        gm_path = self.root / 'gamemaster.json'
        shared_fast, shared_charged, opp_row = self._build_swablu_gamemaster(gm_path)
        client = DirectMatrixClient(gamemaster=gm_path, log_dir=self.root)
        self.addCleanup(client.close)
        service = BattleService(client, store=self.store)

        # 1. Populate owned_instances_v1 + ownership_events_v1 + individual sync patch.
        ivs = {'attack': 0, 'defense': 14, 'hp': 15}
        inv = Ownership(self.store, species_ids=service.species)
        inv.register('swablu-owned-1', {
            'species_id': 'swablu',
            'ivs': ivs,
            'current_level': 12.0,
            'current_cp': 260,
            'current_moves': {'fast': shared_fast, 'charged': shared_charged},
        })
        inv.confirm('tv02-own-1', 'swablu-owned-1', expected_revision=0, state='confirmed_owned')
        sync_operation(self.store, {
            'action': 'individual_patch',
            'instance_id': 'swablu-owned-1',
            'request_id': 'tv02-sync-1',
            'changes': {'nickname': {'revision': 0, 'value': 'AltMega0/14'}},
        })
        expected_owned = inv.get('swablu-owned-1')
        expected_events = inv.history('swablu-owned-1')
        expected_sync = sync_operation(self.store, {'action': 'individual_get', 'instance_id': 'swablu-owned-1'})

        # 2. Populate selection_snapshots_v1 + selection_instances_v1 with Mega & freshness metadata.
        calc_ver = 'a' * 64
        meta_ver = 'b' * 64
        rules_digest = 'c' * 64
        saved_sel = selection_operation(
            self.store,
            {
                'action': 'selection_save',
                'species_id': 'altaria_mega',
                'owned_species_id': 'swablu',
                'request_id': 'tv02-sel-1',
                'meta_sha256': meta_ver,
                'calculation_version': calc_ver,
                'policy_version': 'box-first-v3',
                'ranking_source_date': '2026-10-15',
                'rules_digest': rules_digest,
                'candidates': [{
                    'ivs': '0/14/15',
                    'role': 'important',
                    'moves': [shared_fast, *shared_charged],
                    'evidence': ['Reachable from swablu'],
                    'instance_id': 'swablu-owned-1',
                    'owned_species_id': 'swablu',
                    'goal': 'Evolve to Altaria Mega',
                }],
            },
            set(service.species),
        )
        expected_latest = selection_operation(
            self.store,
            {'action': 'selection_latest', 'species_id': 'altaria_mega'},
            set(service.species),
            current_context={
                'calculation_version': calc_ver,
                'meta_sha256': meta_ver,
                'policy_version': 'box-first-v3',
                'ranking_source_date': '2026-10-15',
                'rules_digest': rules_digest,
            },
            species_catalog=service.species,
        )

        # 3. Populate missing_analysis_plans_v1 + battle_results + role_evaluations_v1.
        mega_lvl, _ = max_level_and_cp(
            {'atk': 222, 'def': 218, 'hp': 181}, ivs, cp_cap=1500, max_level=50.0, cpms=service.cpms,
        )
        comp_payload = {
            'action': 'evaluate',
            'candidates': [{
                'species_id': 'altaria_mega',
                'owned_species_id': 'swablu',
                'ivs': ivs,
                'level': mega_lvl,
                'moves': {'fast': shared_fast, 'charged': shared_charged},
                'mega_level': 4,
                'charged3': 'MOONBLAST',
            }],
            'scenarios': [{
                'opponent': {
                    'species_id': opp_row['species'],
                    'ivs': {'attack': opp_row['atk'], 'defense': opp_row['def'], 'hp': opp_row['hp']},
                    'level': opp_row['level'],
                    'moves': {'fast': opp_row['fast'], 'charged': [opp_row['charged1'], opp_row['charged2']]},
                },
                'shields': [1, 1],
                'requirement': {'outcomes': ['self_win']},
            }],
            'role': {'role_id': 'tv02-mega-role', 'revision': 1, 'priority': 2},
        }
        before_eval = missing_operation(service, comp_payload)
        first_spec = before_eval['candidates'][0]['conditions'][0]['spec']
        sim_res = service.simulate(first_spec)
        self.assertEqual(sim_res['status'], 'complete')
        expected_eval = missing_operation(service, comp_payload)
        self.assertEqual(expected_eval['evidence_state'], 'complete')

        # 4. Populate team_builder.sqlite3 (parties / runs / cells / meta_weights) via PartyBuilder.
        work_dir = self.volume / 'party_work'
        party_builder = PartyBuilder(work_dir)
        party_builder.meta_weights({'altaria_mega': 2.5})
        saved_party = party_builder.save_party({
            'name': 'Mega GL Team',
            'members': [{
                'species': 'altaria_mega',
                'fast': shared_fast,
                'charged1': shared_charged[0],
                'charged2': shared_charged[1],
                'charged3': shared_charged[0],
                'mega_level': 4,
                'atk': 0,
                'def': 14,
                'hp': 15,
            }],
            'ruleset': 'cp1500-lv50',
            'mega_rules': {'cup_id': 'great_mega', 'max_megas_in_three': 1, 'max_megas_in_six': 6},
        })
        expected_party = party_builder.get_party(saved_party['id'])
        with sqlite3.connect(party_builder.path) as pdb:
            pdb.execute('PRAGMA journal_mode=WAL')
            pdb.execute("INSERT INTO runs VALUES('run-tv02', 'done', '{\"ok\":true}', 100)")
            pdb.execute("INSERT INTO cells VALUES('cell-tv02', 550, 100)")
            pdb.commit()

        # Auxiliary settings JSON in volume.
        settings_file = self.volume / 'mega_settings.json'
        settings_file.write_text(json.dumps({'super_max_cp_mode': 'none'}, sort_keys=True), encoding='utf-8')
        settings_hash = hashlib.sha256(settings_file.read_bytes()).hexdigest()

        before_battle_inv = backup.sqlite_inventory(self.store.path)
        before_party_inv = backup.sqlite_inventory(party_builder.path)
        for tbl in ('owned_instances_v1', 'selection_snapshots_v1', 'missing_analysis_plans_v1', 'battle_results', 'missing_role_evaluations_v1'):
            self.assertIn(tbl, before_battle_inv['tables'])
            self.assertGreaterEqual(before_battle_inv['tables'][tbl]['rows'], 1)
        for tbl in ('parties', 'runs', 'cells', 'meta_weights'):
            self.assertIn(tbl, before_party_inv['tables'])
            self.assertEqual(before_party_inv['tables'][tbl]['rows'], 1)

        # 5. Execute backup, verify, and isolated restore.
        bundle = self.root / 'bundle'
        restored_root = self.root / 'restored'
        res = backup.backup({'volume': self.volume}, bundle)
        self.assertTrue(res['verified'])
        manifest = backup.verify(bundle)
        self.assertFalse(any(f['path'].endswith('-wal') for f in manifest['files']))
        self.assertNotIn('swablu-owned-1', json.dumps(manifest))

        backup.restore(bundle, restored_root)
        restored_vol = restored_root / 'volume'
        restored_battle_db = restored_vol / 'battle_analysis.sqlite3'
        restored_party_db = restored_vol / party_builder.path.relative_to(self.volume)
        self.assertEqual(backup.sqlite_inventory(restored_battle_db), before_battle_inv)
        self.assertEqual(backup.sqlite_inventory(restored_party_db), before_party_inv)
        self.assertEqual(hashlib.sha256((restored_vol / 'mega_settings.json').read_bytes()).hexdigest(), settings_hash)

        # 6. Verify restored objects work cleanly across all modules and owner scopes.
        restored_store = BattleStore(restored_battle_db)
        restored_inv = Ownership(restored_store, species_ids=service.species)
        self.assertEqual(restored_inv.get('swablu-owned-1'), expected_owned)
        self.assertEqual(restored_inv.history('swablu-owned-1'), expected_events)
        self.assertEqual(
            sync_operation(restored_store, {'action': 'individual_get', 'instance_id': 'swablu-owned-1'}),
            expected_sync,
        )
        restored_latest = selection_operation(
            restored_store,
            {'action': 'selection_latest', 'species_id': 'altaria_mega'},
            set(service.species),
            current_context={
                'calculation_version': calc_ver,
                'meta_sha256': meta_ver,
                'policy_version': 'box-first-v3',
                'ranking_source_date': '2026-10-15',
                'rules_digest': rules_digest,
            },
            species_catalog=service.species,
        )
        self.assertEqual(restored_latest, expected_latest)
        self.assertEqual(restored_latest['snapshot']['revision'], saved_sel['revision'])

        restored_service = BattleService(client, store=restored_store)
        restored_eval = missing_operation(restored_service, comp_payload)
        self.assertEqual(restored_eval['evidence_state'], 'complete')
        self.assertEqual(restored_eval['evaluation_id'], expected_eval['evaluation_id'])
        self.assertEqual(RoleEvaluation(restored_store).history(expected_eval['evaluation_id'])['state'], expected_eval['state'])

        restored_party_builder = PartyBuilder(restored_vol / 'party_work')
        self.assertEqual(restored_party_builder.get_party(saved_party['id']), expected_party)
        self.assertEqual(restored_party_builder.meta_weights()['weights'], {'altaria_mega': 2.5})

        # Foreign owner isolation preserved after restore.
        foreign_store = BattleStore(restored_battle_db, owner_scope='foreign-owner')
        self.assertIsNone(Ownership(foreign_store, species_ids=service.species).get('swablu-owned-1'))
        self.assertIsNone(selection_operation(foreign_store, {'action': 'selection_latest', 'species_id': 'altaria_mega'})['snapshot'])

        # Tampered bundle is refused fail-closed before touching a destination.
        (bundle / 'files' / 'volume' / 'mega_settings.json').write_bytes(b'{"tampered":true}')
        with self.assertRaises(ValueError):
            backup.restore(bundle, self.root / 'refused-restore')
        self.assertFalse((self.root / 'refused-restore').exists())

    def test_tv07_tv08_cross_stage_conflicts_idempotency_and_iv_search_resume(self):
        gm_path = self.root / 'gamemaster_tv08.json'
        shared_fast, shared_charged, opp_row = self._build_swablu_gamemaster(gm_path)
        client = DirectMatrixClient(gamemaster=gm_path, log_dir=self.root)
        self.addCleanup(client.close)
        service = BattleService(client, store=self.store)

        # 1. Ownership & Selection Save idempotency + 409 conflict on different payload with same request_id.
        inv = Ownership(self.store, species_ids=service.species)
        ivs = {'attack': 0, 'defense': 14, 'hp': 15}
        inv.register('swablu-1', {'species_id': 'swablu', 'ivs': ivs, 'current_level': 12.0, 'current_cp': 260})
        first_confirm = inv.confirm('ev-1', 'swablu-1', expected_revision=0, state='confirmed_owned')
        self.assertEqual(inv.confirm('ev-1', 'swablu-1', expected_revision=0, state='confirmed_owned'), first_confirm)
        with self.assertRaises(OwnershipConflict):
            inv.confirm('ev-1', 'swablu-1', expected_revision=0, state='confirmed_absent')
        with self.assertRaises(OwnershipConflict):
            inv.confirm('ev-2', 'swablu-1', expected_revision=0, state='confirmed_absent')

        sel_payload = {
            'action': 'selection_save',
            'species_id': 'altaria_mega',
            'owned_species_id': 'swablu',
            'request_id': 'req-idem-1',
            'meta_sha256': 'a' * 64,
            'calculation_version': 'b' * 64,
            'policy_version': 'box-first-v3',
            'candidates': [{
                'ivs': '0/14/15', 'role': 'important', 'moves': [shared_fast, *shared_charged],
                'evidence': ['Win 1'], 'instance_id': 'swablu-1', 'goal': 'Power up',
            }],
        }
        r1 = selection_operation(self.store, sel_payload, set(service.species))
        self.assertEqual(selection_operation(self.store, sel_payload, set(service.species)), r1)
        with self.assertRaises(OwnershipConflict):
            selection_operation(
                self.store,
                {**sel_payload, 'candidates': [{**sel_payload['candidates'][0], 'goal': 'Different goal'}]},
                set(service.species),
            )

        # 2. Missing Analysis IVSearch interrupt & resume: budget=1 -> pause -> budget=1 resumes cleanly without duplicate engine calls.
        mega_lvl, _ = max_level_and_cp(
            {'atk': 222, 'def': 218, 'hp': 181}, ivs, cp_cap=1500, max_level=50.0, cpms=service.cpms,
        )
        spec = {
            'schema': 'battle-spec-v1',
            'mode': 'standard',
            'rules': {'league': 'great', 'cp_cap': 1500, 'cup_id': 'great_mega', 'allow_cp_downscaling': True},
            'combatants': [
                {'species_id': 'altaria_mega', 'ivs': ivs, 'level': mega_lvl,
                 'moves': {'fast': shared_fast, 'charged': shared_charged}, 'mega_level': 3,
                 'initial': {'hp': 'full', 'energy': 0, 'shields': 1, 'stages': [0, 0]}},
                {'species_id': opp_row['species'], 'ivs': {'attack': opp_row['atk'], 'defense': opp_row['def'], 'hp': opp_row['hp']},
                 'level': opp_row['level'], 'moves': {'fast': opp_row['fast'], 'charged': [opp_row['charged1'], opp_row['charged2']]},
                 'initial': {'hp': 'full', 'energy': 0, 'shields': 1, 'stages': [0, 0]}},
            ],
        }
        search = IVSearch(service)
        sid = search.start([spec], iv_floors=(14, 14, 14))
        step1 = search.step(sid, budget=1)
        self.assertEqual(step1['coverage']['all_completed_iv_count'], 1)
        calls_after_step1 = service.cache_stats['engine_calls']
        # Reopen store & search to simulate process restart/resume.
        reopened_service = BattleService(client, store=BattleStore(self.store.path))
        resumed_search = IVSearch(reopened_service)
        resumed_sid = resumed_search.start([spec], iv_floors=(14, 14, 14))
        self.assertEqual(resumed_sid, sid)
        step2 = resumed_search.step(resumed_sid, budget=1)
        self.assertEqual(step2['coverage']['all_completed_iv_count'], 2)
        self.assertEqual(step2['new_battles'], 1)
        self.assertEqual(reopened_service.cache_stats['engine_calls'], 1)
        self.assertEqual(calls_after_step1, 1)

        # 3. Party Builder HTTP save conflict (409) preserves existing Mega party without overwriting.
        party_builder = PartyBuilder(self.volume / 'party_http')
        created = party_builder.save_party({
            'name': 'Saved Mega',
            'members': [{'species': 'altaria_mega', 'fast': shared_fast, 'charged1': shared_charged[0], 'charged2': shared_charged[1], 'mega_level': 4}],
            'ruleset': 'cp1500-lv50',
            'mega_rules': {'cup_id': 'great_mega', 'max_megas_in_three': 1, 'max_megas_in_six': 6},
        })

        def post_party(path, payload):
            handler = Mock()
            handler.path = path
            handler._trusted_local_host.return_value = True
            raw = json.dumps(payload).encode()
            handler.rfile = io.BytesIO(raw)
            handler.headers = {'Content-Type': 'application/json', 'Content-Length': str(len(raw)), 'X-PvPoke-Token': web.TOKEN}
            web.Handler.do_POST(handler)
            return handler.respond.call_args.args

        with patch.object(web, 'PARTY', party_builder):
            status_ok, body_ok = post_party('/api/party/save', {
                'id': created['id'], 'revision': 1, 'name': 'Saved Mega v2',
                'members': [{'species': 'altaria_mega', 'fast': shared_fast, 'charged1': shared_charged[0], 'charged2': shared_charged[1], 'mega_level': 4}],
                'ruleset': 'cp1500-lv50',
                'mega_rules': {'cup_id': 'great_mega', 'max_megas_in_three': 1, 'max_megas_in_six': 6},
            })
            self.assertEqual(status_ok, 200)
            self.assertEqual(body_ok['revision'], 2)

            status_conflict, body_conflict = post_party('/api/party/save', {
                'id': created['id'], 'revision': 1, 'name': 'Stale Tab Overwrite',
                'members': [],
            })
            self.assertEqual(status_conflict, 409)
            self.assertIn('保存競合', body_conflict['error'])
            self.assertEqual(party_builder.get_party(created['id'])['name'], 'Saved Mega v2')
            self.assertEqual(party_builder.get_party(created['id'])['mega_rules']['cup_id'], 'great_mega')

    def test_party_ui_offline_conflict_and_stale_result_guard_js(self):
        from pvpoke_party_ui import HTML as PARTY_HTML

        m = re.search(r'<script>(.*?)</script>', PARTY_HTML, re.S)
        self.assertIsNotNone(m)
        script_path = self.root / 'party_ui.js'
        script_path.write_text(m.group(1), encoding='utf-8')
        subprocess.run(['node', '--check', str(script_path)], check=True, capture_output=True, text=True, timeout=10)

        test_js = f"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const script = fs.readFileSync({json.dumps(str(script_path))}, 'utf8');

const els = {{}};
const makeEl = (id='') => ({{
  id, value: '', checked: false, hidden: false, disabled: false, textContent: '',
  options: [], children: [], dataset: {{}}, className: '', style: {{}},
  append(...xs) {{ this.children.push(...xs); for (const x of xs) if (x && 'value' in x) this.options.push(x); }},
  replaceChildren(...xs) {{ this.children = []; this.options = []; this.append(...xs); }},
  addEventListener() {{}},
  setAttribute() {{}},
  removeAttribute() {{}},
  querySelector() {{ return {{ checked: false, value: '' }}; }},
  querySelectorAll() {{ return []; }},
  prepend(x) {{ this.children.unshift(x); }},
  before() {{}},
  after() {{}},
  remove() {{}},
  classList: {{ toggle() {{}}, add() {{}}, remove() {{}} }},
}});
const $ = id => (els[id] ??= makeEl(id));
class Option {{ constructor(text, value) {{ this.text = text; this.value = value ?? text; }} }}

let fetchHandler = async () => ({{ ok: false, status: 401, json: async () => ({{ error: 'auth' }}) }});
const ctx = {{
  document: {{ getElementById: $, createElement: tag => makeEl(tag), createTextNode: text => ({{ textContent: text }}), querySelectorAll: () => [] }},
  Option,
  URLSearchParams,
  location: {{ hash: '' }},
  setTimeout: (fn) => fn(),
  clearTimeout: () => {{}},
  fetch: (url, opts) => fetchHandler(url, opts),
}};
vm.createContext(ctx);
vm.runInContext(script, ctx);

(async () => {{
  // 1. Setup with catalog & Mega party load restores mega_rules, mega_level, charged3, revision.
  fetchHandler = async (url) => {{
    if (url.includes('catalog')) return {{ ok: true, json: async () => ({{
      ready: true,
      species: {{
        altaria_mega: {{ name_ja: 'メガチルタリス', fastMoves: ['DRAGON_BREATH'], chargedMoves: ['SKY_ATTACK', 'MOONBLAST'], tags: ['mega', 'supermega'], extraChargedMoves: ['MOONBLAST_PLUS'] }},
      }},
      moves: {{}},
    }}) }};
    if (url.includes('meta-preset-export')) return {{ ok: true, json: async () => ({{ id: 'm1', sha256: 'a'.repeat(64), csv: 'altaria_mega,DRAGON_BREATH,SKY_ATTACK,MOONBLAST', parts: [{{ csv: 'altaria_mega,DRAGON_BREATH,SKY_ATTACK,MOONBLAST' }}] }}) }};
    if (url.includes('meta-presets')) return {{ ok: true, json: async () => ({{ default_id: 'm1', items: [{{ id: 'm1', name: 'GL', rows: 1, sha256: 'a'.repeat(64) }}] }}) }};
    if (url.endsWith('/app-api/party/list')) return {{ ok: true, json: async () => ({{ items: [{{ id: 'p1', revision: 2, name: 'Mega Team' }}] }}) }};
    if (url.endsWith('/app-api/party/meta-weights')) return {{ ok: true, json: async () => ({{ weights: {{}} }}) }};
    if (url.endsWith('/app-api/party/get')) return {{ ok: true, json: async () => ({{
      id: 'p1', revision: 2, name: 'Mega Team',
      members: [{{ species: 'altaria_mega', fast: 'DRAGON_BREATH', charged1: 'SKY_ATTACK', charged2: 'MOONBLAST', mega_level: 4, charged3: 'MOONBLAST_PLUS' }}],
      locked_slots: [0], ruleset: 'cp1500-lv50', mega_rules: {{ cup_id: 'great_mega', max_megas_in_three: 1, max_megas_in_six: 6 }},
      opponents: [], candidate_pool: [], strategy: {{}}, opponent_hypotheses: [],
    }}) }};
    return {{ ok: true, json: async () => ({{}}) }};
  }};
  await ctx.setup();
  $('saved').value = 'p1';
  await $('load').onclick();
  assert.equal(vm.runInContext('partyId', ctx), 'p1');
  assert.equal(vm.runInContext('revision', ctx), 2);
  assert.equal($('partyRuleset').value, 'custom');
  assert.equal($('customCupId').value, 'great_mega');
  assert.equal($('maxMegasInThree').value, '1');

  // 2. Save conflict (409) keeps revision=2 intact and surfaces conflict message.
  fetchHandler = async (url) => {{
    if (url.endsWith('/app-api/party/save')) return {{ ok: false, status: 409, json: async () => ({{ error: '保存競合: 別のタブで編集されています' }}) }};
    return {{ ok: true, json: async () => ({{}}) }};
  }};
  await ctx.saveParty(false);
  assert.equal(vm.runInContext('revision', ctx), 2);
  assert.ok($('status').textContent.includes('保存競合'), 'status was: ' + $('status').textContent);

  // 3. Offline flow uses six selected species; this minimal DOM mock does not
  // implement querySelectorAll, so supply a valid roster only for API-state tests.
  // Real selection/serialization remains covered by Playwright browser E2E.
  vm.runInContext("getMon = () => Array.from({{length:6}}, () => ({{species:'altaria_mega'}}))", ctx);
  fetchHandler = async (url) => {{
    if (url.endsWith('/app-api/party/start')) return {{ ok: true, json: async () => ({{ job_id: 'j1' }}) }};
    if (url.endsWith('/app-api/party/status')) throw TypeError('Failed to fetch');
    return {{ ok: true, json: async () => ({{}}) }};
  }};
  await ctx.wrap('analyze');
  assert.equal(vm.runInContext('activeJob', ctx), null);
  assert.equal($('cancel').disabled, true);
  assert.equal($('analyze').disabled, false);
  assert.ok($('status').textContent.includes('Failed to fetch'));

  // 4. Mid-run input mutation rejects stale result rather than showing outdated recommendations.
  let mutated = false;
  fetchHandler = async (url) => {{
    if (url.endsWith('/app-api/party/start')) return {{ ok: true, json: async () => ({{ job_id: 'j2' }}) }};
    if (url.endsWith('/app-api/party/status')) {{
      if (!mutated) {{ mutated = true; $('maxMegasInThree').value = '2'; }}
      return {{ ok: true, json: async () => ({{ status: 'done', result: {{ kind: 'analyze', selection: {{ status: '計算済み', recommendations: [] }} }} }}) }};
    }}
    return {{ ok: true, json: async () => ({{}}) }};
  }};
  await ctx.wrap('analyze');
  assert.ok($('status').textContent.includes('計算中に入力が変更されました'));
  console.log('PARTY_UI_OFFLINE_CONFLICT_OK');
}})().catch(e => {{ console.error(e); process.exitCode = 1; }});
"""
        proc = subprocess.run(['node', '-e', test_js], capture_output=True, text=True, check=True, timeout=10)
        self.assertIn('PARTY_UI_OFFLINE_CONFLICT_OK', proc.stdout)


if __name__ == '__main__':
    unittest.main()
