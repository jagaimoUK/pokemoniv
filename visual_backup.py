"""Owner-scoped visual reference backup; S3 settings are provider-neutral for R2 migration."""
import base64
import hashlib
import hmac
import io
import json
import logging
import os
import secrets
import struct
import threading
import time
import zipfile
from pvpoke_auth_store import CredentialStore

MAX_ARCHIVE = 16 * 1024 * 1024
MODEL = 'mobilenet-v3-small-1-letterbox-10-12-90-36-v1'

class BackupError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status

class BackupTokens:
    def __init__(self, key, store=None):
        self.key = hashlib.sha256(('visual-backup-v1:' + key).encode()).digest()
        self.store = store or CredentialStore()
    def issue(self):
        payload = 'vb1.%s.%s' % (int(time.time()) + 365 * 86400, secrets.token_urlsafe(18))
        signature = hmac.new(self.key, payload.encode(), hashlib.sha256).hexdigest()
        token = payload + '.' + signature
        self.store.active(token, 'backup', int(payload.split('.')[1]))
        return token
    def valid(self, token):
        try:
            if not isinstance(token, str) or len(token) > 300 or not token.isascii():
                return False
            version, expires, nonce, signature = token.split('.')
            if version != 'vb1' or len(nonce) != 24 or not time.time() < int(expires) <= time.time() + 366*86400:
                return False
            payload = '.'.join((version, expires, nonce))
            return (hmac.compare_digest(hmac.new(self.key, payload.encode(), hashlib.sha256).hexdigest(), signature)
                    and self.store.active(token, 'backup', int(expires)))
        except (ValueError, TypeError):
            return False

def validate_archive(data):
    import re
    if not 0 < len(data) <= MAX_ARCHIVE:
        raise BackupError('バックアップの容量上限は16MBです', 413)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            rows = archive.infolist()
            names = [r.filename for r in rows]
            if len(rows) > 1025 or len(set(names)) != len(names) or sum(r.file_size for r in rows) > 32*1024*1024:
                raise ValueError()
            if any(r.flag_bits & 1 or r.file_size > 256*1024 or not re.fullmatch(r'(manifest\.json|[A-Za-z0-9_-]{1,80}\.(jpg|vec))', r.filename) for r in rows):
                raise ValueError()
            manifest = json.loads(archive.read('manifest.json'))
            if manifest.get('format') != 'pokemonivreader-visual-backup-v1' or manifest.get('model') != MODEL:
                raise ValueError()
            samples = manifest['samples']
            if not isinstance(samples, list) or len(samples) > 512:
                raise ValueError()
            expected = {'manifest.json'}
            seen, forms = set(), {}
            for sample in samples:
                rid, species = sample['recordId'], sample['speciesId']
                if not re.fullmatch('[A-Za-z0-9_-]{1,80}', rid) or rid in seen or not isinstance(species, str) or not 0 < len(species) <= 100 or sample['origin'] not in ('manual','types'):
                    raise ValueError()
                seen.add(rid)
                forms[species] = forms.get(species, 0) + 1
                if forms[species] > 24:
                    raise ValueError()
                image = archive.read(rid + '.jpg')
                vector = archive.read(rid + '.vec')
                if not image.startswith(b'\xff\xd8') or len(vector) != 4096:
                    raise ValueError()
                import math
                values = struct.unpack('>1024f', vector)
                if not all(math.isfinite(v) for v in values) or sum(v*v for v in values) < 1e-9:
                    raise ValueError()
                expected.update((rid+'.jpg', rid+'.vec'))
            if set(names) != expected:
                raise ValueError()
            return len(samples)
    except (ValueError, KeyError, TypeError, AttributeError, zipfile.BadZipFile, RuntimeError, OSError, struct.error) as exc:
        raise BackupError('見本バックアップの形式を確認できません') from exc

