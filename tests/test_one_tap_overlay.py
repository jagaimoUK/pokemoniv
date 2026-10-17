from pathlib import Path
import unittest

root = Path(__file__).resolve().parents[1]
activity = (root / "android-integration/overlayqueue/OverlayCopyQueueImportActivity.kt").read_text()
demo = (root / "demo/app/src/main/java/com/example/pokemonivreader/overlayqueue/OverlayCopyQueueImportActivity.kt").read_text()
controller = (root / "android-integration/overlayqueue/OverlayCopyQueueController.kt").read_text()
manifest = (root / "demo/app/src/main/AndroidManifest.xml").read_text()

class OneTapBridgeContract(unittest.TestCase):
    def test_demo_importer_matches_integrated_source(self):
        self.assertEqual(activity, demo)
    def test_share_and_deep_link_auto_import(self):
        self.assertIn('Intent.ACTION_SEND', activity)
        self.assertIn('Intent.ACTION_VIEW', activity)
        self.assertIn('Base64.URL_SAFE', activity)
        self.assertIn('importRaw(incoming)', activity)
        self.assertIn('private fun importRaw(raw: String)', activity)
        self.assertIn('OverlayCopyQueueController.get(this).onImported()', activity)
    def test_no_mandatory_manual_steps(self):
        self.assertIn('fun onImported()', controller)
        on_imported = controller.split('fun onImported()', 1)[1].split('private fun refresh()', 1)[0]
        self.assertIn('openPanel()', on_imported)
        self.assertIn('setSelectionFromTop(0, 0)', on_imported)
    def test_browser_deep_link_is_explicitly_registered(self):
        self.assertIn('android:scheme="pokemonivreader"', manifest)
        self.assertIn('android:host="import"', manifest)
        self.assertIn('android.intent.category.BROWSABLE', manifest)
        self.assertIn('android.intent.action.SEND', manifest)

if __name__ == "__main__":
    unittest.main()
