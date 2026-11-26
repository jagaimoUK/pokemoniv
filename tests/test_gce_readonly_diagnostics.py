"""Offline checks: GCE diagnostic helper must not execute arbitrary shell commands."""
from __future__ import annotations

import contextlib
import importlib.util
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'deploy/compute-engine/gce_readonly_diagnostics.py'
spec = importlib.util.spec_from_file_location('gce_readonly_diagnostics', TARGET)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class GceReadonlyDiagnosticsTests(unittest.TestCase):
    def test_command_whitelist(self):
        self.assertEqual(mod.CHECKS, ('health', 'storage', 'missing'))
        with patch.object(mod.os, 'geteuid', return_value=0), patch.object(mod.sys, 'argv', ['helper', ';rm -rf /']):
            with self.assertRaises(SystemExit) as raised:
                mod.main()
            self.assertEqual(raised.exception.code, 2)

    def test_docker_does_not_use_shell(self):
        class FakeResult:
            returncode = 0
            stdout = 'ok\n'
        with patch.object(mod.subprocess, 'run', return_value=FakeResult()) as run:
            self.assertEqual(mod.docker('inspect', '--format', '{{.State.Status}}'), 'ok')
        args, kwargs = run.call_args
        self.assertEqual(args[0][0], '/usr/bin/docker')
        self.assertNotIn('shell', kwargs)
        self.assertEqual(kwargs['timeout'], 20)

    def test_storage_does_not_read_db_records(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            (data / 'pvpoke_archives').mkdir()
            (data / 'pvpoke_archives' / 'battle_analysis.sqlite3').write_bytes(b'abcd')
            mounts = json.dumps([
                {'Destination': '/data', 'Source': str(data)},
                {'Destination': '/home/appuser/pvpoke_automation_web', 'Source': '/srv/pokemoniv/work'},
            ])
            with patch.object(mod, 'DATA', data), patch.object(mod, 'ARCHIVE', data / 'pvpoke_archives'), patch.object(mod, 'docker', return_value=mounts):
                out = StringIO()
                with contextlib.redirect_stdout(out):
                    mod.storage()
                self.assertIn('data_mount_correct=true', out.getvalue())
                self.assertIn('battle_analysis.sqlite3_bytes=4', out.getvalue())
                self.assertNotIn('abcd', out.getvalue())

    def test_missing_uses_nonroot_container_user(self):
        with patch.object(mod, 'docker', return_value='catalog_ready=true') as command:
            with tempfile.TemporaryDirectory() as folder:
                with patch.object(mod, 'ARCHIVE', Path(folder)):
                    out = StringIO()
                    with contextlib.redirect_stdout(out):
                        mod.missing()
                    self.assertIn('catalog_ready=true', out.getvalue())
        args = command.call_args.args
        self.assertEqual(args[:5], ('exec', '--user', '10001', '--env', 'HOME=/home/appuser'))
        self.assertEqual(args[-3:-1], ('python', '-c'))
        self.assertNotIn('PVP_API_KEY', args[-1])


if __name__ == '__main__':
    unittest.main()