class VisualBackup:
    def __init__(self, client=None, bucket=None):
        self.bucket = bucket or os.getenv('VISUAL_BACKUP_S3_BUCKET', '')
        self.key = 'visual-memory/v1/owner/latest.zip'
        self.lock = threading.Lock()
        self.client = client
        self.probe_ok = False
        if client is None and self.bucket:
            import boto3
            from botocore.config import Config
            endpoint = os.environ['VISUAL_BACKUP_S3_ENDPOINT']
            if not endpoint.startswith('https://'):
                raise ValueError('Backup storage must use HTTPS')
            self.client = boto3.client('s3', endpoint_url=endpoint,
                region_name=os.getenv('VISUAL_BACKUP_S3_REGION', 'auto'),
                aws_access_key_id=os.environ['VISUAL_BACKUP_S3_ACCESS_KEY_ID'],
                aws_secret_access_key=os.environ['VISUAL_BACKUP_S3_SECRET_ACCESS_KEY'],
                config=Config(signature_version='s3v4', connect_timeout=10, read_timeout=30,
                    retries={'max_attempts': 2}, s3={'addressing_style': os.getenv('VISUAL_BACKUP_S3_STYLE','virtual')}))
    @property
    def enabled(self):
        return self.client is not None and bool(self.bucket)
    def require(self):
        if not self.enabled:
            raise BackupError('見本のクラウド保存は未設定です', 503)
    def head(self):
        self.require()
        try:
            row = self.client.head_object(Bucket=self.bucket, Key=self.key)
            return {'exists': True, 'etag': row['ETag'], 'bytes': row['ContentLength'],
                'count': int(row.get('Metadata',{}).get('samples','0')),
                'updatedAt': row['LastModified'].isoformat()}
        except Exception as exc:
            if getattr(exc,'response',{}).get('Error',{}).get('Code') in ('404','NoSuchKey','NotFound'):
                return {'exists': False, 'etag':'', 'count':0}
            raise
    def upload(self, data, expected):
        self.require()
        count = validate_archive(data)
        if not isinstance(expected,str) or len(expected)>200:
            raise BackupError('保存前の更新確認が必要です',409)
        with self.lock:
            if self.head()['etag'] != expected:
                raise BackupError('別の端末から更新されています。先に復元してください',409)
            condition = {'IfMatch':expected} if expected else {'IfNoneMatch':'*'}
            try:
                row = self.client.put_object(Bucket=self.bucket,Key=self.key,Body=data,
                    ContentType='application/zip',Metadata={'samples':str(count),'format':'v1'},**condition)
            except Exception as exc:
                if str(getattr(exc,'response',{}).get('Error',{}).get('Code')) in ('412','PreconditionFailed','ConditionalRequestConflict'):
                    raise BackupError('保存先が更新されました。先に復元してください',409) from exc
                raise
            return {'etag':row['ETag'],'count':count,'sha256':hashlib.sha256(data).hexdigest()}
    def download(self):
        self.require()
        try:
            row = self.client.get_object(Bucket=self.bucket,Key=self.key)
        except Exception as exc:
            if getattr(exc,'response',{}).get('Error',{}).get('Code') in ('404','NoSuchKey','NotFound'):
                raise BackupError('保存された見本はまだありません',404) from exc
            raise
        stream = row['Body']
        try:
            data=stream.read(MAX_ARCHIVE+1)
        finally:
            stream.close()
        validate_archive(data)
        return {'archive':base64.b64encode(data).decode(),'etag':row['ETag'],'sha256':hashlib.sha256(data).hexdigest()}
    def probe(self):
        if not self.enabled:
            return
        key='visual-memory/v1/_probe/'+secrets.token_hex(12)
        try:
            value=b'pokemonivreader-backup-probe-v1'
            created=self.client.put_object(Bucket=self.bucket,Key=key,Body=b'initial',IfNoneMatch='*')
            self.client.put_object(Bucket=self.bucket,Key=key,Body=value,IfMatch=created['ETag'])
            try:
                self.client.put_object(Bucket=self.bucket,Key=key,Body=b'stale',IfMatch=created['ETag'])
            except Exception as exc:
                if str(getattr(exc,'response',{}).get('Error',{}).get('Code')) not in ('412','PreconditionFailed','ConditionalRequestConflict'):
                    raise
            else:
                raise ValueError('storage does not enforce conditional updates')
            result=self.client.get_object(Bucket=self.bucket,Key=key)
            try:
                self.probe_ok=result['Body'].read()==value
            finally:
                result['Body'].close()
            if not self.probe_ok:
                raise ValueError('probe mismatch')
        except Exception as exc:
            logging.warning('Visual backup storage probe failed: %s',type(exc).__name__)
        finally:
            try:
                self.client.delete_object(Bucket=self.bucket,Key=key)
            except Exception:
                self.probe_ok=False
        if self.probe_ok:
            logging.warning('Visual backup storage probe: PASS (conditional put/get/delete)')

