from io import BytesIO
import unittest

from tools import cloud_migration_objects as objects


class PreconditionFailed(Exception):
    response = {'ResponseMetadata': {'HTTPStatusCode': 412}}


class FakeStorage:
    def __init__(self, data=None):
        self.data = dict(data or {})
        self.puts = 0
        self.corrupt = False

    def get_paginator(self, _):
        return self

    def paginate(self, **kwargs):
        yield {'Contents': [{'Key': k, 'Size': len(v), 'ETag': '"' + objects.hashlib.sha256(v).hexdigest() + '"'}
                            for k, v in self.data.items() if k.startswith(kwargs['Prefix'])]}

    def get_object(self, **kwargs):
        data = self.data[kwargs['Key']]
        if 'IfMatch' in kwargs and kwargs['IfMatch'] != '"' + objects.hashlib.sha256(data).hexdigest() + '"':
            raise PreconditionFailed()
        return {'Body': BytesIO(data), 'Metadata': {'original': 'keep'}, 'ContentType': 'application/zip'}

    def put_object(self, **kwargs):
        assert kwargs['IfNoneMatch'] == '*'
        if kwargs['Key'] in self.data:
            raise PreconditionFailed()
        self.puts += 1
        self.data[kwargs['Key']] = b'x' if self.corrupt else kwargs['Body'].read()


class ObjectMigrationTests(unittest.TestCase):
    def setUp(self):
        self.source = FakeStorage({'pokemoniv/visual-reference/latest.zip': b'private learning data'})
        self.target = FakeStorage()
        self.plan = objects.plan(self.source, 'source')

    def copy(self, **overrides):
        args = dict(source=self.source, target=self.target, proposal=self.plan,
                    target_bucket='target', target_prefix='migration-test/',
                    approved_sha256=self.plan['plan_sha256'])
        return objects.copy(**{**args, **overrides})

    def test_dry_plan_and_verified_idempotent_copy(self):
        self.assertEqual(self.source.puts, 0)
        result = self.copy()
        self.assertTrue(result['verified'])
        self.assertFalse(result['published'])
        self.assertEqual(self.target.puts, 1)
        self.assertEqual(self.copy(), result)
        self.assertEqual(self.target.puts, 1)
        self.assertEqual(self.source.data['pokemoniv/visual-reference/latest.zip'], b'private learning data')

    def test_collision_never_overwrites(self):
        self.target.data['migration-test/pokemoniv/visual-reference/latest.zip'] = b'other private data'
        with self.assertRaises(ValueError):
            self.copy()
        self.assertEqual(self.target.puts, 0)

    def test_corruption_does_not_verify_or_modify_source(self):
        self.target.corrupt = True
        with self.assertRaises(ValueError):
            self.copy()
        self.assertEqual(len(self.source.data), 1)

    def test_stale_plan_and_budgets_and_live_prefix_blocked(self):
        for args in ({'max_bytes': 0}, {'target_prefix': ''}, {'approved_sha256': '0'*64}):
            with self.assertRaises(ValueError):
                self.copy(**args)
        self.source.data['new.zip'] = b'changed'
        with self.assertRaises(ValueError):
            self.copy()
        self.assertEqual(self.target.puts, 0)


if __name__ == '__main__':
    unittest.main()
