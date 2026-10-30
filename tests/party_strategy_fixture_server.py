"""Local browser fixture: real app gateway + worker + bundled engine, no external API."""
import json
import os
import re
import sys
import tempfile
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['PVP_ENGINE'] = 'direct'
os.environ['PVP_API_KEY'] = 'fixture-' + 'x'*32
import pvpoke_batch_v2 as engine
import pvpoke_mcp_remote as gateway
from pvpoke_party_backend import PartyBuilder

workspace = tempfile.TemporaryDirectory()
work = Path(workspace.name)
gm = json.loads((ROOT/'tests/fixtures/strategy_gamemaster.json').read_text())
(work/'gamemaster.json').write_text(json.dumps(gm))
js = (ROOT/'vendor/pvpoke/src/js/pokemon/Pokemon.js').read_text()
(work/'Pokemon.js').write_text(js)
engine.DATA = work
cpms = [float(x) for x in re.search(r'var\s+cpms\s*=\s*\[([^\]]+)\]',js,re.S)[1].split(',') if x.strip()]
species = {p['speciesId']:p for p in gm['pokemon']}
catalog = {sid:{'name':p['speciesName'],'fastMoves':p['fastMoves'],'chargedMoves':p['chargedMoves']} for sid,p in species.items()}
party = PartyBuilder(work)
party.save_party({'name':'Browser fixture','members':json.loads((ROOT/'tests/fixtures/strategy_rows.json').read_text())})
lock = threading.RLock()
state = {'state':'idle'}
def request(path, payload=None, **kwargs):
    args = payload or {}
    if path == '/api/catalog':return {'ready':True,'species':catalog}
    action = path.rsplit('/',1)[-1]
    if action == 'list':return party.list_parties()
    if action == 'get':return party.get_party(args['id'])
    if action == 'save':return party.save_party(args)
    if action == 'start':return party.start(args,catalog=catalog,species=species,cpms=cpms,
        engine=engine,work=work,global_lock=lock,global_status=state)
    if action == 'status':return party.run_status(args['job_id'])
    if action == 'cancel':return party.cancel(args['job_id'])
    raise ValueError(path)
gateway.backend._request = request
gateway.backend._token = lambda:'fixture-token'
gateway.backend.meta_presets = lambda:{'items':[{'id':'legacy','name':'Fixture','rows':6,'sha256':'0'*64}], 'default_id':'legacy'}
server=ThreadingHTTPServer(('127.0.0.1',0),gateway.Handler)
gateway.PORT=server.server_port
gateway.APP_ORIGIN=f'http://127.0.0.1:{server.server_port}'
print(json.dumps({'url':gateway.APP_ORIGIN,'key':gateway.API_KEY}),flush=True)
try:server.serve_forever()
finally:server.server_close();workspace.cleanup()
