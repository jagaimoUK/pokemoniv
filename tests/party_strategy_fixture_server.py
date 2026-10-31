"""Local browser fixture: real app gateway + worker + bundled engine, no external API."""
import json
import hashlib
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
import pvpoke_meta_live as meta_live
import pvpoke_meta_presets as meta_presets

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
from pvpoke_app_catalog import enrich_catalog
from pvpoke_flashcards import public_catalog
enrich_catalog(catalog, species)
party = PartyBuilder(work)
fixture_rows = json.loads((ROOT/'tests/fixtures/strategy_rows.json').read_text())
party.save_party({'name':'Browser fixture','members':fixture_rows})
meta_rows = fixture_rows + [{'species':'primeape','fast':'COUNTER',
    'charged1':'ICE_PUNCH','charged2':'CLOSE_COMBAT'}]
meta_csv = ''.join(','.join(row[k] for k in
    ('species','fast','charged1','charged2')) + '\n' for row in meta_rows)
meta_live.sync(work, meta_csv, species)
_, alternate_csv, _ = meta_live._validated_upload(work, meta_csv, species)
meta_presets.save(work, {'action':'create', 'revision':meta_presets.listing(work)['revision'],
    'name':'Alternate fixture', 'csv':alternate_csv,
    'expected_sha256':hashlib.sha256(alternate_csv.encode()).hexdigest()}, species)
lock = threading.RLock()
state = {'state':'idle'}
def request(path, payload=None, **kwargs):
    args = payload or {}
    if path == '/api/catalog':return {'ready':True,'species':catalog,'moves':{
        m['moveId']:{'name':m['name'],'name_ja':public_catalog()['moves'].get(m['moveId'],{}).get('ja')}
        for m in gm['moves']}}
    action = path.rsplit('/',1)[-1]
    if action == 'meta-weights':return party.meta_weights(args.get('changes'))
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
gateway.backend.meta_presets = lambda: meta_presets.listing(work)
gateway.backend.export_meta_preset = lambda id, sha: meta_presets.export_preset(work, id, sha)
server=ThreadingHTTPServer(('127.0.0.1',0),gateway.Handler)
gateway.PORT=server.server_port
gateway.APP_ORIGIN=f'http://127.0.0.1:{server.server_port}'
print(json.dumps({'url':gateway.APP_ORIGIN,'key':gateway.API_KEY}),flush=True)
try:server.serve_forever()
finally:server.server_close();workspace.cleanup()
