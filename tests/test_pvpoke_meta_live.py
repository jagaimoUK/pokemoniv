"""Project snapshot synchronization is atomic, validated, and persistent."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pvpoke_meta_live as live


SPECIES = {
    "quagsire": {
        "fastMoves": ["MUD_SHOT"],
        "chargedMoves": ["AQUA_TAIL", "STONE_EDGE", "MUD_BOMB"],
    },
    "altaria": {
        "fastMoves": ["DRAGON_BREATH"],
        "chargedMoves": ["SKY_ATTACK", "FLAMETHROWER"],
    },
}


class LiveMetaTests(unittest.TestCase):
    def test_atomic_persist_and_same_content_no_change(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.dict(os.environ, {"PVP_ARCHIVE_DIR": d}):
                work = Path(d) / "work"
                source = ("quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n"
                          "altaria,DRAGON_BREATH,SKY_ATTACK,FLAMETHROWER\n")
                first = live.sync(work, source, SPECIES)
                self.assertTrue(first["changed"])
                self.assertEqual(first["rows"], 2)
                self.assertEqual(first["source"], "project_synced")
                self.assertEqual(live.active_path(work).read_text(), source)
                again = live.sync(work, source, SPECIES)
                self.assertFalse(again["changed"])
                self.assertEqual(first["sha256"], again["sha256"])

    def test_invalid_replacement_preserves_prior_source(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.dict(os.environ, {"PVP_ARCHIVE_DIR": d}):
                work = Path(d) / "work"
                good = "quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n"
                live.sync(work, good, SPECIES)
                old = live.get_status(work)["sha256"]
                with self.assertRaises(ValueError):
                    live.sync(work, "quagsire,MUD_SHOT,AQUA_TAIL,INVALID\n", SPECIES)
                self.assertEqual(live.get_status(work)["sha256"], old)
                self.assertEqual(live.active_path(work).read_text(), good)

    def test_duplicate_upload_consolidated_but_malformed_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.dict(os.environ, {"PVP_ARCHIVE_DIR": d}):
                work = Path(d) / "work"
                row = "quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n"
                saved = live.sync(work, row + row, SPECIES)
                self.assertEqual(saved["rows"], 1)
                self.assertEqual(saved["duplicate_count"], 1)
                self.assertEqual(live.active_path(work).read_text(), row)
                with self.assertRaises(ValueError):
                    live.sync(work, "quagsire,MUD_SHOT,STONE_EDGE\n", SPECIES)

    def test_preview_only_then_exact_apply_with_optimistic_lock(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.dict(os.environ, {"PVP_ARCHIVE_DIR": d}):
                work = Path(d) / "work"
                original = "quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n"
                replacement = ("quagsire,MUD_SHOT,AQUA_TAIL,MUD_BOMB\n"
                               "altaria,DRAGON_BREATH,SKY_ATTACK,FLAMETHROWER\n")
                live.sync(work, original, SPECIES)
                old = live.get_status(work)
                proposal = live.preview(work, replacement, SPECIES)
                self.assertEqual(proposal["current_rows"], 1)
                self.assertEqual(proposal["rows"], 2)
                self.assertEqual(proposal["added_count"], 2)
                self.assertEqual(proposal["removed_count"], 1)
                self.assertTrue(proposal["changed"])
                self.assertEqual(live.get_status(work), old)
                with self.assertRaisesRegex(ValueError, "プレビュー"):
                    live.sync(work, replacement, SPECIES,
                              expected_previous_sha256="0" * 64,
                              expected_sha256=proposal["sha256"])
                with self.assertRaisesRegex(ValueError, "プレビュー"):
                    live.sync(work, original, SPECIES,
                              expected_previous_sha256=old["sha256"],
                              expected_sha256=proposal["sha256"])
                self.assertEqual(live.active_path(work).read_text(), original)
                saved = live.sync(work, replacement, SPECIES,
                                  expected_previous_sha256=old["sha256"],
                                  expected_sha256=proposal["sha256"])
                self.assertTrue(saved["changed"])
                self.assertEqual(saved["rows"], 2)
                self.assertEqual(live.active_path(work).read_text(), replacement)
                with self.assertRaisesRegex(ValueError, "プレビュー"):
                    live.sync(work, original, SPECIES,
                              expected_previous_sha256=old["sha256"])

    def test_preview_rejects_invalid_data_without_changing_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.dict(os.environ, {"PVP_ARCHIVE_DIR": d}):
                work = Path(d) / "work"
                old = live.get_status(work)
                for content in (
                    "quagsire,MUD_SHOT,BOGUS,STONE_EDGE\n",
                    "missingno,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n",
                    "quagsire,MUD_SHOT,AQUA_TAIL\n",
                ):
                    with self.assertRaises(ValueError):
                        live.preview(work, content, SPECIES)
                self.assertEqual(live.get_status(work), old)
                self.assertFalse(live.uploaded_path(work).exists())

    def test_normalization_and_sha_match(self):
        a = "quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n"
        b = "quagsire, MUD_SHOT, AQUA_TAIL, STONE_EDGE\r\n"
        self.assertEqual(live.digest(a), live.digest(b))



    def test_reported_91_92_duplicate_error_and_preview_recovery(self):
        species={f'p{i}':{'fastMoves':['FAST'],'chargedMoves':['CHARGE1','CHARGE2']} for i in range(90)}
        rows=[f'p{i},FAST,CHARGE1,CHARGE2' for i in range(90)]
        content='\n'.join(rows+[rows[0],rows[1]])+'\n'
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,{'PVP_ARCHIVE_DIR':d}):
            work=Path(d)/'work'
            old=live.get_status(work)
            with self.assertRaisesRegex(ValueError,'91行 重複; 92行 重複'):
                live._validated_rows(work,content,species)
            proposal=live.preview(work,content,species)
            self.assertEqual(proposal['input_rows'],92)
            self.assertEqual(proposal['rows'],90)
            self.assertEqual(proposal['duplicate_count'],2)
            self.assertEqual(proposal['duplicate_lines'],[91,92])
            self.assertEqual(live.get_status(work),old)
            saved=live.sync(work,content,species,expected_previous_sha256=old['sha256'],expected_sha256=proposal['sha256'])
            self.assertEqual(saved['rows'],90)
            self.assertEqual(live.active_path(work).read_text(),'\n'.join(rows)+'\n')
            self.assertEqual(saved['sha256'],proposal['sha256'])

    def test_semantic_duplicates_preserve_forms_moves_and_first_occurrence(self):
        content=('Quagsire, MUD_SHOT, AQUA_TAIL, STONE_EDGE\n'
            'quagsire,mud_shot,aqua_tail,stone_edge\n'
            'quagsire_shadow,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n'
            'QUAGSIRE_SHADOW-shadow,mud_shot,aqua_tail,stone_edge\n'
            'quagsire,MUD_SHOT,AQUA_TAIL,MUD_BOMB\n'
            'quagsire,MUD_SHOT,STONE_EDGE,AQUA_TAIL\n')
        proposal=live.normalize_input(content)
        self.assertEqual(proposal['duplicate_count'],2)
        self.assertEqual(proposal['duplicate_lines'],[2,4])
        self.assertEqual(proposal['source_lines'],[1,3,5,6])
        self.assertEqual(proposal['csv'].splitlines()[0],'Quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE')
        self.assertEqual(len(proposal['csv'].splitlines()),4)

    def test_duplicate_cleanup_does_not_hide_bad_rows_and_reports_original_line(self):
        good='quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n'
        content='\n'+good+good+'\nquagsire,MUD_SHOT,BOGUS,STONE_EDGE\n'
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,{'PVP_ARCHIVE_DIR':d}):
            work=Path(d)/'work';old=live.get_status(work)
            with self.assertRaisesRegex(ValueError,'5行 現在のPvPokeデータにない技'):
                live.preview(work,content,SPECIES)
            self.assertEqual(live.get_status(work),old)
            self.assertFalse(live.uploaded_path(work).exists())

    def test_unique_row_and_byte_limits_still_apply_after_cleanup(self):
        good='quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n'
        proposal=live.normalize_input(good*501)
        self.assertEqual(proposal['duplicate_count'],500)
        self.assertEqual(len(proposal['duplicate_lines']),30)
        self.assertEqual(proposal['csv'],good)
        with self.assertRaisesRegex(ValueError,'500'):
            live.normalize_input(''.join(f'p{i},FAST,C1,C2\n' for i in range(501)))
        with self.assertRaisesRegex(ValueError,'80KB'):
            live.normalize_input(good*3000)
        for content in ('', '  \n', 'quagsire,MUD_SHOT,AQUA_TAIL\n'):
            with self.assertRaises(ValueError):live.normalize_input(content)


if __name__ == "__main__":
    unittest.main()
