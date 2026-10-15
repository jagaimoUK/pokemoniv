#!/usr/bin/env python3
"""Authenticated cloud prototype for PvPoke: single user, single worker.
Test protocol compliance with real ChatGPT MCP client before relying on it.
Not a hardened multi-tenant production service.
"""
import json
import logging
import os
import hmac
from urllib.parse import urlparse
import jwt
from jwt import PyJWKClient, InvalidTokenError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pvpoke_bridge_core as backend
from pvpoke_iv_workflow import IVWorkflow
from pvpoke_app_ui import HTML as APP_HTML
from pvpoke_app_access import AppAccess
from pvpoke_app_input import parse_import

APP_ACCESS = AppAccess()

IV_RUNNER = IVWorkflow(backend)

HOST, PORT = '0.0.0.0', int(os.environ.get('PORT', '8787'))
API_KEY = os.environ.get('PVP_API_KEY', '')
if len(API_KEY) < 32:
    raise SystemExit('PVP_API_KEY must be set to a random value at least 32 characters long')
ALLOWED_ORIGINS = {'https://chatgpt.com', 'https://chat.openai.com', f'http://127.0.0.1:{PORT}', f'http://localhost:{PORT}'}
VERSION = '2025-06-18'
# OAuth is enabled only when the authenticated user's Auth0 tenant is configured.
MCP_URL = os.environ.get('PVP_MCP_URL', 'https://pokemoniv-production.up.railway.app/mcp').rstrip('/')
APP_ORIGIN = '{0.scheme}://{0.netloc}'.format(urlparse(MCP_URL))
ALLOWED_ORIGINS.add(APP_ORIGIN)
AUTH0_ISSUER_RAW = os.environ.get('AUTH0_ISSUER', '').strip().rstrip('/')
AUTH0_ISSUER = AUTH0_ISSUER_RAW + '/' if AUTH0_ISSUER_RAW else ''
JWT_AUDIENCE = os.environ.get('JWT_AUDIENCE', MCP_URL).strip()
AUTH0_ALLOWED_SUB = os.environ.get('AUTH0_ALLOWED_SUB', '').strip()
OAUTH_SCOPE = os.environ.get('PVP_OAUTH_SCOPE', 'openid').strip()
AUTH0_ENABLED = bool(AUTH0_ISSUER)
if AUTH0_ENABLED:
    if not AUTH0_ISSUER.startswith('https://'):
        raise SystemExit('AUTH0_ISSUER must begin with https://')
    if not AUTH0_ALLOWED_SUB:
        raise SystemExit('Set AUTH0_ALLOWED_SUB to your Auth0 user ID before enabling OAuth')
    if not MCP_URL.startswith('https://'):
        raise SystemExit('PVP_MCP_URL must use HTTPS')
    JWKS = PyJWKClient(AUTH0_ISSUER + '.well-known/jwks.json', cache_keys=True, timeout=5)


def oauth_token_valid(raw):
    if not AUTH0_ENABLED or not raw.startswith('Bearer '):
        return False
    token = raw[7:]
    try:
        key = JWKS.get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key.key, algorithms=['RS256'],
                            audience=JWT_AUDIENCE, issuer=AUTH0_ISSUER,
                            options={'require': ['iss', 'aud', 'exp', 'sub']}, leeway=15)
        if not hmac.compare_digest(str(claims.get('sub', '')), AUTH0_ALLOWED_SUB):
            return False
        if OAUTH_SCOPE:
            scopes = set(str(claims.get('scope', '')).split())
            permissions = claims.get('permissions', [])
            if not isinstance(permissions, list):
                permissions = []
            if OAUTH_SCOPE not in (scopes | set(str(x) for x in permissions)):
                return False
        return True
    except (InvalidTokenError, ValueError, KeyError, OSError) as exc:
        logging.warning('OAuth token rejected: %s', type(exc).__name__)
        return False
    except Exception as exc:
        logging.warning('OAuth authentication unavailable: %s', type(exc).__name__)
        return False


