"""Existing get_catalog also reports persisted meta/storage statuses."""
import unittest
from unittest.mock import patch
import pvpoke_bridge_core as bridge


class CatalogStorageTest(unittest.TestCase):
    def test_catalog_reports_synced_meta_and_archive_stats(self):
        def fake_request(path, *args, **kwargs):
            if path == "/api/catalog":
                return {"ready": True, "timestamp": "2026-10-13", "species": {"quagsire": {}}, "presets": []}
            if path == "/api/meta/status":
                return {"rows": 87, "sha256": "abc", "source": "bundled"}
            if path == "/api/storage/status":
                return {"archive_count": 3, "archive_bytes": 120000, "latest_exists": True}
            raise ValueError(path)
        with patch.object(bridge, "_request", side_effect=fake_request):
            result = bridge.catalog()
            self.assertEqual(result["meta_status"]["rows"], 87)
            self.assertEqual(result["storage_status"]["archive_count"], 3)
            self.assertEqual(result["species_count"], 1)


if __name__ == "__main__":
    unittest.main()
