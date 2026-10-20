import base64
import datetime
import hashlib
import http.client
import io
import json
import os
import struct
import threading
import unittest
import zipfile
from unittest.mock import patch
from http.server import ThreadingHTTPServer

os.environ.setdefault('PVP_API_KEY', 'test-' + 'x' * 32)
from visual_backup import VisualBackup, BackupTokens, BackupError, MODEL, validate_archive

def archive(species='zigzagoon', **changes):
    row={'recordId':'test-1','speciesId':species,'origin':'manual','createdAt':1}
    manifest={'format':'pokemonivreader-visual-backup-v1','model':MODEL,'samples':[row]}
    manifest.update(changes)
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('manifest.json',json.dumps(manifest))
        z.writestr('test-1.jpg',b'\xff\xd8test')
        z.writestr('test-1.vec',struct.pack('>1024f',1,*([0]*1023)))
    return out.getvalue()

class S3Error(Exception):
    def __init__(self,code): self.response={'Error':{'Code':code}}

class MemoryS3:
    def __init__(self): self.objects={}
    def head_object(self,Bucket,Key):
        if Key not in self.objects: raise S3Error('404')
        data,meta=self.objects[Key]
        return {'ETag':'"'+hashlib.md5(data).hexdigest()+'"','ContentLength':len(data),'Metadata':meta,
                'LastModified':datetime.datetime.now(datetime.timezone.utc)}
    def put_object(self,Bucket,Key,Body,Metadata=None,IfMatch=None,IfNoneMatch=None,**kwargs):
        previous=self.head_object(Bucket,Key)['ETag'] if Key in self.objects else ''
        if (IfMatch is not None and IfMatch!=previous) or (IfNoneMatch=='*' and previous): raise S3Error('PreconditionFailed')
        self.objects[Key]=(Body,Metadata or {})
        return self.head_object(Bucket,Key)
    def get_object(self,Bucket,Key):
        result=self.head_object(Bucket,Key);result['Body']=io.BytesIO(self.objects[Key][0]);return result
    def delete_object(self,Bucket,Key): self.objects.pop(Key,None)

class BackupTests(unittest.TestCase):
    def test_upload_download_and_lost_update(self):
        b=VisualBackup(MemoryS3(),'private');data=archive()
        self.assertFalse(b.head()['exists'])
        result=b.upload(data,'');self.assertEqual(result['count'],1)
        self.assertEqual(base64.b64decode(b.download()['archive']),data)
        with self.assertRaises(BackupError) as caught: b.upload(archive('zigzagoon_galarian'),'')
        self.assertEqual(caught.exception.status,409)
        self.assertEqual(b.upload(archive('zigzagoon_galarian'),result['etag'])['count'],1)
    def test_probe_enforces_conditional_writes_and_removes_test_objects(self):
        s3=MemoryS3();b=VisualBackup(s3,'private');b.probe()
        self.assertTrue(b.probe_ok);self.assertFalse(s3.objects)
    def test_invalid_model_and_unconfirmed_samples_cannot_replace_backup(self):
        b=VisualBackup(MemoryS3(),'private');saved=b.upload(archive(),'')
        for data in (b'bad zip',archive(model='other'),archive(samples=[{'recordId':'test-1','speciesId':'zigzagoon','origin':'visual'}])):
            with self.assertRaises(BackupError): b.upload(data,saved['etag'])
        self.assertEqual(b.download()['etag'],saved['etag'])
    def test_traversal_extra_files_bad_vector_and_duplicate_names_are_rejected(self):
        for path,body in [('../escape',b'a'),('extra.jpg',b'a'),('test-1.vec',b'bad'),('test-1.vec',struct.pack('>1024f',float('nan'),*([0]*1023)))]:
            buffer=io.BytesIO(archive())
            with zipfile.ZipFile(buffer,'a') as z: z.writestr(path,body)
            with self.assertRaises(BackupError): validate_archive(buffer.getvalue())
    def test_tokens_tampering_expiry_and_key_rotation(self):
        tokens=BackupTokens('secret');token=tokens.issue()
        self.assertTrue(tokens.valid(token));self.assertFalse(tokens.valid(token+'x'))
        self.assertFalse(BackupTokens('changed').valid(token))
        with patch('visual_backup.time.time',return_value=10**12): self.assertFalse(tokens.valid(token))

class GatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pvpoke_mcp_remote as remote
        cls.remote=remote
        cls.backend=VisualBackup(MemoryS3(),'private')
        cls.patcher=patch.object(remote,'VISUAL_BACKUP',cls.backend);cls.patcher.start()
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),remote.Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.patcher.stop()
    def request(self,path,token='',args=None,cookie=''):
        c=http.client.HTTPConnection(*self.server.server_address)
        c.request('POST',path,json.dumps(args or {}),{'Content-Type':'application/json','Authorization':'Bearer '+token,'Cookie':cookie})
        r=c.getresponse();body=r.read();headers=dict(r.getheaders());c.close();return r.status,body,headers
    def test_only_owner_auth_can_issue_code_and_code_is_backup_scoped(self):
        r=self.remote
        self.assertEqual(self.request('/app-api/visual-backup-token')[0],401)
        status,body,_=self.request('/app-api/visual-backup-token',r.API_KEY)
        self.assertEqual(status,200);token=json.loads(body)['connection'].removeprefix('pivbackup1.')
        self.assertEqual(self.request('/visual-backup/v1/status',token)[0],200)
        for path in ['/mcp','/app-api/catalog','/app-api/visual-backup-token']:
            self.assertEqual(self.request(path,token)[0],401)
        self.assertEqual(self.request('/visual-backup/v1/status',r.API_KEY)[0],401)
    def test_cookie_login_and_archive_roundtrip(self):
        status,_,headers=self.request('/app-api/session',self.remote.API_KEY)
        self.assertEqual(status,200)
        _,body,_=self.request('/app-api/visual-backup-token',cookie=headers['Set-Cookie'])
        token=json.loads(body)['connection'].removeprefix('pivbackup1.')
        status,body,_=self.request('/visual-backup/v1/status',token)
        etag=json.loads(body)['etag'];data=archive()
        self.assertEqual(self.request('/visual-backup/v1/upload',token,{'expectedEtag':etag,'archive':base64.b64encode(data).decode()})[0],200)
        status,body,_=self.request('/visual-backup/v1/download',token)
        self.assertEqual(status,200);self.assertEqual(base64.b64decode(json.loads(body)['archive']),data)

if __name__=='__main__': unittest.main()
