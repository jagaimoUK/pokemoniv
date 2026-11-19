import http.client
import json
import os
from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch

import test_battle_api as server
from pvpoke_battle_store import BattleStore
from pvpoke_missing_comparison import API_PATH, APP_PATH, PAGE_PATH
from pvpoke_ownership import Ownership
from test_battle_service import FIXTURES, battle_spec


def case(*, energy=0, threshold=0):
    builds = []
    for left in (0, 1):
        build, opponent = battle_spec(left=left)['combatants']
        builds.append({key: value for key, value in build.items() if key != 'initial'})
    return {
        'action': 'evaluate', 'candidates': builds,
        'scenarios': [{'opponent': {key: value for key, value in opponent.items() if key != 'initial'},
                       'shields': [1, 1], 'energy': energy, 'requirement': {'minimum': {'fast_damage': threshold}}}],
        'role': {'role_id': 'lead', 'revision': 1, 'priority': 5},
    }


def request(host, path, payload=None, *, headers=None):
    conn = http.client.HTTPConnection(*host.server_address, timeout=15)
    conn.request('POST' if payload is not None else 'GET', path,
                 json.dumps(payload).encode() if type(payload) is dict else payload, headers or {})
    res = conn.getresponse()
    result = (res.status, res.read(), dict(res.getheaders()))
    conn.close()
    return result


class MissingGatewayTests(server.ServerFixture):
    handler = server.gateway.Handler

    def setUp(self):
        self.enterContext(patch.object(server.gateway, 'RATE_BUDGET', server.RateBudget()))
        super().setUp()

    def test_public_pages_cannot_embed_private_keys_and_api_needs_auth(self):
        """No private credentials or owner data in public app shell/unauth requests."""
        with patch.dict(os.environ, {
                'PVP_MISSING_ANALYSIS_ENABLED': '1',
                'PVP_SANDBOX_ENABLED': '1'}), patch.object(
                server.gateway.backend, '_request') as backend:
            for path in ('/app', PAGE_PATH, '/app/sandbox', '/app/party', '/app/migration'):
                status, body, _ = request(self.server, path)
                self.assertEqual(status, 200, path)
                self.assertNotIn(server.gateway.API_KEY.encode(), body, path)
                self.assertNotIn(server.web.TOKEN.encode(), body, path)
            for path in (APP_PATH, '/app-api/sandbox'):
                self.assertEqual(request(self.server, path, {'action': 'list'},
                                         headers={'Content-Type': 'application/json'})[0],
                                 401)
            backend.assert_not_called()

    def test_flag_origin_auth_and_fixed_route(self):
        auth = {'Authorization': 'Bearer ' + server.gateway.API_KEY, 'Content-Type': 'application/json'}
        with patch.dict(os.environ, {'PVP_MISSING_ANALYSIS_ENABLED': '0'}):
            self.assertEqual(request(self.server, PAGE_PATH)[0], 404)
            self.assertEqual(request(self.server, APP_PATH, case(), headers=auth)[0], 503)
        with patch.dict(os.environ, {
                'PVP_MISSING_ANALYSIS_ENABLED': '1',
                'PVP_SANDBOX_ENABLED': '1',
                'PVP_TACTIC_SEARCH_ENABLED': '1',
                'PVP_OBSERVED_SEARCH_ENABLED': '1'}), patch.object(
                server.gateway.backend, '_token', return_value='local-test-token'), patch.object(
                server.gateway.backend, '_request', return_value={'state': 'evidence_pending'}) as call:
            code, html, headers = request(self.server, PAGE_PATH)
            self.assertEqual(code, 200)
            self.assertIn('不足'.encode(), html)
            self.assertIn(b'data-sandbox="1"', html)
            self.assertIn(b'data-tactic-search="1"', html)
            self.assertIn(b'data-observed-search="1"', html)
            self.assertIn('Content-Security-Policy', headers)
            self.assertEqual(request(self.server, APP_PATH, case())[0], 401)
            self.assertEqual(request(self.server, APP_PATH, case(), headers={**auth, 'Origin': 'https://other.invalid'})[0], 403)
            self.assertEqual(request(self.server, APP_PATH, case(), headers={**auth, 'Content-Type': 'text/plain'})[0], 415)
            self.assertEqual(request(self.server, APP_PATH, b'{"action":1,"action":2}', headers=auth)[0], 400)
            self.assertEqual(request(self.server, APP_PATH, b' ' * 65537, headers=auth)[0], 413)
            self.assertEqual(request(self.server, APP_PATH, case(), headers=auth)[0], 200)
            call.assert_called_once_with(API_PATH, case(), headers={'X-PvPoke-Token': 'local-test-token'}, timeout=65)