BACKUP_HTML='''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>見本バックアップの接続</title><style>body{font:17px sans-serif;max-width:34rem;margin:3rem auto;padding:1rem;background:#f2f5f1;color:#25352b}button,input,textarea{font:inherit;padding:.8rem;border-radius:18px;border:1px solid #9cab9e;margin:.4rem 0;max-width:100%;box-sizing:border-box}textarea{width:100%;height:9rem}button{background:#dce9da}p{line-height:1.7}</style><h1>見本バックアップの接続</h1><p>このサーバーの所有者用バックアップです。画像の見本だけを非公開で保存します。接続コードは他の人に渡さないでください。</p><button id="issue">接続コードを発行</button><section id="login" hidden><p>厳選Webアプリと同じ接続キーでログインしてください。一度ログインすればブラウザーで記憶されます。</p><input id="key" type="password" autocomplete="off" placeholder="接続キー"><button id="signin">ログイン</button></section><p id="msg"></p><section id="result" hidden><p>コードをコピーし、読み取りアプリの「見本のクラウド保存」で貼り付けてください。</p><textarea id="code" readonly></textarea><button id="copy">接続コードをコピー</button></section><h2>接続コードの管理</h2><p>この更新後に発行、または使用されたコードを表示します。旧コードは使用後に一覧へ現れます。コードごとに失効でき、見本データは残ります。</p><button id="connections">接続一覧を更新</button><section id="connectionList"></section><script>
async function call(path,data={},key=''){const h={'Content-Type':'application/json'};if(key)h.Authorization='Bearer '+key;const r=await fetch('/app-api/'+path,{method:'POST',headers:h,credentials:'same-origin',body:JSON.stringify(data)});if(r.status===401){document.querySelector('#login').hidden=false;throw Error('ログインが必要です');}const x=await r.json();if(!r.ok)throw Error(x.error||'接続できません');return x;}
async function issue(){try{const x=await call('visual-backup-token');document.querySelector('#code').value=x.connection;document.querySelector('#result').hidden=false;document.querySelector('#msg').textContent='接続コードを発行しました';await connections();}catch(e){document.querySelector('#msg').textContent=e.message;}}
async function connections(){try{const x=await call('visual-backup-connections');const root=document.querySelector('#connectionList');root.replaceChildren();for(const item of x.items){const row=document.createElement('p');const label=document.createElement('span');label.textContent=new Date(item.created*1000).toLocaleString()+' / '+item.id.slice(0,12)+' ';const revoke=document.createElement('button');revoke.textContent='この接続を失効';revoke.onclick=async()=>{try{await call('visual-backup-revoke',{id:item.id});await connections();document.querySelector('#msg').textContent='接続を失効しました。再接続する端末には新しいコードを発行してください';}catch(e){document.querySelector('#msg').textContent=e.message;}};row.append(label,revoke);root.append(row);}}catch(e){document.querySelector('#msg').textContent=e.message;}}
document.querySelector('#connections').onclick=connections;document.querySelector('#issue').onclick=issue;document.querySelector('#signin').onclick=async()=>{try{await call('session',{},document.querySelector('#key').value);document.querySelector('#key').value='';document.querySelector('#login').hidden=true;await issue();}catch(e){document.querySelector('#msg').textContent=e.message;}};document.querySelector('#copy').onclick=async()=>{try{await navigator.clipboard.writeText(document.querySelector('#code').value);document.querySelector('#msg').textContent='コピーしました。読み取りアプリに戻って貼り付けてください';}catch(e){document.querySelector('#code').select();}};
</script></html>'''
