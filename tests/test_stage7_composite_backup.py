"""Composite synthetic restore of existing owner ledger, observed search and settings."""
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from pvpoke_battle_service import BattleService
from pvpoke_battle_store import BattleStore
from pvpoke_observed_search import ObservedSearch
from pvpoke_ownership import Ownership
from pvpoke_role_evaluation import RoleEvaluation
from pvpoke_sandbox import SandboxService
from test_missing_observed_evidence import MissingObservedEvidenceTests
from tools import cloud_migration_backup as backup


class Stage7CompositeRestore(unittest.TestCase):
    def test_owner_observed_evaluation_and_settings_survive_backup_restore(self):
        fixture = MissingObservedEvidenceTests(
            "test_link_matches_only_exact_build_and_starting_conditions_without_writes")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        other_root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        bundle, target = other_root / "bundle", other_root / "restored"

        inventory = Ownership(fixture.store, species_ids={"quagsire"})
        inventory.register("synthetic-subject", {
            "species_id": "quagsire",
            "ivs": {"attack": 0, "defense": 11, "hp": 12}})
        inventory.confirm("synthetic-confirm", "synthetic-subject",
                          expected_revision=0, state="confirmed_owned")
        individual = inventory.get("synthetic-subject")
        events = inventory.history("synthetic-subject")
        revision = inventory.revision()
        role = fixture.evaluation()
        search_id = fixture.observed()
        previous = ObservedSearch(fixture.sandbox)
        previous.step(search_id, 0, 1)
        previous_summary = previous.get(search_id)
        previous_role = RoleEvaluation(fixture.store).history(role["evaluation_id"])
        self.assertEqual(previous_summary["work"], 1)
        settings = fixture.root / "stage7-settings.json"
        settings.write_text(json.dumps({"observed_enabled": False, "kind": "synthetic"},
                                       sort_keys=True), encoding="utf-8")
        settings_digest = hashlib.sha256(settings.read_bytes()).hexdigest()
        before = backup.sqlite_inventory(fixture.store.path)

        self.assertTrue(backup.backup({"synthetic": fixture.root}, bundle)["verified"])
        manifest = backup.verify(bundle)
        self.assertGreaterEqual(len(manifest["files"]), 2)
        backup.restore(bundle, target)
        restored_path = target / "synthetic" / fixture.store.path.name
        with sqlite3.connect(restored_path) as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(backup.sqlite_inventory(restored_path), before)
        self.assertEqual(hashlib.sha256((target / "synthetic" / settings.name).read_bytes()).hexdigest(),
                         settings_digest)

        restored_store = BattleStore(restored_path)
        restored_ownership = Ownership(restored_store, species_ids={"quagsire"})
        self.assertEqual(restored_ownership.get("synthetic-subject"), individual)
        self.assertEqual(restored_ownership.history("synthetic-subject"), events)
        self.assertEqual(restored_ownership.revision(), revision)
        self.assertEqual(RoleEvaluation(restored_store).history(role["evaluation_id"]),
                         previous_role)
        service = BattleService(fixture.client, store=restored_store)
        next_summary = ObservedSearch(SandboxService(service)).get(search_id)
        self.assertEqual(next_summary["work"], previous_summary["work"])
        self.assertEqual(next_summary["status"], previous_summary["status"])

        other = Ownership(BattleStore(restored_path, owner_scope="foreign"),
                          species_ids={"quagsire"})
        self.assertIsNone(other.get("synthetic-subject"))
        self.assertEqual(other.history("synthetic-subject"), [])
        print("STAGE7_BACKUP_RESULT " + json.dumps({
            "verified": True, "observed_receipts": previous_summary["work"],
            "owner_events": len(events), "owner_revision": revision,
            "settings_digest_equal": True, "integrity": "ok",
            "foreign_owner_hidden": True}, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