class MissingLocalTests(server.ServerFixture):
    handler = server.web.Handler

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        shutil.copyfile(FIXTURES / 'strategy_gamemaster.json', self.root / 'gamemaster.json')
        self.enterContext(patch.dict(os.environ, {'PVP_MISSING_ANALYSIS_ENABLED': '1', 'PVP_BATTLE_API_ENABLED': '1',
                                                 'PVP_ARCHIVE_DIR': str(self.root / 'volume')}))
        self.enterContext(patch.object(server.web.engine, 'DATA', self.root))
        self.enterContext(patch.object(server.web, 'WORK', self.root / 'work'))
        self.enterContext(patch.dict(server.web.CATALOG, {'ready': True}))
        self.enterContext(patch.dict(server.web.STATUS, {'state': 'idle'}))
        super().setUp()

    def compare(self, payload):
        headers = {'Content-Type': 'application/json', 'X-PvPoke-Token': server.web.TOKEN}
        status, body, _ = request(self.server, API_PATH, payload, headers=headers)
        return status, json.loads(body)

    def test_evidence_same_role_substitutes_and_explicit_ownership(self):
        payload = case()
        with patch.object(server.web.BattleService, 'simulate') as engine:
            code, initial = self.compare(payload)
            self.assertEqual(code, 200)
            self.assertEqual(initial['state'], 'evidence_pending')
            self.assertEqual([item['status'] for item in initial['candidates']], ['pending', 'pending'])
            engine.assert_not_called()
        for candidate in initial['candidates']:
            battle = candidate['conditions'][0]['spec']
            code, response = server.post(self.server, '/api/battles/simulate', battle)
            self.assertEqual((code, response['status']), (200, 'complete'))
        _, saved = self.compare(payload)
        self.assertEqual(saved['state'], 'ownership_confirmation_needed')
        self.assertEqual([(item['status'], item['comparison'], item['party_substitution'])
                          for item in saved['candidates']], [('sufficient', 'same_species', 'pending'),
                                                            ('sufficient', 'cross_species', 'pending')])
        candidate = saved['candidates'][0]
        observation = {'species_id': candidate['species_id'], 'ivs': candidate['ivs'], 'current_cp': 1476,
                       'current_level': candidate['level'], 'current_moves': candidate['moves']}
        event = {'action': 'ownership', 'instance_id': 'fixture', 'event_id': 'fixture-event',
                 'expected_revision': 0, 'state': 'confirmed_owned', 'observation': observation}
        with patch.object(server.web.BattleService, 'simulate') as engine:
            code, record = self.compare(event)
            self.assertEqual((code, record['state']), (200, 'confirmed_owned'))
            self.assertEqual(self.compare(event), (200, record))
            self.assertEqual(self.compare({**event, 'event_id': 'duplicate'})[0], 409)
            self.assertEqual(self.compare({**event, 'owner_scope': 'other'})[0], 400)
            update = {**event, 'event_id': 'refresh', 'expected_revision': 1}
            self.assertEqual(self.compare({**update, 'observation': {**observation, 'ivs': {
                'attack': 1, 'defense': 15, 'hp': 15}}})[0], 409)
            code, changed = self.compare(update)
            self.assertEqual((code, changed['revision']), (200, 2))
            self.assertEqual(self.compare({**update, 'event_id': 'stale'})[0], 409)
            _, reevaluated = self.compare(payload)
            self.assertEqual(reevaluated['state'], 'covered')
            self.assertEqual(self.compare(case(threshold=10000))[1]['state'], 'gap')
            _, explored = self.compare({'action': 'explore', 'evaluation_id': reevaluated['evaluation_id'],
                                        'build_id': candidate['build_id'], 'budget': 0})
            self.assertEqual(explored['eligible_iv_count'], 4096)
            self.assertEqual(explored['new_battles'], 0)
            engine.assert_not_called()
        foreign = BattleStore(self.root / 'volume' / 'battle_analysis.sqlite3', owner_scope='foreign')
        self.assertIsNone(Ownership(foreign).get('fixture'))

    def test_unplayed_iv_space_is_explicitly_unverified_not_a_proven_zero(self):
        """At 0/4096, zero confirmed successes must not mean no eligible IV wins."""
        from pvpoke_missing_ui import HTML

        status, compared = self.compare(case())
        self.assertEqual(status, 200)
        self.assertEqual(compared['state'], 'evidence_pending')
        status, explored = self.compare({
            'action': 'explore',
            'evaluation_id': compared['evaluation_id'],
            'build_id': compared['reference']['build_id'],
            'budget': 0,
        })
        self.assertEqual(status, 200)
        self.assertEqual(explored['state'], 'unknown')
        self.assertEqual(explored['eligible_iv_count'], 4096)
        self.assertEqual(explored['completed_iv_count'], 0)
        self.assertEqual(explored['qualifying_count'], 0)
        # A zero is only the number of *proven* matches, never a proof of
        # absence. The API must explicitly carry the unverified remainder.
        self.assertEqual(explored['not_fully_tested_iv_count'], 4096)
        self.assertIn('全条件の検証が未完了', HTML)
        self.assertIn('達成確認済み', HTML)
        # After exactly one native battle, one IV may be fully assessed.
        status, progressed = self.compare({
            'action': 'explore',
            'evaluation_id': compared['evaluation_id'],
            'build_id': compared['reference']['build_id'],
            'budget': 1,
        })
        self.assertEqual(status, 200)
        self.assertEqual(progressed['completed_iv_count'], 1)
        self.assertEqual(progressed['not_fully_tested_iv_count'], 4095)
        self.assertEqual(progressed['new_battles'], 1)
        # Opt-in batches keep the server-side native limit (32), and resume
        # from the same saved plan without reclassifying any unknown IV as lost.
        batch_request = {
            'action': 'explore',
            'evaluation_id': compared['evaluation_id'],
            'build_id': compared['reference']['build_id'], 'budget': 8,
        }
        status, batch = self.compare(batch_request)
        self.assertEqual(status, 200)
        self.assertEqual(batch['new_battles'], 8)
        self.assertEqual(batch['completed_iv_count'], 9)
        self.assertEqual(batch['not_fully_tested_iv_count'], 4087)
        self.assertEqual(self.compare({**batch_request, 'budget': 33})[0], 400)

    def test_exploration_distinguishes_failed_attempt_from_saved_nonqualification(self):
        status, compared = self.compare(case(threshold=10000))
        self.assertEqual(status, 200)
        request = {'action': 'explore', 'evaluation_id': compared['evaluation_id'],
                   'build_id': compared['reference']['build_id'], 'budget': 1}
        _, before = self.compare(request)
        self.assertEqual(before['completed_iv_count'], 1)
        with patch.object(server.web.BattleService, 'simulate', return_value={
                'status': 'failed', 'error': {'message': 'private fixture detail'}}):
            status, interrupted = self.compare(request)
        self.assertEqual(status, 200)
        self.assertTrue(interrupted['retry_needed'])
        self.assertEqual(interrupted['completed_iv_count'], 1)
        self.assertEqual(interrupted['fully_tested_nonqualifying_iv_count'], 1)
        self.assertEqual(interrupted['not_fully_tested_iv_count'], 4095)
        self.assertNotIn('private fixture detail', json.dumps(interrupted))

        _, resumed = self.compare(request)
        self.assertFalse(resumed['retry_needed'])
        self.assertEqual(resumed['completed_iv_count'], 2)
        self.assertEqual(resumed['fully_tested_nonqualifying_iv_count'], 2)
        self.assertEqual(resumed['new_battles'], 1)

    def test_cross_species_partial_evidence_cannot_be_combined_into_one_role(self):
        """Two builds each clearing a different matchup are not substitutable."""
        payload = case()
        alternate = battle_spec(left=0, right=3)['combatants'][1]
        payload['scenarios'].append({
            'opponent': {k: v for k, v in alternate.items() if k != 'initial'},
            'shields': [1, 1],
            'energy': 0,
            'requirement': {'minimum': {'fast_damage': 0}},
        })
        status, planned = self.compare(payload)
        self.assertEqual(status, 200)
        self.assertEqual(len(planned['candidates']), 2)
        for index, candidate in enumerate(planned['candidates']):
            spec = candidate['conditions'][index]['spec']
            status, battle = server.post(self.server, '/api/battles/simulate', spec)
            self.assertEqual(status, 200)
            self.assertEqual(battle['status'], 'complete')
        status, report = self.compare(payload)
        self.assertEqual(status, 200)
        self.assertEqual(report['state'], 'evidence_pending')
        self.assertEqual([candidate['status'] for candidate in report['candidates']],
                         ['pending', 'pending'])
        self.assertEqual(report['candidates'][1]['comparison'], 'cross_species')
        self.assertTrue(all(candidate['party_substitution'] == 'pending'
                            for candidate in report['candidates']))

    def test_opponent_boundary_preview_is_read_only_scope_bound_and_static(self):
        status, comparison = self.compare(case())
        self.assertEqual(status, 200)
        reference = comparison['reference']['build_id']
        first = comparison['candidates'][0]['conditions'][0]['battle_key']
        request = {'action': 'opponent_boundaries',
                   'evaluation_id': comparison['evaluation_id'],
                   'build_id': reference, 'battle_key': first,
                   'iv_floors': [15, 15, 15]}
        with patch.object(server.web.BattleService, 'simulate',
                          side_effect=AssertionError('Must not run PvPoke battle')):
            status, report = self.compare(request)
        self.assertEqual(status, 200)
        self.assertEqual(report['eligible_iv_count'], 1)
        self.assertEqual(report['native_battles_run'], 0)
        self.assertFalse(report['battle_outcomes_verified'])
        self.assertEqual(self.compare({**request, 'battle_key': '0' * 64})[0], 400)
        self.assertEqual(self.compare({**request, 'owner_scope': 'other'})[0], 400)
        self.assertEqual(self.compare({**request, 'iv_floors': [True, 15, 15]})[0], 400)

    def test_nonneutral_setup_produces_conditional_role_alternative(self):
        payload = case(energy=20)
        code, initial = self.compare(payload)
        self.assertEqual(code, 200)
        battle = initial['candidates'][1]['conditions'][0]['spec']
        self.assertEqual(server.post(self.server, '/api/battles/simulate', battle)[0], 200)
        code, report = self.compare(payload)
        self.assertEqual(code, 200)
        self.assertEqual([item['status'] for item in report['candidates']], ['pending', 'conditional'])
        self.assertFalse(server.web.BATTLE_RUNNING)

    def test_ownership_list_history_scope_and_reconfirm_via_missing_api(self):
        payload = case()
        candidate = payload['candidates'][0]
        observation = {
            'species_id': candidate['species_id'], 'ivs': candidate['ivs'],
            'current_cp': 1476, 'current_level': candidate['level'],
            'current_moves': candidate['moves'],
        }
        with patch.object(server.web.BattleService, 'simulate',
                          side_effect=AssertionError('Ownership operations must not invoke PvPoke')):
            code, empty = self.compare({'action': 'ownership_list'})
            self.assertEqual(code, 200)
            self.assertEqual(empty['ledger_revision'], 0)
            self.assertEqual(empty['items'], [])
            self.assertEqual(empty['scopes'], [])
            self.assertEqual(self.compare({'action': 'ownership_list', 'owner_scope': 'other'})[0], 400)
            self.assertEqual(self.compare({'action': 'ownership_history', 'instance_id': 'missing'})[0], 400)

            # Register + confirm owned, then absent, then reconfirm with updated CP/Lv.
            ev_create = {
                'action': 'ownership', 'instance_id': 'step1-inst', 'event_id': 'step1-ev-1',
                'expected_revision': 0, 'state': 'confirmed_owned', 'observation': observation,
            }
            self.assertEqual(self.compare(ev_create)[0], 200)
            # Observation updates must be rejected when marking confirmed_absent.
            self.assertEqual(self.compare({
                'action': 'ownership', 'instance_id': 'step1-inst', 'event_id': 'step1-ev-bad',
                'expected_revision': 1, 'state': 'confirmed_absent', 'observation': observation,
            })[0], 400)
            ev_absent = {
                'action': 'ownership', 'instance_id': 'step1-inst', 'event_id': 'step1-ev-2',
                'expected_revision': 1, 'state': 'confirmed_absent',
            }
            self.assertEqual(self.compare(ev_absent), (200, {'instance_id': 'step1-inst', 'state': 'confirmed_absent', 'revision': 2}))
            updated_obs = {**observation, 'current_cp': 1492, 'current_level': 21.0}
            ev_reown = {
                'action': 'ownership', 'instance_id': 'step1-inst', 'event_id': 'step1-ev-3',
                'expected_revision': 2, 'state': 'confirmed_owned', 'register': False,
                'observation': updated_obs,
            }
            self.assertEqual(self.compare(ev_reown), (200, {'instance_id': 'step1-inst', 'state': 'confirmed_owned', 'revision': 3}))
            # Replay is idempotent; changing species/IVs on update conflicts (409).
            self.assertEqual(self.compare(ev_reown), (200, {'instance_id': 'step1-inst', 'state': 'confirmed_owned', 'revision': 3}))
            self.assertEqual(self.compare({
                'action': 'ownership', 'instance_id': 'step1-inst', 'event_id': 'step1-ev-4',
                'expected_revision': 3, 'state': 'confirmed_owned', 'register': False,
                'observation': {**updated_obs, 'ivs': {'attack': 15, 'defense': 15, 'hp': 15}},
            })[0], 409)

            code, listed = self.compare({'action': 'ownership_list', 'species_id': candidate['species_id'], 'state': 'confirmed_owned'})
            self.assertEqual(code, 200)
            self.assertEqual(len(listed['items']), 1)
            self.assertEqual(listed['items'][0]['current_cp'], 1492)
            self.assertEqual(listed['items'][0]['revision'], 3)
            ledger_rev = listed['ledger_revision']

            code, hist = self.compare({'action': 'ownership_history', 'instance_id': 'step1-inst', 'limit': 10})
            self.assertEqual(code, 200)
            self.assertEqual([e['new_state'] for e in hist['events']], ['confirmed_owned', 'confirmed_absent', 'confirmed_owned'])
            self.assertEqual(hist['instance']['current_cp'], 1492)
            self.assertFalse(hist['has_more'])

            # Explicit box scope confirmation requires matching ledger revision and complete=True for absence.
            scope_req = {
                'action': 'ownership_scope', 'event_id': 'step1-scope-1',
                'expected_ledger_revision': ledger_rev, 'species_id': candidate['species_id'],
                'search': '0attack', 'box_range': [1, 100], 'complete': True, 'absence_confirmed': True,
            }
            self.assertEqual(self.compare({**scope_req, 'event_id': 'bad-scope', 'complete': False})[0], 400)
            self.assertEqual(self.compare({**scope_req, 'event_id': 'stale-scope', 'expected_ledger_revision': ledger_rev + 1})[0], 409)
            code, scope_res = self.compare(scope_req)
            self.assertEqual(code, 200)
            self.assertTrue(scope_res['current'])
            self.assertTrue(scope_res['absence_confirmed'])
            self.assertEqual(self.compare(scope_req), (200, scope_res))

            # Scope confirmation must never alter individual instance ownership state.
            code, after_scope = self.compare({'action': 'ownership_list'})
            self.assertEqual(code, 200)
            self.assertEqual(after_scope['items'][0]['state'], 'confirmed_owned')
            self.assertEqual(len(after_scope['scopes']), 1)
            self.assertTrue(after_scope['scopes'][0]['current'])

            # Step 1 P1 regression: CP-only update (omitting current_level and current_moves) must keep saved Lv/moves.
            ev_p1_create = {
                'action': 'ownership', 'instance_id': 'step1-p1-inst', 'event_id': 'step1-p1-1',
                'expected_revision': 0, 'state': 'confirmed_owned',
                'observation': {
                    'species_id': candidate['species_id'], 'ivs': candidate['ivs'],
                    'current_cp': 1476, 'current_level': 20.5,
                    'current_moves': candidate['moves'],
                },
            }
            self.assertEqual(self.compare(ev_p1_create)[0], 200)
            ev_p1_cp = {
                'action': 'ownership', 'instance_id': 'step1-p1-inst', 'event_id': 'step1-p1-2',
                'expected_revision': 1, 'state': 'confirmed_owned', 'register': False,
                'observation': {'species_id': candidate['species_id'], 'ivs': candidate['ivs'], 'current_cp': 1492},
            }
            self.assertEqual(self.compare(ev_p1_cp), (200, {'instance_id': 'step1-p1-inst', 'state': 'confirmed_owned', 'revision': 2}))
            # Replay same event_id and conflict on stale revision.
            self.assertEqual(self.compare(ev_p1_cp), (200, {'instance_id': 'step1-p1-inst', 'state': 'confirmed_owned', 'revision': 2}))
            self.assertEqual(self.compare({**ev_p1_cp, 'event_id': 'step1-p1-stale'})[0], 409)

            code, hist_p1 = self.compare({'action': 'ownership_history', 'instance_id': 'step1-p1-inst'})
            self.assertEqual(code, 200)
            self.assertEqual(hist_p1['instance']['current_cp'], 1492)
            self.assertEqual(hist_p1['instance']['current_level'], 20.5)
            self.assertEqual(hist_p1['instance']['current_moves'], candidate['moves'])

            # confirmed_absent -> reconfirm CP-only preserves Lv/moves; explicit move change updates moves; invalid move rejects 400.
            self.assertEqual(self.compare({
                'action': 'ownership', 'instance_id': 'step1-p1-inst', 'event_id': 'step1-p1-3',
                'expected_revision': 2, 'state': 'confirmed_absent',
            })[0], 200)
            self.assertEqual(self.compare({
                'action': 'ownership', 'instance_id': 'step1-p1-inst', 'event_id': 'step1-p1-4',
                'expected_revision': 3, 'state': 'confirmed_owned', 'register': False,
                'observation': {'species_id': candidate['species_id'], 'ivs': candidate['ivs'], 'current_cp': 1498},
            })[0], 200)
            new_moves = {'fast': candidate['moves']['fast'], 'charged': [candidate['moves']['charged'][0]]}
            self.assertEqual(self.compare({
                'action': 'ownership', 'instance_id': 'step1-p1-inst', 'event_id': 'step1-p1-bad-move',
                'expected_revision': 4, 'state': 'confirmed_owned', 'register': False,
                'observation': {'species_id': candidate['species_id'], 'ivs': candidate['ivs'],
                                'current_cp': 1498, 'current_moves': {'fast': 'bad-move', 'charged': ['STONE_EDGE']}},
            })[0], 400)
            self.assertEqual(self.compare({
                'action': 'ownership', 'instance_id': 'step1-p1-inst', 'event_id': 'step1-p1-5',
                'expected_revision': 4, 'state': 'confirmed_owned', 'register': False,
                'observation': {'species_id': candidate['species_id'], 'ivs': candidate['ivs'],
                                'current_cp': 1498, 'current_moves': new_moves},
            })[0], 200)

        store = BattleStore.from_volume()
        owner_db = Ownership(store, species_ids={candidate['species_id']})
        stored = owner_db.get('step1-p1-inst')
        self.assertIsNotNone(stored)
        self.assertEqual(stored['current_cp'], 1498)
        self.assertEqual(stored['current_level'], 20.5)
        self.assertEqual(stored['current_moves'], new_moves)
        self.assertEqual(stored['revision'], 5)

        foreign = BattleStore(store.path, owner_scope='foreign')
        other = Ownership(foreign, species_ids={candidate['species_id']})
        self.assertEqual(other.list_snapshot()['items'], [])
        self.assertEqual(other.list_snapshot()['scopes'], [])
        self.assertIsNone(other.instance_history('step1-inst'))

    def test_step3_readonly_role_history_action_and_validation(self):
        payload = case(threshold=0)
        status, result = self.compare(payload)
        self.assertEqual(status, 200)
        expected_id = result['evaluation_id']
        with patch.object(server.web.BattleService, 'simulate',
                          side_effect=AssertionError('History must never run a battle')):
            code, history = self.compare({'action': 'evaluation_history', 'limit': 1})
            self.assertEqual(code, 200)
            self.assertEqual(len(history['items']), 1)
            self.assertEqual(history['items'][0]['evaluation_id'], expected_id)
            self.assertEqual(history['items'][0]['role_id'], 'lead')
            self.assertTrue(history['items'][0]['versions_current'])
            self.assertEqual(history['items'][0]['state'], result['state'])
            self.assertFalse(history['has_more'])
            for invalid in ({'action': 'evaluation_history', 'limit': True},
                            {'action': 'evaluation_history', 'limit': 0},
                            {'action': 'evaluation_history', 'after_id': expected_id},
                            {'action': 'evaluation_history', 'owner_scope': 'foreign'}):
                self.assertEqual(self.compare(invalid)[0], 400)

    def test_step2_explore_floors_boundaries_progress_ownership_and_isolation(self):
        payload = case(threshold=0)
        payload['scenarios'].append({
            **payload['scenarios'][0],
            'shields': [0, 0],
        })
        status, compared = self.compare(payload)
        self.assertEqual(status, 200)
        ref_build_id = compared['reference']['build_id']
        ref_candidate = compared['candidates'][0]

        base_explore = {
            'action': 'explore',
            'evaluation_id': compared['evaluation_id'],
            'build_id': ref_build_id,
            'budget': 0,
        }
        for bad_floor in ([True, 15, 14], [16, 0, 0], [0, 0], None, ['10', 10, 10]):
            self.assertEqual(self.compare({**base_explore, 'iv_floors': bad_floor})[0], 400)

        code, initial = self.compare({**base_explore, 'iv_floors': [15, 15, 14]})
        self.assertEqual(code, 200)
        self.assertEqual(initial['state'], 'unknown')
        self.assertEqual(initial['raw_iv_count'], 4096)
        self.assertEqual(initial['iv_floors'], [15, 15, 14])
        self.assertEqual(initial['eligible_iv_count'], 2)
        self.assertEqual(initial['completed_iv_count'], 0)
        self.assertEqual(initial['not_fully_tested_iv_count'], 2)
        self.assertEqual(initial['candidate'], {'species_id': ref_candidate['species_id'], 'moves': ref_candidate['moves']})
        self.assertEqual(len(initial['conditions']), 2)
        self.assertEqual([c['completed_count'] for c in initial['conditions']], [0, 0])
        self.assertEqual([c['remaining_count'] for c in initial['conditions']], [2, 2])
        self.assertEqual(set(initial['boundary_counts']), {
            'hp', 'cmp', 'breakpoint', 'bulkpoint',
            'charged_1', 'charged_2', 'incoming_charged_1', 'incoming_charged_2',
        })

        code, partial = self.compare({**base_explore, 'iv_floors': [15, 15, 14], 'budget': 3})
        self.assertEqual(code, 200)
        self.assertEqual(partial['state'], 'partial')
        self.assertEqual(partial['new_battles'], 3)
        self.assertEqual(partial['completed_iv_count'], 1)
        self.assertEqual(partial['qualifying_count'], 1)
        self.assertEqual(partial['not_fully_tested_iv_count'], 1)
        self.assertEqual(sum(c['completed_count'] for c in partial['conditions']), 3)
        self.assertEqual(partial['ownership_summary']['unconfirmed_count'], 1)
        self.assertEqual(partial['ownership_summary']['confirmed_owned_count'], 0)

        code, complete = self.compare({**base_explore, 'iv_floors': [15, 15, 14], 'budget': 1})
        self.assertEqual(code, 200)
        self.assertEqual(complete['state'], 'complete')
        self.assertEqual(complete['new_battles'], 1)
        self.assertEqual(complete['completed_iv_count'], 2)
        self.assertEqual(complete['qualifying_count'], 2)
        self.assertEqual([c['completed_count'] for c in complete['conditions']], [2, 2])
        self.assertEqual([c['remaining_count'] for c in complete['conditions']], [0, 0])
        by_iv = {(q['attack'], q['defense'], q['hp']): q for q in complete['qualifying']}
        self.assertEqual(set(by_iv), {(15, 15, 14), (15, 15, 15)})
        self.assertTrue(all(q['level'] > 0 and q['cp'] >= 10 and q['owned_instances'] == [] for q in by_iv.values()))

        # Register 15/15/15 as confirmed_owned (exact build) and 15/15/14 as confirmed_absent.
        q_exact = by_iv[(15, 15, 15)]
        self.assertEqual(self.compare({
            'action': 'ownership', 'instance_id': 'step2-exact-inst', 'event_id': 'step2-ev-1',
            'expected_revision': 0, 'state': 'confirmed_owned',
            'observation': {
                'species_id': ref_candidate['species_id'],
                'ivs': {'attack': 15, 'defense': 15, 'hp': 15},
                'current_cp': q_exact['cp'], 'current_level': q_exact['level'],
                'current_moves': ref_candidate['moves'],
            },
        })[0], 200)
        q_absent = by_iv[(15, 15, 14)]
        self.assertEqual(self.compare({
            'action': 'ownership', 'instance_id': 'step2-absent-inst', 'event_id': 'step2-ev-2',
            'expected_revision': 0, 'state': 'confirmed_owned',
            'observation': {
                'species_id': ref_candidate['species_id'],
                'ivs': {'attack': 15, 'defense': 15, 'hp': 14},
                'current_cp': q_absent['cp'],
            },
        })[0], 200)
        self.assertEqual(self.compare({
            'action': 'ownership', 'instance_id': 'step2-absent-inst', 'event_id': 'step2-ev-3',
            'expected_revision': 1, 'state': 'confirmed_absent',
        })[0], 200)

        # Foreign owner record for 15/15/14 must stay completely isolated.
        foreign_store = BattleStore.from_volume()
        foreign_owner = Ownership(BattleStore(foreign_store.path, owner_scope='foreign'),
                                  species_ids={ref_candidate['species_id']})
        foreign_owner.register('foreign-only', {
            'species_id': ref_candidate['species_id'],
            'ivs': {'attack': 15, 'defense': 15, 'hp': 14},
            'current_cp': q_absent['cp'], 'current_level': q_absent['level'],
            'current_moves': ref_candidate['moves'],
        })

        code, matched = self.compare({**base_explore, 'iv_floors': [15, 15, 14]})
        self.assertEqual(code, 200)
        self.assertEqual(matched['new_battles'], 0)
        self.assertEqual(matched['ownership_summary'], {
            'confirmed_owned_exact_count': 1,
            'confirmed_owned_count': 1,
            'confirmed_absent_recorded_count': 1,
            'unconfirmed_count': 0,
            'species_confirmed_owned_count': 1,
        })
        # Owned exact qualifying IV is prioritized first.
        self.assertEqual((matched['qualifying'][0]['attack'], matched['qualifying'][0]['defense'], matched['qualifying'][0]['hp']),
                         (15, 15, 15))
        self.assertEqual(matched['qualifying'][0]['owned_instances'][0]['build_match'], 'exact')
        self.assertEqual(matched['qualifying'][1]['owned_instances'][0]['state'], 'confirmed_absent')

        # Narrower floor reuses saved battles with 0 new simulations.
        code, narrow = self.compare({**base_explore, 'iv_floors': [15, 15, 15]})
        self.assertEqual(code, 200)
        self.assertEqual(narrow['new_battles'], 0)
        self.assertEqual(narrow['eligible_iv_count'], 1)
        self.assertEqual(narrow['completed_iv_count'], 1)
        self.assertEqual(narrow['qualifying_count'], 1)

    def test_step4_readonly_tactic_observed_and_sandbox_lists(self):
        import hashlib
        from pvpoke_battle_service import BattleService
        from pvpoke_direct_backend import DirectMatrixClient
        from pvpoke_observed_search import ObservedSearch
        from pvpoke_sandbox import SandboxService
        from pvpoke_sandbox_workspace import TacticStore
        from pvpoke_tactic_search import TacticSearch

        # 503 gating when sandbox / tactic-search / observed flags are disabled
        with patch.dict(os.environ, {'PVP_SANDBOX_ENABLED': '0',
                                     'PVP_TACTIC_SEARCH_ENABLED': '1',
                                     'PVP_OBSERVED_SEARCH_ENABLED': '1'}):
            self.assertEqual(self.compare({'action': 'tactic_search_list'})[0], 503)
            self.assertEqual(self.compare({'action': 'observed_search_list'})[0], 503)
            self.assertEqual(self.compare({'action': 'sandbox_tactic_list'})[0], 503)
        with patch.dict(os.environ, {'PVP_SANDBOX_ENABLED': '1',
                                     'PVP_TACTIC_SEARCH_ENABLED': '0',
                                     'PVP_OBSERVED_SEARCH_ENABLED': '0'}):
            self.assertEqual(self.compare({'action': 'tactic_search_list'})[0], 503)
            self.assertEqual(self.compare({'action': 'observed_search_list'})[0], 503)
            self.assertEqual(self.compare({'action': 'sandbox_tactic_list'}), (200, {'items': []}))

        with patch.dict(os.environ, {'PVP_SANDBOX_ENABLED': '1',
                                     'PVP_TACTIC_SEARCH_ENABLED': '1',
                                     'PVP_OBSERVED_SEARCH_ENABLED': '1'}):
            # Empty before any saved records exist
            self.assertEqual(self.compare({'action': 'tactic_search_list'}),
                             (200, {'items': [], 'has_more': False, 'next_after': None}))
            self.assertEqual(self.compare({'action': 'observed_search_list'}),
                             (200, {'items': [], 'has_more': False, 'next_after': None}))
            self.assertEqual(self.compare({'action': 'sandbox_tactic_list'}), (200, {'items': []}))

            # Evaluate missing analysis baseline so we can also test direct ID reuse
            eval_payload = case(threshold=0)
            status, evaluated = self.compare(eval_payload)
            self.assertEqual(status, 200)
            eval_id = evaluated['evaluation_id']
            battle_spec_base = evaluated['candidates'][0]['conditions'][0]['spec']

            # Create local owner fixed tactic searches (2), observed search (1), and sandbox tactic (2 revisions)
            store = BattleStore.from_volume()
            client = DirectMatrixClient(gamemaster=self.root / 'gamemaster.json', log_dir=self.root)
            self.addCleanup(client.close)
            service = BattleService(client, store=store)
            sandbox = SandboxService(service)
            tactic_search = TacticSearch(service)
            sandbox_base = {k: v for k, v in battle_spec_base.items()
                            if k not in ('calculation_version', 'policies')}
            spec1 = {**sandbox_base, 'mode': 'sandbox', 'actions': [], 'shield_decisions': []}
            spec2 = {**sandbox_base, 'mode': 'sandbox',
                     'combatants': [sandbox_base['combatants'][0],
                                    {**sandbox_base['combatants'][1],
                                     'initial': {**sandbox_base['combatants'][1]['initial'], 'energy': 10}}],
                     'actions': [], 'shield_decisions': []}
            ts1_id = tactic_search.start(spec1)
            tactic_search.step(ts1_id, budget=1)
            ts2_id = tactic_search.start(spec2)

            observed = ObservedSearch(sandbox)
            world1 = {**sandbox_base, 'mode': 'sandbox'}
            world2 = {**sandbox_base, 'mode': 'sandbox',
                      'combatants': [sandbox_base['combatants'][0],
                                     {**sandbox_base['combatants'][1],
                                      'initial': {**sandbox_base['combatants'][1]['initial'], 'energy': 25}}]}
            obs_res = observed.start(
                [world1, world2],
                [{'attack': 'standard', 'shield': 'never'}],
                [{'fast_delay': 0, 'miss_first_fast': False, 'reverse_fast_batch': False}],
                1,
                roles=[{'id': 'win', 'priority': 1, 'outcomes': ['self_ko_win'], 'minimum': {}}],
            )
            observed.step(obs_res['search_id'], 0, 1)

            tstore = TacticStore(store)
            tid = '1' * 32
            tstore.save(sandbox, tid, 0, '初手プラン', spec1)
            tstore.save(sandbox, tid, 1, '初手プラン改', spec2)

            # Create foreign-owner records that must never leak to local owner
            foreign_store = BattleStore(store.path, owner_scope='foreign')
            foreign_service = BattleService(client, store=foreign_store)
            foreign_sandbox = SandboxService(foreign_service)
            foreign_spec = {**sandbox_base, 'mode': 'sandbox',
                            'combatants': [sandbox_base['combatants'][0],
                                           {**sandbox_base['combatants'][1],
                                            'initial': {**sandbox_base['combatants'][1]['initial'], 'energy': 33}}],
                            'actions': [], 'shield_decisions': []}
            foreign_ts_id = TacticSearch(foreign_service).start(foreign_spec)
            foreign_obs = ObservedSearch(foreign_sandbox).start(
                [foreign_spec],
                [{'attack': 'standard', 'shield': 'never'}],
                [{'fast_delay': 0, 'miss_first_fast': False, 'reverse_fast_batch': False}],
                1,
            )
            TacticStore(foreign_store).save(foreign_sandbox, '2' * 32, 0, '他オーナー戦術', foreign_spec)
            self.assertNotEqual(foreign_ts_id, ts1_id)
            self.assertNotEqual(foreign_obs['search_id'], obs_res['search_id'])

            db_before = hashlib.sha256(store.path.read_bytes()).hexdigest()

            # Read-only listing must run zero battles, zero receipt replays, and zero DB writes
            with patch.object(server.web.BattleService, 'simulate',
                              side_effect=AssertionError('List must not simulate')), \
                 patch.object(SandboxService, 'simulate',
                              side_effect=AssertionError('List must not simulate sandbox')), \
                 patch.object(ObservedSearch, '_replay',
                              side_effect=AssertionError('List must not replay receipts')):
                c1, page1 = self.compare({'action': 'tactic_search_list', 'limit': 1})
                self.assertEqual(c1, 200)
                self.assertEqual(len(page1['items']), 1)
                self.assertTrue(page1['has_more'])
                self.assertEqual(page1['next_after'], page1['items'][0]['search_id'])

                c2, page2 = self.compare({'action': 'tactic_search_list', 'limit': 1,
                                          'after_id': page1['next_after']})
                self.assertEqual(c2, 200)
                self.assertEqual(len(page2['items']), 1)
                self.assertFalse(page2['has_more'])
                listed_ts_ids = {page1['items'][0]['search_id'], page2['items'][0]['search_id']}
                self.assertEqual(listed_ts_ids, {ts1_id, ts2_id})
                for item in page1['items'] + page2['items']:
                    self.assertTrue(item['version_current'])
                    self.assertEqual(item['shields'], [1, 1])
                    self.assertIn('species_id', item['self'])
                    self.assertIn('species_id', item['opponent'])
                    if item['search_id'] == ts1_id:
                        self.assertEqual(item['attempted_scripts'], 1)
                        self.assertGreaterEqual(item['complete_scripts'], 0)

                oc, obs_list = self.compare({'action': 'observed_search_list', 'limit': 24})
                self.assertEqual(oc, 200)
                self.assertFalse(obs_list['has_more'])
                self.assertEqual([item['search_id'] for item in obs_list['items']], [obs_res['search_id']])
                obs_item = obs_list['items'][0]
                self.assertEqual(obs_item['work'], 1)
                self.assertEqual(obs_item['world_count'], 2)
                self.assertEqual(len(obs_item['worlds']), 2)
                self.assertFalse(obs_item['worlds_truncated'])
                self.assertEqual(obs_item['worlds'][0]['energy'], 0)
                self.assertEqual(obs_item['roles'], ['win'])
                self.assertTrue(obs_item['version_current'])

                sc, sb_list = self.compare({'action': 'sandbox_tactic_list'})
                self.assertEqual(sc, 200)
                self.assertEqual([item['tactic_id'] for item in sb_list['items']], [tid])
                sb_item = sb_list['items'][0]
                self.assertEqual((sb_item['revision'], sb_item['name'], sb_item['energy']), (2, '初手プラン改', 0))
                self.assertTrue(sb_item['version_current'])

                # Validation rejects invalid arguments / unknown keys / owner_scope
                for bad in ({'action': 'tactic_search_list', 'limit': True},
                            {'action': 'tactic_search_list', 'limit': 33},
                            {'action': 'tactic_search_list', 'after_id': 'bad'},
                            {'action': 'tactic_search_list', 'owner_scope': 'foreign'},
                            {'action': 'observed_search_list', 'limit': 0},
                            {'action': 'observed_search_list', 'owner_scope': 'foreign'},
                            {'action': 'sandbox_tactic_list', 'owner_scope': 'foreign'},
                            {'action': 'sandbox_tactic_list', 'limit': 5}):
                    self.assertEqual(self.compare(bad)[0], 400, bad)

            self.assertEqual(hashlib.sha256(store.path.read_bytes()).hexdigest(), db_before)

            # End-to-end: feed listed search IDs straight into evidence actions without sessionStorage links
            ev_c, ev_data = self.compare({'action': 'tactic_evidence', 'evaluation_id': eval_id,
                                          'search_ids': [ts1_id]})
            self.assertEqual(ev_c, 200)
            self.assertEqual(ev_data['searched_count'], 1)

            oe_c, oe_data = self.compare({'action': 'observed_evidence', 'evaluation_id': eval_id,
                                          'search_ids': [obs_res['search_id']]})
            self.assertEqual(oe_c, 200)
            self.assertEqual(oe_data['links'][0]['search_id'], obs_res['search_id'])

            # Fail closed (503) if row tactic_id or revision mismatches body even when digest is valid
            tid_b = '3' * 32
            tstore.save(sandbox, tid_b, 0, '別戦術B', spec1)
            tstore.save(sandbox, tid_b, 1, '別戦術B第2版', spec2)
            with store._reader() as db:
                row_a1 = db.execute("SELECT body, digest FROM sandbox_tactics_v1 WHERE tactic_id=? AND revision=1",
                                    (tid,)).fetchone()
                row_a2 = db.execute("SELECT body, digest FROM sandbox_tactics_v1 WHERE tactic_id=? AND revision=2",
                                    (tid,)).fetchone()
                row_b2 = db.execute("SELECT body, digest FROM sandbox_tactics_v1 WHERE tactic_id=? AND revision=2",
                                    (tid_b,)).fetchone()
            with store._writer(critical=True) as db:
                db.execute("UPDATE sandbox_tactics_v1 SET body=?, digest=? WHERE tactic_id=? AND revision=2",
                           (row_a1[0], row_a1[1], tid))
            self.assertEqual(self.compare({'action': 'sandbox_tactic_list'})[0], 503)
            with store._writer(critical=True) as db:
                db.execute("UPDATE sandbox_tactics_v1 SET body=?, digest=? WHERE tactic_id=? AND revision=2",
                           (row_b2[0], row_b2[1], tid))
            self.assertEqual(self.compare({'action': 'sandbox_tactic_list'})[0], 503)
            with store._writer(critical=True) as db:
                db.execute("UPDATE sandbox_tactics_v1 SET body=?, digest=? WHERE tactic_id=? AND revision=2",
                           (row_a2[0], row_a2[1], tid))
            self.assertEqual(self.compare({'action': 'sandbox_tactic_list'})[0], 200)

            # Fail closed (503) if stored records are corrupted
            with store._writer(critical=True) as db:
                db.execute("UPDATE tactic_searches_v1 SET digest='bad' WHERE search_id=?", (ts1_id,))
                db.execute("UPDATE observed_jobs_v2 SET plan='{}' WHERE id=?", (obs_res['search_id'],))
                db.execute("UPDATE sandbox_tactics_v1 SET digest='bad' WHERE tactic_id=?", (tid,))
            self.assertEqual(self.compare({'action': 'tactic_search_list'})[0], 503)
            self.assertEqual(self.compare({'action': 'observed_search_list'})[0], 503)
            self.assertEqual(self.compare({'action': 'sandbox_tactic_list'})[0], 503)