POKEMON = {
    'type': 'object',
    'properties': {
        'species': {'type': 'string', 'description': 'PvPoke species ID, e.g. azumarill'},
        'fast': {'type': 'string', 'description': 'PvPoke fast move ID'},
        'charged1': {'type': 'string', 'description': 'PvPoke charged move ID'},
        'charged2': {'type': 'string', 'description': 'PvPoke charged move ID'},
    },
    'required': ['species', 'fast', 'charged1', 'charged2'],
}
OPPONENT = {
    'type': 'object',
    'properties': {
        **POKEMON['properties'],
        'atk': {'type': 'integer', 'minimum': 0, 'maximum': 15},
        'def': {'type': 'integer', 'minimum': 0, 'maximum': 15},
        'hp': {'type': 'integer', 'minimum': 0, 'maximum': 15},
        'iv_mode': {'type': 'string', 'enum': ['inherit', 'source', 'custom', 'default', 'rank1', 'attack', 'defense'],
                    'description': 'Explicit manual source/custom IVs, individual automatic mode, or inherit the global automatic setting.'},
        'source_ivs': {'type': 'object', 'properties': {
            'atk': {'type': 'integer', 'minimum': 0, 'maximum': 15},
            'def': {'type': 'integer', 'minimum': 0, 'maximum': 15},
            'hp': {'type': 'integer', 'minimum': 0, 'maximum': 15}},
            'required': ['atk', 'def', 'hp'],
            'description': 'Passive original IVs kept for iv_mode=source, never selected automatically.'},
    },
    'required': POKEMON['required'],
}
PREP = {
    'type': 'object',
    'properties': {
        'candidate': POKEMON,
        'ivs': {'type': 'string', 'description': 'One ATK,DEF,HP triplet per line, e.g. 0,15,15\\n1,15,14'},
        'opponents': {'type': 'array', 'items': OPPONENT, 'minItems': 1},
        'shields': {'type': 'string', 'enum': ['all', 'equal', 'disadvantage'], 'default': 'all'},
        'opponent_iv_mode': {'type': 'string', 'enum': ['default', 'rank1', 'attack', 'defense'],
                             'default': 'default',
                             'description': 'Four automatic opponent IV modes. Overrides any present IVs unless a row explicitly selects iv_mode=source or custom.'},
    },
    'required': ['candidate', 'ivs', 'opponents'],
}
TOOLS = [
    {'name': 'get_catalog', 'description': 'Get currently available Pokemon presets and dataset status.',
     'inputSchema': {'type': 'object', 'properties': {}}},
    {'name': 'get_meta_status', 'description': 'Show currently active curated meta snapshot row count and SHA256. Before each batch compare to the current ChatGPT Project source.',
     'inputSchema': {'type': 'object', 'properties': {}}},
    {'name': 'sync_meta_opponents', 'description': 'Persist an updated, validated four-column curated opponent list from the ChatGPT Project file. Preserve rows/order/moves, call only when hash differs and no calculation is running.',
     'inputSchema': {'type': 'object', 'properties': {
         'csv_text': {'type': 'string', 'minLength': 1, 'maxLength': 80000,
                      'description': 'Entire raw species,fast,charged1,charged2 CSV from Project; no headers or IVs.'}},
                     'required': ['csv_text']}},
    {'name': 'get_storage_status', 'description': 'Inspect saved ZIP archive count and storage byte usage; completed runs retain newest 20 archives up to 200MB.',
     'inputSchema': {'type': 'object', 'properties': {}}},
    {'name': 'prepare_battle', 'description': 'Validate candidate IVs, moves and CP/level settings without running a battle.',
     'inputSchema': PREP},
    {'name': 'start_battle', 'description': 'Start asynchronous PvPoke Matrix simulations. Use get_status to poll.',
     'inputSchema': PREP},
    {'name': 'prepare_24_conditions', 'description': 'Preview curated meta batch. batch_mode=simple: Default IV x 6 shields; detailed: 4 IV modes x 6 shields. Does not start battle.',
     'inputSchema': {'type': 'object', 'properties': {'candidate': POKEMON, 'ivs': PREP['properties']['ivs'],
                         'batch_mode': {'type':'string','enum':['simple','detailed'],'default':'simple',
                                        'description':'simple = only PvPoke Default opponents, 6 shield conditions; detailed = all four opponent IV modes, 24 conditions'}},
                     'required': ['candidate', 'ivs']}},
    {'name': 'start_24_conditions', 'description': 'Run curated meta batch, simple 6 scenarios or detailed 24 scenarios. Defaults to simple. Read get_status and get_24_summary.',
     'inputSchema': {'type': 'object', 'properties': {'candidate': POKEMON, 'ivs': PREP['properties']['ivs'],
                         'batch_mode': {'type':'string','enum':['simple','detailed'],'default':'simple',
                                        'description':'simple = only PvPoke Default opponents, 6 shield conditions; detailed = all four opponent IV modes, 24 conditions'}},
                     'required': ['candidate', 'ivs']}},
    {'name': 'get_24_summary', 'description': 'Get candidate IV performance aggregates for a finished 6 or 24 condition meta job.',
     'inputSchema': {'type': 'object', 'properties': {
         'offset': {'type':'integer','minimum':0,'default':0},
         'limit': {'type':'integer','minimum':1,'maximum':50,'default':20},
         'mode': {'type':'string','enum':['default','rank1','attack','defense']}
     }}},
    {'name': 'get_selection_report',
     'description': 'Fast six-shield IV comparison in one call: all candidate rankings, 500-rating crossovers and optionally full ratings for named focus opponents. Reuses completed ZIP without rerunning battles.',
     'inputSchema': {'type': 'object', 'properties': {
         'mode': {'type': 'string', 'enum': ['default','rank1','attack','defense'], 'default': 'default'},
         'focus_opponents': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 15,
                             'description': 'Optional case-insensitive name fragments, e.g. Corsola, Tinkaton, Clodsire'},
         'max_flips': {'type': 'integer', 'minimum': 0, 'maximum': 500, 'default': 120}
     }}},
    {'name': 'get_selection_digest',
     'description': 'Compact all-6-shield IV evidence digest. Full saved ZIP is verified and analyzed server-side. Returns all candidate rankings, Pareto dominance, important crossover examples and selective focus matchup ratings; no new battles, no S/A grades.',
     'inputSchema': {'type': 'object', 'properties': {
         'mode': {'type': 'string', 'enum': ['default','rank1','attack','defense'], 'default': 'default'},
         'focus_opponents': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 15},
         'highlight_limit': {'type': 'integer', 'minimum': 1, 'maximum': 60, 'default': 20},
         'review_limit': {'type': 'integer', 'minimum': 2, 'maximum': 12, 'default': 8},
         'focus_limit': {'type': 'integer', 'minimum': 0, 'maximum': 20, 'default': 20}
     }}},
    {'name': 'run_iv_selection',
     'description': 'Launch all curated battles and wait up to 20s. Default: verified decision-v2 evidence for GPT evaluation. report_format=app: rule-based provisional recommendations, reasons and search strings. Return run_ref for bounded polling. Never restart a running batch.',
     'inputSchema': {'type': 'object', 'properties': {
         'candidate': POKEMON,
         'ivs': PREP['properties']['ivs'],
         'batch_mode': {'type': 'string', 'enum': ['simple', 'detailed'], 'default': 'simple'},
         'expected_meta_sha256': {'type': 'string', 'pattern': '^[0-9a-fA-F]{64}$',
                                  'description': 'Hash from the Project meta source; abort when the server meta hash differs.'},
         'focus_opponents': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 15},
         'highlight_limit': {'type': 'integer', 'minimum': 1, 'maximum': 60, 'default': 20},
         'review_limit': {'type': 'integer', 'minimum': 2, 'maximum': 12, 'default': 8},
         'focus_limit': {'type': 'integer', 'minimum': 0, 'maximum': 20, 'default': 20},
         'wait_seconds': {'type': 'integer', 'minimum': 0, 'maximum': 20, 'default': 12},
         'report_format': {'type': 'string', 'enum': ['decision', 'decision-v1', 'compact', 'app'], 'default': 'decision'},
         'selection_policy': {'type': 'object', 'properties': {
             'meaningful_win_lead': {'type': 'number', 'minimum': 1, 'maximum': 1000, 'default': 20}
         }, 'additionalProperties': False}
     }, 'required': ['candidate', 'ivs']}},
    {'name': 'get_iv_selection_result',
     'description': 'Wait up to 12s by default for the exact run_ref; return verified decision evidence when complete. Cached results retain job-identity checks. Never restart the batch.',
     'inputSchema': {'type': 'object', 'properties': {
         'run_ref': {'type': 'string', 'minLength': 1},
         'wait_seconds': {'type': 'integer', 'minimum': 0, 'maximum': 20, 'default': 12}
     }, 'required': ['run_ref']}},
    {'name': 'get_status', 'description': 'Read local calculation state, progress and recent logs.',
     'inputSchema': {'type': 'object', 'properties': {}}},
    {'name': 'get_results', 'description': 'Get per-opponent Battle Ratings from a finished result ZIP, 6 or 24 conditions.',
     'inputSchema': {
         'type': 'object',
         'properties': {
             'shield': {'type': 'string', 'enum': ['s0','s1','s2','i0y1','i0y2','i1y2'], 'default': 's1'},
             'offset': {'type': 'integer', 'minimum': 0, 'default': 0},
             'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20, 'default': 10},
             'mode': {'type':'string','enum':['default','rank1','attack','defense'],
                      'description':'Required for 24-condition ZIP results, absent for legacy 6-condition ZIP'},
         },
     }},
]

