"""Persistent presets, failure atomicity, legacy compatibility and run isolation."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pvpoke_meta_live as live
import pvpoke_meta_presets as presets
from test_pvpoke_meta_live import SPECIES

CSV = 'quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n'
CSV2 = 'quagsire,MUD_SHOT,AQUA_TAIL,MUD_BOMB\n'


class MetaPresetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name) / 'work'
        self.env = patch.dict(os.environ, {'PVP_ARCHIVE_DIR': self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_update_compact_and_conflict_keep_manual_rows(self):
        made=self.create();pid=made['saved_id']
        entry=presets.resolve(self.work,pid)
        content=CSV+CSV2
        result=presets.save(self.work,{'action':'update','id':pid,'revision':made['revision'],
            'expected_previous_sha256':entry['sha256'], 'csv':content,
            'expected_sha256':live.digest(content)},SPECIES)
        self.assertEqual(presets.resolve(self.work,pid)['source_csv'],content)
        self.assertTrue(presets.store_path(self.work).with_suffix('.json.bak').exists())
        with self.assertRaises(ValueError):
            presets.save(self.work,{'action':'update','id':pid,'revision':result['revision'],
                'expected_previous_sha256':entry['sha256'],'csv':CSV},SPECIES)
        obj=presets._read(self.work);obj['items'][0]['csv']=content+CSV2
        presets._write(self.work,obj)
        current=presets.resolve(self.work,pid)
        presets.save(self.work,{'action':'compact','id':pid,'revision':obj['revision'],
            'expected_previous_sha256':current['sha256']},SPECIES)
        self.assertEqual(presets.resolve(self.work,pid)['csv'],content)
        exported=presets.export_preset(self.work,pid,presets.resolve(self.work,pid)['sha256'])
        self.assertEqual(exported['manual_csv'],content)

    def create(self, name='日常用', csv=CSV, revision=None):
        if revision is None:
            revision = presets.listing(self.work)['revision']
        return presets.save(self.work, {'action': 'create', 'name': name,
            'csv': csv, 'revision': revision, 'expected_sha256': live.digest(csv)}, SPECIES)

    def test_first_load_preserves_legacy_and_never_creates_store(self):
        live.sync(self.work, CSV, SPECIES)
        state = presets.listing(self.work)
        self.assertEqual(state['default_id'], 'legacy')
        self.assertEqual(state['items'][0]['sha256'], live.digest(CSV))
        self.assertFalse(presets.store_path(self.work).exists())
        self.assertIn('pvpoke:fantasy', [p['id'] for p in state['items']])

    def test_multiple_saves_survive_restart_without_overwriting_legacy(self):
        live.sync(self.work, CSV, SPECIES)
        a = self.create()
        b = self.create('大会用', CSV2)
        self.assertNotEqual(a['saved_id'], b['saved_id'])
        presets.bundled.cache_clear()
        self.assertEqual(presets.resolve(self.work, a['saved_id'])['csv'], CSV)
        self.assertEqual(presets.resolve(self.work, b['saved_id'])['csv'], CSV2)
        self.assertEqual(live.active_path(self.work).read_text(), CSV)
        self.assertEqual(presets.listing(self.work)['revision'], 2)

    def test_default_and_favorite_persist_independently(self):
        state = self.create()
        id_ = state['saved_id']
        state = presets.save(self.work, {'action': 'default','id': id_, 'revision':1}, SPECIES)
        state = presets.save(self.work, {'action': 'favorite','id': 'pvpoke:fantasy',
            'favorite': True, 'revision':state['revision']}, SPECIES)
        self.assertEqual(presets.listing(self.work)['default_id'], id_)
        self.assertTrue(presets.resolve(self.work, 'pvpoke:fantasy')['favorite'])
        presets.save(self.work, {'action':'favorite','id':'pvpoke:fantasy',
            'favorite':False,'revision':state['revision']}, SPECIES)
        self.assertFalse(presets.resolve(self.work,'pvpoke:fantasy')['favorite'])

    def test_stale_revision_and_bad_hash_do_not_change_data(self):
        self.create()
        before = presets.store_path(self.work).read_bytes()
        with self.assertRaisesRegex(ValueError, '別の画面'):
            self.create('古い画面', revision=0)
        with self.assertRaisesRegex(ValueError, 'プレビュー'):
            presets.save(self.work, {'action':'create','name':'不一致','csv':CSV,
                'revision':1,'expected_sha256':'0'*64}, SPECIES)
        self.assertEqual(presets.store_path(self.work).read_bytes(), before)

    def test_invalid_csv_and_duplicate_names_preserve_store(self):
        self.create()
        before = presets.store_path(self.work).read_bytes()
        for name, csv in [('日常用',CSV), ('x'*61,CSV),('',CSV),
                ('不正','quagsire,BOGUS,AQUA_TAIL,STONE_EDGE\n')]:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.create(name,csv)
        self.assertEqual(presets.store_path(self.work).read_bytes(), before)

    def test_atomic_replace_failure_keeps_previous_revision(self):
        self.create()
        before = presets.store_path(self.work).read_bytes()
        original = os.replace
        def fail_live(src, dest):
            if Path(dest) == presets.store_path(self.work):
                raise OSError('disk full')
            return original(src,dest)
        with patch.object(presets.os, 'replace', side_effect=fail_live):
            with self.assertRaises(OSError):
                self.create('保存失敗', CSV2)
        self.assertEqual(presets.store_path(self.work).read_bytes(), before)
        self.assertEqual(presets.store_path(self.work).with_suffix('.json.bak').read_bytes(), before)
        self.assertFalse(list(presets.store_path(self.work).parent.glob('*.tmp')))

    def test_corrupt_store_is_not_silently_reset(self):
        self.create()
        presets.store_path(self.work).write_text('{broken')
        with self.assertRaisesRegex(ValueError, 'バックアップ'):
            presets.listing(self.work)
        self.assertEqual(presets.store_path(self.work).read_text(), '{broken')

    def test_snapshots_are_immutable_and_do_not_switch_shared_legacy(self):
        live.sync(self.work, CSV, SPECIES)
        entry = self.create('別のメタ',CSV2)
        id_ = entry['saved_id']
        path, info = presets.snapshot(self.work,id_,SPECIES,live.digest(CSV2))
        self.assertEqual(info['id'],id_)
        self.assertEqual(path.read_text(),CSV2)
        live.sync(self.work, CSV2, SPECIES)
        self.assertEqual(path.read_text(),CSV2)
        self.assertEqual(presets.snapshot(self.work,id_,SPECIES)[0],path)
        with self.assertRaisesRegex(ValueError,'更新'):
            presets.snapshot(self.work,id_,SPECIES,'0'*64)
        path.write_text(CSV)
        with self.assertRaisesRegex(ValueError,'一致'):
            presets.snapshot(self.work,id_,SPECIES)

    def test_unknown_and_unavailable_presets_are_rejected(self):
        with self.assertRaises(ValueError):
            presets.resolve(self.work,'../../etc/passwd')
        with self.assertRaisesRegex(ValueError,'通常技'):
            presets.snapshot(self.work,'pvpoke:spectral',SPECIES)
        with self.assertRaises(ValueError):
            presets.save(self.work,{'action':'favorite','id':'pvpoke:fantasy',
                'revision':0,'favorite':'yes'},SPECIES)

    def test_custom_limit_with_maximum_rows(self):
        # 500 valid distinct move sets: cheap validation stub isolates store capacity.
        many=''.join(f'pokemon{i},FAST,CHARGE1,CHARGE2\n' for i in range(500))
        with patch.object(live, '_validated_rows', return_value=([],many)):
            for i in range(presets.MAX_CUSTOM):
                state=self.create(str(i),many)
        self.assertEqual(len([p for p in state['items'] if p['source']=='custom']),50)
        with self.assertRaisesRegex(ValueError,'最大50'):
            self.create('51件目')
        self.assertEqual(presets.listing(self.work)['revision'],50)

    def test_full_snapshot_validation_rejects_missing_species(self):
        state=self.create()
        with self.assertRaises(ValueError):
            presets.snapshot(self.work,state['saved_id'],{})


    def test_export_preserves_moves_order_and_shadow_damage_marker(self):
        content=('quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n'
                 'quagsire_shadow,MUD_SHOT,AQUA_TAIL,MUD_BOMB\n'
                 'quagsire_shadow-shadow,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n')
        with patch.object(presets.live,'active_path') as path:
            path.return_value.read_text.return_value=content
            result=presets.export_preset(self.work,'legacy',live.digest(content))
        self.assertEqual(result['csv'],content.replace('quagsire_shadow,','quagsire_shadow-shadow,').rstrip('\n'))
        self.assertEqual(result['rows'],3)
        self.assertEqual(len(result['parts']),1)
        self.assertFalse(presets.store_path(self.work).exists())

    def test_export_large_preset_never_drops_rows(self):
        for count in (1,100,101,500):
            with self.subTest(count=count):
                content=''.join(f'pokemon{i},FAST,CHARGE1,CHARGE2\n' for i in range(count))
                with patch.object(presets.live,'active_path') as path:
                    path.return_value.read_text.return_value=content
                    result=presets.export_preset(self.work,'legacy',live.digest(content))
                self.assertEqual(result['rows'],count)
                self.assertEqual('\n'.join(p['csv'] for p in result['parts']),result['csv'])
                self.assertTrue(all(len(p['csv'].splitlines())<=100 for p in result['parts']))
                self.assertEqual(result['parts'][-1]['end'],count)

    def test_export_unknown_unavailable_or_changed_meta_fails(self):
        for id_,sha in [('missing','a'*64),('pvpoke:spectral','a'*64),('legacy','0'*64),('legacy',None)]:
            with self.subTest(id=id_):
                with self.assertRaises(ValueError):presets.export_preset(self.work,id_,sha)

    def test_export_custom_and_official_without_rewriting_settings(self):
        saved=self.create();id_=saved['saved_id'];before=presets.store_path(self.work).read_bytes()
        result=presets.export_preset(self.work,id_,live.digest(CSV))
        self.assertEqual(result['csv'],CSV.rstrip('\n'))
        fantasy=presets.resolve(self.work,'pvpoke:fantasy')
        exported=presets.export_preset(self.work,'pvpoke:fantasy',fantasy['sha256'])
        self.assertEqual(exported['rows'],27)
        self.assertIn('forretress_shadow-shadow,',exported['csv'])
        self.assertEqual(presets.store_path(self.work).read_bytes(),before)


    def test_named_preset_creation_uses_the_same_deduplicated_preview(self):
        content=CSV+CSV2+CSV
        proposal=live.preview(self.work,content,SPECIES)
        before=live.get_status(self.work)
        saved=presets.save(self.work,{'action':'create','name':'貼り付けテスト','csv':content,
            'revision':0,'expected_sha256':proposal['sha256']},SPECIES)
        entry=presets.resolve(self.work,saved['saved_id'])
        self.assertEqual(entry['csv'],CSV+CSV2)
        self.assertEqual(entry['sha256'],proposal['sha256'])
        self.assertEqual(saved['duplicate_count'],1)
        self.assertEqual(live.get_status(self.work),before)
        self.assertEqual(presets.listing(self.work)['default_id'],'legacy')

    def test_changed_paste_is_rejected_without_mutating_store(self):
        self.create();before=presets.store_path(self.work).read_bytes()
        proposal=live.preview(self.work,CSV+CSV,SPECIES)
        with self.assertRaisesRegex(ValueError,'プレビュー'):
            presets.save(self.work,{'action':'create','name':'書換えテスト','csv':CSV2+CSV2,
                'revision':1,'expected_sha256':proposal['sha256']},SPECIES)
        self.assertEqual(presets.store_path(self.work).read_bytes(),before)
