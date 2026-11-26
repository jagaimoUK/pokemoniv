"""Synthetic and static security checks for Cloud Run preview configuration."""
import contextlib
import io
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('PVP_API_KEY', 'test-' + 'x' * 32)
import pvpoke_mcp_remote as remote
import pvpoke_seed_preview as seed_preview
from pvpoke_battle_store import BattleStore
from pvpoke_individual_sync import app_operation


class PreviewSecurityTests(unittest.TestCase):
    def test_parse_extra_origins_accepts_https_and_rejects_unsafe_values(self):
        parsed = remote.parse_extra_origins(' https://preview.example.run.app/ , http://127.0.0.1:8787 ')
        self.assertEqual(parsed, {'https://preview.example.run.app', 'http://127.0.0.1:8787'})
        self.assertEqual(remote.parse_extra_origins(''), set())

        for invalid in (
            '*',
            'https://*',
            'http://preview.example.run.app',
            'https://preview.example.run.app/path',
            'https://user:pass@preview.example.run.app',
            'https://preview.example.run.app?x=1',
            'javascript:alert(1)',
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    remote.parse_extra_origins(invalid)

    def test_seed_preview_uses_synthetic_data_without_logging_tokens_and_blocks_railway_mount(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {
                'PVP_ARCHIVE_DIR': tmpdir,
                'PVP_API_KEY': 'synthetic-preview-test-key-000000000000',
            }
            stdout = io.StringIO()
            with patch.dict(os.environ, env, clear=False):
                os.environ.pop('RAILWAY_VOLUME_MOUNT_PATH', None)
                with contextlib.redirect_stdout(stdout):
                    seed_preview.seed()
            out = stdout.getvalue()
            self.assertNotIn('is1.', out)
            self.assertNotIn('PREVIEW_CONNECTION_CODE', out)

            store = BattleStore(Path(tmpdir) / 'pvpoke_archives' / 'battle_analysis.sqlite3')
            known = app_operation(store, {'action': 'individual_get', 'instance_id': 'smoke-known-1'})
            self.assertEqual(known['individual']['species_id'], 'quagsire')
            self.assertEqual(known['individual']['current_cp'], 1498)
            self.assertEqual(known['individual']['ivs'], {'attack': 0, 'defense': 11, 'hp': 12})

            with patch.dict(os.environ, {'RAILWAY_VOLUME_MOUNT_PATH': tmpdir}, clear=False):
                with self.assertRaises(RuntimeError):
                    seed_preview.seed()

    def test_cloud_run_preview_workflow_static_security_invariants(self):
        wf_path = Path(__file__).resolve().parent.parent / '.github' / 'workflows' / 'cloud-run-preview.yml'
        raw = wf_path.read_text(encoding='utf-8')
        self.assertNotIn('pokemoniv-preview-key-32chars-exact-min', raw)
        self.assertNotIn('SMOKE_CODE', raw)
        self.assertNotIn('PREVIEW_CONNECTION_CODE', raw)
        self.assertNotIn('pull_request_target', raw)

        self.assertRegex(raw, r'(?m)^\s*group:\s*cloud-run-preview-service\s*$')
        self.assertRegex(raw, r'(?m)^\s*cancel-in-progress:\s*false\s*$')
        self.assertRegex(raw, r'(?m)^\s*persist-credentials:\s*false\s*$')
        self.assertIn('head.repo.full_name == github.repository', raw)
        self.assertIn('secrets.PREVIEW_PVP_API_KEY', raw)
        self.assertIn('--env-vars-file', raw)
        self.assertIn('--min-instances 0', raw)
        self.assertIn('--max-instances 1', raw)
        for step_name in (
            'Pre-deploy static checks and synthetic unit tests',
            'Validate required preview secrets',
            'Post-deploy health and synthetic API smoke test',
            'Prune older unused Cloud Run revisions (best-effort)',
            'Upsert Preview URL Comment on PR',
        ):
            self.assertIn(step_name, raw)


if __name__ == '__main__':
    unittest.main()