def call_tool(name, args):
    if not isinstance(args, dict):
        raise ValueError('arguments must be an object')
    if name == 'get_catalog':
        result = backend.catalog()
        result['app_access'] = APP_ACCESS.issue(APP_ORIGIN)
        return result
    if name == 'get_meta_status':
        return backend.meta_status()
    if name == 'sync_meta_opponents':
        return backend.sync_meta_opponents(args['csv_text'])
    if name == 'get_storage_status':
        return backend.storage_status()
    if name in ('prepare_battle', 'start_battle'):
        action = backend.preview if name == 'prepare_battle' else backend.start
        return action(args['candidate'], args['ivs'], args['opponents'],
                      args.get('shields', 'all'), args.get('opponent_iv_mode'))
    if name == 'prepare_24_conditions':
        return backend.preview24(args['candidate'], args['ivs'], args.get('batch_mode', 'simple'))
    if name == 'start_24_conditions':
        return backend.start24(args['candidate'], args['ivs'], args.get('batch_mode', 'simple'))
    if name == 'get_24_summary':
        return backend.summary24(args.get('offset',0), args.get('limit',20), args.get('mode'))
    if name == 'get_selection_report':
        return backend.selection_report(args.get('mode','default'),
                                        args.get('focus_opponents'),
                                        args.get('max_flips',120))
    if name == 'get_selection_digest':
        return backend.selection_digest(args.get('mode','default'),
                                        args.get('focus_opponents'),
                                        args.get('highlight_limit',20),
                                        args.get('review_limit',8),
                                        args.get('focus_limit',20))
    if name == 'run_iv_selection':
        return IV_RUNNER.run(args['candidate'], args['ivs'],
                             args.get('batch_mode') or 'simple',
                             args.get('focus_opponents'),
                             args.get('highlight_limit', 20),
                             args.get('review_limit', 8),
                             args.get('focus_limit', 20),
                             args.get('wait_seconds', 12),
                             args.get('expected_meta_sha256'),
                             args.get('report_format', 'decision'), args.get('selection_policy'))
    if name == 'get_iv_selection_result':
        return IV_RUNNER.result(args['run_ref'], args.get('wait_seconds', 12))
    if name == 'get_status':
        return backend.status()
    if name == 'get_results':
        return backend.results(args.get('shield', 's1'), args.get('offset', 0),
                               args.get('limit', 10), args.get('mode'))
    raise KeyError(f'Unknown tool: {name}')

