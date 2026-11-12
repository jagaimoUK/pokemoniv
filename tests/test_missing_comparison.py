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

    def test_flag_origin_auth_and_fixed_route(self):
        auth = {'Authorization': 'Bearer ' + server.gateway.API_KEY, 'Content-Type': 'application/json'}
        with patch.dict(os.environ, {'PVP_MISSING_ANALYSIS_ENABLED': '0'}):
            self.assertEqual(request(self.server, PAGE_PATH)[0], 404)
            self.assertEqual(request(self.server, APP_PATH, case(), headers=auth)[0], 503)
        with patch.dict(os.environ, {'PVP_MISSING_ANALYSIS_ENABLED': '1'}), patch.object(
                server.gateway.backend, '_token', return_value='local-test-token'), patch.object(
                server.gateway.backend, '_request', return_value={'state': 'evidence_pending'}) as call:
            code, html, headers = request(self.server, PAGE_PATH)
            self.assertEqual(code, 200)
            self.assertIn('不足'.encode(), html)
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
