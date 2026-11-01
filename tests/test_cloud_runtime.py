from pathlib import Path
import unittest

from pvpoke_cloud_runtime import check
from pvpoke_proxy_config import render
from pvpoke_browser_migration import page


class CloudRuntimeTests(unittest.TestCase):
    def test_existing_hosts_unchanged(self):
        check({})
        check({'RAILWAY_VOLUME_MOUNT_PATH': '/data'})

    def test_cloud_production_blocked_even_with_one_instance(self):
        for mode in ('', 'production', 'firestore'):
            with self.assertRaises(ValueError):
                check({'K_SERVICE': 'app', 'PVP_CLOUD_MODE': mode})

    def test_validation_requires_disposable_storage(self):
        env = {'K_SERVICE': 'app', 'PVP_CLOUD_MODE': 'validation', 'PVP_ARCHIVE_DIR': '/tmp/validation'}
        check(env)
        for path in ('', '/data', '/tmp', 'tmp/app', '/tmp/../data'):
            with self.assertRaises(ValueError):
                check({**env, 'PVP_ARCHIVE_DIR': path})
        for key in ('PVP_AUTH_DB', 'RAILWAY_VOLUME_MOUNT_PATH', 'VISUAL_BACKUP_S3_BUCKET'):
            with self.assertRaises(ValueError):
                check({**env, key: 'production'})

    def test_public_port_is_configured_and_private_ports_stay_private(self):
        self.assertIn('listen 8080;', render('8080'))
        for port in ('bad', 8765, 8788, 80):
            with self.assertRaises(ValueError):
                render(port)

    def test_backup_page_is_embedded_for_csp_and_in_container(self):
        html = page()
        self.assertIn('pokemoniv-browser-backup-v1', html)
        self.assertNotIn('src="http', html)
        self.assertIn('COPY pvpoke_browser_migration.js', Path('Dockerfile').read_text())


if __name__ == '__main__':
    unittest.main()
