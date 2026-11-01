import hashlib
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

os.environ.setdefault('PVP_API_KEY', 'test-' + 'x'*32)
import pvpoke_flashcards as fc
import pvpoke_mcp_remote as remote
import pvpoke_meta_variants as variants
import pvpoke_meta_presets as presets
import pvpoke_meta_live as live


class FlashcardTests(unittest.TestCase):
    def test_catalog_and_all_rankings_valid(self):
        d=fc.public_catalog()
        self.assertEqual(len(d['leagues']),3)
        for league in d['leagues']:
            self.assertGreater(len(league['rows']),400)
            for row in league['rows']:
                p=d['species'][row['species']]
                self.assertTrue(all(m in p['fast'] and d['moves'][m]['gain']>0 for m in row['fast']))
                self.assertTrue(all(m in p['charged'] and 0<d['moves'][m]['cost']<=100 for m in row['charged']))
        self.assertIn('ニドクイン', d['species']['nidoqueen']['ja'])
        self.assertEqual(d['moves']['POISON_FANG']['ja'],'どくどくのキバ')

    def test_rows_keep_pairs_and_unlimited_internal_decks(self):
        rows=fc.rows_from_csv('a,F,X,Y\na,G,Y,Z\na,F,X,Z\n')
        self.assertEqual(rows,[{'species':'a','fast':['F'],'charged':['X','Y','Z']},{'species':'a','fast':['G'],'charged':['Y','Z']}])
        text='a,F,X,Y\n'*1500
        self.assertEqual(len(live._parse(text,trusted=True)),1500)
        with self.assertRaises(ValueError):live._parse(text)

    def test_page_is_self_contained_and_has_no_external_frames(self):
        page=fc.page()
        self.assertNotIn('/*CORE*/',page)
        self.assertNotIn('/*UI*/',page)
        self.assertIn("frame-src 'none'",page)
        self.assertNotIn('<iframe',page)
        self.assertNotIn(remote.API_KEY,page)

    def test_meta_metadata_does_not_repeat_backup_csv(self):
        metadata=presets._metadata({'id':'custom:test','name':'x','csv':'a,F,X,Y\n','source_csv':'private original'}, {'favorite_ids':[],'default_id':'legacy'})
        self.assertNotIn('source_csv',metadata)
        self.assertNotIn('csv',metadata)

    def test_variant_ratings_exclude_headers_and_summary_columns(self):
        candidates=[dict(species='a',fast='F',charged1='X',charged2='Y'),dict(species='a',fast='F',charged1='X',charged2='Z'),dict(species='a',fast='F',charged1='Y',charged2='Z')]
        m=[['','one','two','Wins','Losses','Draws','Average'],
           ['a',400,400,99,0,0,999],['b',600,580,1,0,0,0],['c',579,560,1,0,0,0]]
        chosen=variants.choose_variants(candidates,[m]*6,1,['one','two'])
        self.assertEqual(len(chosen),1)
        self.assertEqual(chosen[0][0][-1],'Z')
        self.assertEqual(chosen[0][1],['one','two'])
        self.assertEqual(variants.choose_variants(candidates,[m]*6,1,['same','same']),[])
        m[1][1]=650
        self.assertEqual(variants.choose_variants(candidates,[m]*6,1,['one','two']),[])

    def test_background_compare_and_apply_conflict(self):
        with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,{'PVP_ARCHIVE_DIR':root}):
            work=Path(root);csv='a,F,X,Y\n';job={'id':'legacy','source_sha256':hashlib.sha256(csv.encode()).hexdigest()}
            with patch.object(presets,'resolve',return_value={'sha256':'changed','csv':csv}):
                self.assertFalse(variants.apply(work,job,[('a','F','X','Z')]))
            self.assertFalse(live.uploaded_path(work).exists())
            with patch.object(presets,'resolve',return_value={'sha256':job['source_sha256'],'csv':csv}):
                self.assertTrue(variants.apply(work,job,[('a','F','X','Y'),('a','F','X','Z')]))
            self.assertIn('X,Z',live.uploaded_path(work).read_text())
            self.assertEqual(live.uploaded_path(work).with_suffix('.csv.bak').read_text(),csv)

    def test_interrupted_evaluation_resumes_completed_species(self):
        job={'source_csv':'a,F,X,Y\n','evaluated':{'a':{'species':'a','tested':3,'chosen':[{'row':['a','F','X','Z'],'new_species':['x','y']}]}}}
        class Client:
            def simulate(self,*args):raise AssertionError('completed species must not be recalculated')
        with patch.object(variants,'prepared_rows',return_value=[]):
            rows,evidence,count=variants.evaluate(job,Client(),{},[],threading.Lock(),{'state':'idle'},lambda _:None)
        self.assertEqual(count,1)
        self.assertEqual(rows[-1],('a','F','X','Z'))
        self.assertEqual(job['progress'],1)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.server=ThreadingHTTPServer(('127.0.0.1',0),remote.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
    def req(self,path,data=None,headers=None):
        con=http.client.HTTPConnection(*self.server.server_address)
        con.request('POST' if data is not None else 'GET',path,json.dumps(data) if data is not None else None,headers or {})
        r=con.getresponse();result=(r.status,r.read(),dict(r.getheaders()));con.close();return result
    def test_public_etag_and_page(self):
        status,body,headers=self.req('/reader-api/v1/flashcards');self.assertEqual(status,200)
        self.assertNotIn('source_csv',body.decode())
        self.assertEqual(self.req('/reader-api/v1/flashcards',headers={'If-None-Match':headers['ETag']})[0],304)
        self.assertEqual(self.req('/flashcards')[0],200)
    def test_private_meta_auth_and_origin(self):
        self.assertEqual(self.req('/app-api/flashcards',{}, {'Content-Type':'application/json'})[0],401)
        h={'Content-Type':'application/json','Authorization':'Bearer '+remote.API_KEY,'Origin':'https://invalid.example'}
        self.assertEqual(self.req('/app-api/flashcards',{},h)[0],403)
        h['Origin']=remote.APP_ORIGIN
        with patch.object(remote.backend,'_request',return_value={'decks':[{'id':'private'}]}) as request,patch.object(remote.backend,'_token',return_value='local'):
            self.assertEqual(self.req('/app-api/flashcards',{},h)[0],200)
            request.assert_called_once_with('/api/flashcards',headers={'X-PvPoke-Token':'local'})

if __name__=='__main__':unittest.main()
