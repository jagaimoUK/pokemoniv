"""Synthetic edits against the real SQLite sync transaction."""
from pathlib import Path
import tempfile
import unittest

from pvpoke_auth_store import CredentialStore
from pvpoke_battle_store import BattleStore
from pvpoke_individual_sync import IndividualConnections, IndividualUnavailable, KIND, app_operation
from pvpoke_ownership import Ownership, OwnershipConflict


class IndividualSyncTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = BattleStore(self.root / 'battle-analysis.sqlite3')
        self.inventory = Ownership(self.store, species_ids={'quagsire'})
        self.observation = {'species_id': 'quagsire', 'current_cp': 1498,
                            'ivs': {'attack': 0, 'defense': 11, 'hp': 12}}
        self.inventory.register('known', self.observation)
        self.inventory.confirm('confirm-known', 'known', expected_revision=0, state='confirmed_owned')
        self.inventory.register('unconfirmed', self.observation)

    def read(self, instance_id='known', store=None):
        return app_operation(store or self.store, {'action': 'individual_get', 'instance_id': instance_id})

    def request(self, request_id, **changes):
        return {'action': 'individual_patch', 'instance_id': 'known', 'request_id': request_id,
                'changes': {field: {'revision': revision, 'value': value}
                            for field, (revision, value) in changes.items()}}

    def test_lost_response_retry_is_idempotent_even_after_another_edit(self):
        original = self.request('android-a', nickname=(0, 'Alpha'))
        first = app_operation(self.store, original)
        self.assertEqual(first['fields']['nickname']['revision'], 1)
        app_operation(self.store, self.request('web-b', nickname=(1, 'Beta')))
        reopened = BattleStore(self.store.path)
        replay = app_operation(reopened, original)
        self.assertEqual(replay['outcomes'], {'nickname': 'applied'})
        self.assertEqual(replay['fields']['nickname'], {'revision': 2, 'value': 'Beta'})
        with self.assertRaises(OwnershipConflict):
            app_operation(reopened, self.request('android-a', nickname=(2, 'Gamma')))
        self.assertEqual(self.read(store=reopened)['fields']['nickname']['revision'], 2)
        self.assertEqual(self.inventory.get('known')['revision'], 1)

    def test_disjoint_edits_merge_and_only_the_contested_field_is_held(self):
        app_operation(self.store, self.request('web', nickname=(0, 'Web')))
        disjoint = app_operation(self.store, self.request('android', memo=(0, 'Android memo')))
        self.assertEqual(disjoint['outcomes'], {'memo': 'applied'})
        self.assertEqual(disjoint['fields']['nickname']['value'], 'Web')
        contested = self.request('android-next', nickname=(0, 'Phone'), memo=(1, 'New memo'))
        mixed = app_operation(self.store, contested)
        self.assertEqual(mixed['outcomes'], {'nickname': 'conflict', 'memo': 'applied'})
        self.assertEqual(mixed['fields'], {
            'nickname': {'revision': 1, 'value': 'Web'},
            'memo': {'revision': 2, 'value': 'New memo'},
        })
        self.assertEqual(app_operation(self.store, contested), mixed)
        resolved = app_operation(self.store, self.request('resolve', nickname=(1, 'Phone')))
        self.assertEqual(resolved['fields']['nickname'], {'revision': 2, 'value': 'Phone'})
        self.assertEqual(resolved['fields']['memo']['revision'], 2)

    def test_unconfirmed_and_foreign_individuals_fail_closed(self):
        with self.assertRaises(IndividualUnavailable):
            self.read('unconfirmed')
        with self.assertRaises(IndividualUnavailable):
            self.read(store=BattleStore(self.store.path, owner_scope='different-owner'))
        self.inventory.confirm('no-longer-confirmed', 'known', expected_revision=1, state='confirmed_absent')
        with self.assertRaises(IndividualUnavailable):
            app_operation(self.store, self.request('stale', nickname=(0, 'No edit')))

    def test_connection_is_signed_for_one_id_and_revocable(self):
        credentials = CredentialStore(self.root / 'auth.sqlite3')
        connections = IndividualConnections('synthetic-signer', credentials)
        token = connections.issue('known')
        self.assertEqual(connections.instance('Bearer ' + token), 'known')
        self.assertIsNone(connections.instance('Bearer ' + token.replace('.known.', '.other.')))
        credentials.revoke(credentials.fingerprint(token), KIND)
        self.assertIsNone(connections.instance('Bearer ' + token))
