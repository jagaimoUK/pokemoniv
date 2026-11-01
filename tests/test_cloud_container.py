"""CI-only smoke of the actual existing image, not a Cloud Run durability claim."""
import json
import os
import shutil
import subprocess
import time
import unittest
import urllib.error
import urllib.request


@unittest.skipUnless(shutil.which('docker') and os.environ.get('PVP_CLOUD_IMAGE'),
                     'Requires an explicitly selected built Docker image')
class CloudContainerTests(unittest.TestCase):
    def docker(self, *args, check=True):
        return subprocess.run(['docker', *args], check=check, capture_output=True, text=True, timeout=90)

    def test_production_start_guard_in_built_image(self):
        result = self.docker('run', '--rm', '--entrypoint', 'python', '-e', 'K_SERVICE=cloud-ci',
                             os.environ['PVP_CLOUD_IMAGE'], '/app/pvpoke_cloud_runtime.py', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('production is blocked', result.stderr)

    def test_validation_port_health_page_and_auth(self):
        container = self.docker('run', '-d', '--rm', '-p', '127.0.0.1::8080',
            '-e', 'K_SERVICE=cloud-ci', '-e', 'PORT=8080', '-e', 'PVP_CLOUD_MODE=validation',
            '-e', 'PVP_ARCHIVE_DIR=/tmp/pokemoniv-validation',
            '-e', 'PVP_API_KEY=synthetic-container-test-key-0000000000000000000000',
            os.environ['PVP_CLOUD_IMAGE']).stdout.strip()
        self.addCleanup(lambda: self.docker('rm', '-f', container, check=False))
        port = self.docker('port', container, '8080/tcp').stdout.strip().rsplit(':', 1)[-1]
        base = 'http://127.0.0.1:' + port
        deadline = time.monotonic() + 60
        while True:
            try:
                with urllib.request.urlopen(base + '/health', timeout=2) as response:
                    self.assertEqual(response.status, 200)
                    break
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if time.monotonic() >= deadline:
                    self.fail('Container never became healthy: ' + self.docker('logs', container).stdout[-1500:])
                time.sleep(0.3)
        with urllib.request.urlopen(base + '/app/migration', timeout=5) as response:
            self.assertIn(b'pokemoniv-browser-backup-v1', response.read())
            self.assertIn('sha256-', response.headers['Content-Security-Policy'])
        request = urllib.request.Request(base + '/app-api/catalog', data=b'{}',
                                          headers={'Content-Type': 'application/json'})
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(error.exception.code, 401)


if __name__ == '__main__':
    unittest.main()
