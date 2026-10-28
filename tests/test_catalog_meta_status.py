"""Existing get_catalog also reports persisted meta/storage statuses."""
import unittest
from unittest.mock import patch
import pvpoke_bridge_core as bridge
import pvpoke_web as web


class CatalogStorageTest(unittest.TestCase):
    def test_web_catalog_exposes_conditional_return_for_preview_validation(self):
        species={'grumpig':{'speciesName':'Grumpig','dex':326,'fastMoves':['PSYWAVE'],
            'chargedMoves':['DYNAMIC_PUNCH'],'tags':['shadoweligible'],'level25CP':1441}}
        with patch.dict(web.CATALOG), patch.object(web,'configure_engine'), \
                patch.object(web.engine,'game_data',return_value=({'timestamp':'test'},[],species)):
            web.load_catalog()
            self.assertTrue(web.CATALOG['ready'],web.CATALOG['error'])
            entry=web.CATALOG['species']['grumpig']
            self.assertIn('RETURN',entry['chargedMoves'])
            self.assertEqual(web.normalize_pokemon({'species':'grumpig','fast':'PSYWAVE',
                'charged1':'DYNAMIC_PUNCH','charged2':'RETURN'},web.CATALOG['species'],'メタ'),
                ['grumpig','PSYWAVE','DYNAMIC_PUNCH','RETURN'])
        self.assertEqual(species['grumpig']['chargedMoves'],['DYNAMIC_PUNCH'])

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

