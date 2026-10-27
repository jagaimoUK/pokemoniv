"""Real HTTP routing of selected metas into a pinned background job."""
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import pvpoke_bridge_core as bridge
import pvpoke_web as web
import pvpoke_meta_presets as presets
from pvpoke_iv_workflow import IVWorkflow
from test_iv_workflow import CANDIDATE, IVS, HASH, FakeBackend
from test_pvpoke_meta_live import SPECIES

CSV='quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n'


class PresetHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.work=Path(self.tmp.name)
        self.patches=[patch.dict(os.environ,{'PVP_ARCHIVE_DIR':self.tmp.name}),
            patch.object(web,'WORK',self.work),patch.object(web,'BATCH_CONFIG',self.work/'input.json'),
            patch.dict(web.CATALOG,{'ready':True,'species':SPECIES}),
            patch.dict(web.STATUS,{'state':'idle'})]
        for p in self.patches:p.start()
        self.server=ThreadingHTTPServer(('127.0.0.1',0),web.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()

    def req(self,path,data=None,token=True):
        c=http.client.HTTPConnection(*self.server.server_address)
        headers={'Content-Type':'application/json'}
        if token:headers['X-PvPoke-Token']=web.TOKEN
        c.request('GET' if data is None else 'POST',path,None if data is None else json.dumps(data),headers)
        r=c.getresponse();body=r.read();c.close();return r.status,json.loads(body)

    def create(self):
        return self.req('/api/meta/presets',{'action':'create','name':'日常','csv':CSV,
            'expected_sha256':presets.live.digest(CSV),'revision':0})[1]

    def test_list_save_and_unknown_id_http_errors(self):
        status,body=self.req('/api/meta/presets');self.assertEqual(status,200)
        self.assertEqual(body['default_id'],'legacy')
        self.assertEqual(self.req('/api/meta/presets',{},token=False)[0],403)
        saved=self.create();id_=saved['saved_id']
        self.assertEqual(self.req('/api/meta/preset?id='+id_)[1]['name'],'日常')
        self.assertEqual(self.req('/api/meta/preset?id=missing')[0],400)
        self.assertEqual(self.req('/api/meta/preset')[0],400)
        self.assertEqual(self.req('/api/meta/presets',{'action':'default','id':id_,'revision':0})[0],400)

    def test_run_uses_chosen_immutable_file_and_checks_hash_under_lock(self):
        saved=self.create();id_=saved['saved_id'];checksum=presets.resolve(self.work,id_)['sha256']
        args={'candidate':CANDIDATE,'ivs':IVS,'meta_preset_id':id_,'expected_meta_sha256':'0'*64}
        with patch.object(web,'background_run') as worker:
            status,body=self.req('/api/run24',args)
            self.assertEqual(status,400);worker.assert_not_called()
            args['expected_meta_sha256']=checksum
            status,body=self.req('/api/run24',args)
            self.assertEqual(status,200,body)
            self.assertEqual(body['preview']['opponent_count'],1)
            self.assertEqual(body['preview']['meta_preset']['id'],id_)
            file=worker.call_args.args[3]
            self.assertEqual(file.read_text(),CSV)
            self.assertIn('meta_snapshots',str(file))
            self.assertEqual(self.req('/api/meta/presets',{'action':'default','id':id_,'revision':1})[0],409)

    def test_bridge_requests_encode_id_and_forward_bound_hash(self):
        saved=self.create();id_=saved['saved_id']
        with patch.object(bridge,'BASE','http://127.0.0.1:'+str(self.server.server_port)):
            self.assertEqual(bridge.meta_preset_status(id_)['id'],id_)
            with patch.object(web,'background_run'):
                started=bridge.start24(CANDIDATE,IVS,'simple',meta_preset_id=id_,
                    expected_meta_sha256=presets.live.digest(CSV))
                self.assertEqual(started['preview']['opponent_count'],1)


class PresetWorkflowTests(unittest.TestCase):
    def test_selected_meta_overrides_global_status_and_is_kept_in_ticket(self):
        backend=FakeBackend();backend.meta_preset_status=lambda id_:{'id':id_,'name':'Fantasy','sha256':HASH}
        original=backend.start24
        seen={}
        def start(*args,**kwargs):
            seen.update(kwargs);return original(*args)
        backend.start24=start
        backend.sha='b'*64
        runner=IVWorkflow(backend)
        result=runner.run(CANDIDATE,IVS,meta_preset_id='pvpoke:fantasy',expected_meta_sha256=HASH,wait_seconds=0)
        self.assertEqual(seen,{'meta_preset_id':'pvpoke:fantasy','expected_meta_sha256':HASH})
        self.assertEqual(runner._ticket['meta_preset']['name'],'Fantasy')
        with self.assertRaisesRegex(ValueError,'SHA256'):
            backend.state='idle';runner.run(CANDIDATE,IVS,meta_preset_id='pvpoke:fantasy',expected_meta_sha256='0'*64)