if AUTH0_ENABLED:
    # Make authorization explicit in MCP tool discovery, without exposing secrets.
    for t in TOOLS:
        t['securitySchemes'] = [{'type':'oauth2', 'scopes':[OAUTH_SCOPE] if OAUTH_SCOPE else []}]

class Handler(BaseHTTPRequestHandler):
    server_version = 'PvPokeMCPLite/0.1'
    def respond(self, code, obj=None):
        data = b'' if obj is None else json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        if obj is not None:
            self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        if data: self.wfile.write(data)
    def unauthorized(self):
        self.send_response(401)
        challenge = 'Bearer'
        if AUTH0_ENABLED:
            challenge += (f' resource_metadata="{MCP_URL.rsplit("/mcp",1)[0]}'
                          '/.well-known/oauth-protected-resource"')
        self.send_header('WWW-Authenticate', challenge)
        self.send_header('Content-Length', '0')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()

    def app_page(self):
        data = APP_HTML.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.end_headers()
        self.wfile.write(data)

    def app_request(self):
        """Only explicit app operations; never proxy arbitrary backend paths."""
        if self.path not in ('/app-api/catalog', '/app-api/import', '/app-api/run', '/app-api/result'):
            return self.respond(404, {'error': 'Not found'})
        origin = self.headers.get('Origin')
        if origin and origin not in (APP_ORIGIN, f'http://127.0.0.1:{PORT}', f'http://localhost:{PORT}'):
            return self.respond(403, {'error': 'Origin not allowed'})
        if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
            return self.respond(415, {'error': 'Content-Type must be application/json'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 140000:
                return self.respond(413, {'error': 'Invalid body size'})
            args = json.loads(self.rfile.read(size))
            if not isinstance(args, dict):
                raise ValueError('入力はJSONオブジェクトで指定してください')
            if self.path == '/app-api/catalog':
                result = backend._request('/api/catalog')
                result.pop('saved', None)
            elif self.path == '/app-api/import':
                cat = backend._request('/api/catalog')
                if not cat.get('ready'):
                    raise ValueError('ゲームデータを読み込み中です。少し待ってください')
                result = parse_import(args.get('text'), cat, args.get('current'))
            elif self.path == '/app-api/run':
                if args.get('report_format', 'app') not in ('app', 'decision'):
                    raise ValueError('評価方法はappまたはdecisionです')
                # Browser has no access to Project files. Bind the job to the
                # currently installed server meta snapshot instead.
                args['expected_meta_sha256'] = backend.meta_status()['sha256']
                args.setdefault('report_format', 'app')
                result = call_tool('run_iv_selection', args)
            else:
                result = IV_RUNNER.result(args.get('run_ref'), args.get('wait_seconds', 12))
            if self.path in ('/app-api/run', '/app-api/result'):
                result['meta_verified_against_project'] = False
                result['meta_verification_source'] = 'server snapshot; Project file unavailable in browser'
            self.respond(200, result)
        except (ValueError, TypeError, KeyError, backend.BridgeError) as exc:
            self.respond(400, {'error': str(exc)})
        except Exception:
            logging.exception('App request failed')
            self.respond(500, {'error': 'アプリの処理に失敗しました'})

    def do_GET(self):
        if self.path in ('/', '/app'):
            self.app_page()
            return
        if self.path in ('/.well-known/oauth-protected-resource',
                         '/.well-known/oauth-protected-resource/mcp') and AUTH0_ENABLED:
            self.respond(200, {
                'resource': MCP_URL,
                'authorization_servers': [AUTH0_ISSUER],
                'scopes_supported': [OAUTH_SCOPE] if OAUTH_SCOPE else []
            })
            return
        if self.path == '/health':
            self.respond(200, {'ok':True, 'version':'0.2-cloud-prototype'})
        else:
            self.respond(405, {'error': 'POST /mcp for MCP requests'})
    def do_POST(self):
        token = self.headers.get('Authorization', '')
        is_api_key = hmac.compare_digest(token, 'Bearer ' + API_KEY)
        app_session = self.path.startswith('/app-api/') and APP_ACCESS.valid(token)
        if not is_api_key and not app_session and not oauth_token_valid(token):
            self.unauthorized()
            return
        if self.path.startswith('/app-api/'):
            self.app_request()
            return
        if self.path != '/mcp':
            self.respond(404, {'error': 'Not found'})
            return
        origin = self.headers.get('Origin')
        if origin and origin not in ALLOWED_ORIGINS:
            self.respond(403, {'error': 'Origin not allowed'})
            return
        ct = self.headers.get('Content-Type', '').split(';')[0].strip().lower()
        if ct != 'application/json':
            self.respond(415, {'error': 'Content-Type must be application/json'})
            return
        try:
            size = int(self.headers.get('Content-Length','0'))
            if not 0 < size <= 1_000_000:
                self.respond(413, {'error': 'Invalid body size'})
                return
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict) or data.get('jsonrpc') != '2.0' or not isinstance(data.get('method'), str):
                self.respond(400, {'jsonrpc':'2.0','id':data.get('id') if isinstance(data,dict) else None,
                                   'error':{'code':-32600,'message':'Invalid Request'}})
                return
            method, id_ = data['method'], data.get('id')
            if 'id' not in data:
                # Notifications are acknowleded without a JSON-RPC response.
                self.respond(202)
                return
            if method == 'initialize':
                result = {'protocolVersion':VERSION, 'capabilities':{'tools':{'listChanged':False}},
                          'serverInfo':{'name':'PvPoke IV Matrix Local', 'version':'0.1'},
                          'instructions':'PvPoke single-worker prototype. Call get_catalog and prepare_battle before start_battle. Avoid concurrent jobs.'}
            elif method == 'ping':
                result = {}
            elif method == 'tools/list':
                result = {'tools': TOOLS}
            elif method == 'tools/call':
                params = data.get('params') or {}
                if not isinstance(params, dict):
                    raise ValueError('Invalid tool params')
                name = params.get('name')
                if name not in {t['name'] for t in TOOLS}:
                    self.respond(200, {'jsonrpc':'2.0','id':id_,
                                       'error':{'code':-32602, 'message':'Unknown tool'}})
                    return
                try:
                    output = call_tool(name, params.get('arguments') or {})
                    result = {'content':[{'type':'text','text':json.dumps(output,ensure_ascii=False,separators=(',',':'))}],
                              'isError':False}
                except Exception as e:
                    result = {'content':[{'type':'text','text':f'{type(e).__name__}: {e}'}],
                              'isError':True}
            else:
                self.respond(200, {'jsonrpc':'2.0','id':id_,
                                   'error':{'code':-32601,'message':'Method not found'}})
                return
            self.respond(200, {'jsonrpc':'2.0','id':id_,'result':result})
        except Exception as e:
            self.respond(400, {'jsonrpc':'2.0','id':None,
                               'error':{'code':-32700,'message':f'Parse error: {str(e)[:200]}'}})

if __name__ == '__main__':
    print(f'Local MCP test server: http://{HOST}:{PORT}/mcp', flush=True)
    print('Authenticated prototype server. HTTPS must be terminated by hosting platform.', flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


