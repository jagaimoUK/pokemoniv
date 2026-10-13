#!/usr/bin/env python3
"""Authenticated cloud prototype for PvPoke: single user, single worker.
Test protocol compliance with real ChatGPT MCP client before relying on it.
Not a hardened multi-tenant production service.
"""
import json
import logging
import os
import hmac
import jwt
from jwt import PyJWKClient, InvalidTokenError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pvpoke_bridge_core as backend

HOST, PORT = '0.0.0.0', int(os.environ.get('PORT', '8787'))
API_KEY = os.environ.get('PVP_API_KEY', '')
if len(API_KEY) < 32:
    raise SystemExit('PVP_API_KEY must be set to a random value at least 32 characters long')
ALLOWED_ORIGINS = {'https://chatgpt.com', 'https://chat.openai.com', f'http://127.0.0.1:{PORT}', f'http://localhost:{PORT}'}
VERSION = '2025-06-18'
# OAuth is enabled only when the authenticated user's Auth0 tenant is configured.
MCP_URL = os.environ.get('PVP_MCP_URL', 'https://pokemoniv-production.up.railway.app/mcp').rstrip('/')
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
        'iv_mode': {'type': 'string', 'enum': ['custom', 'default', 'rank1', 'attack', 'defense'],
                    'description': 'When set, selects custom IVs or PvPoke GameMaster/ranked opponent IVs.'},
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
        'opponent_iv_mode': {'type': 'string', 'enum': ['custom', 'default', 'rank1', 'attack', 'defense'],
                             'default': 'custom',
                             'description': 'Global opponent IV selection for rows without explicit IVs; existing IVs remain custom.'},
    },
    'required': ['candidate', 'ivs', 'opponents'],
}
TOOLS = [
    {'name': 'get_catalog', 'description': 'Get currently available Pokemon presets and dataset status.',
     'inputSchema': {'type': 'object', 'properties': {}}},
    {'name': 'prepare_battle', 'description': 'Validate candidate IVs, moves and CP/level settings without running a battle.',
     'inputSchema': PREP},
    {'name': 'start_battle', 'description': 'Start asynchronous PvPoke Matrix simulations. Use get_status to poll.',
     'inputSchema': PREP},
    {'name': 'get_status', 'description': 'Read local calculation state, progress and recent logs.',
     'inputSchema': {'type': 'object', 'properties': {}}},
    {'name': 'get_results', 'description': 'Get per-opponent Battle Ratings from an existing result ZIP.',
     'inputSchema': {
         'type': 'object',
         'properties': {
             'shield': {'type': 'string', 'enum': ['s0','s1','s2','i0y1','i0y2','i1y2'], 'default': 's1'},
             'offset': {'type': 'integer', 'minimum': 0, 'default': 0},
             'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20, 'default': 10},
         },
     }},
]

def call_tool(name, args):
    if not isinstance(args, dict):
        raise ValueError('arguments must be an object')
    if name == 'get_catalog':
        return backend.catalog()
    if name in ('prepare_battle', 'start_battle'):
        global_mode = args.get('opponent_iv_mode', 'custom')
        opponents = []
        for row in args['opponents']:
            opponent = dict(row)
            if 'iv_mode' not in opponent and not any(k in opponent for k in ('atk', 'def', 'hp')):
                opponent['iv_mode'] = global_mode
            opponents.append(opponent)
        action = backend.preview if name == 'prepare_battle' else backend.start
        return action(args['candidate'], args['ivs'], opponents, args.get('shields', 'all'))
    if name == 'get_status':
        return backend.status()
    if name == 'get_results':
        return backend.results(args.get('shield', 's1'), args.get('offset', 0), args.get('limit', 10))
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

    def do_GET(self):
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
        if not is_api_key and not oauth_token_valid(token):
            self.unauthorized()
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
                    result = {'content':[{'type':'text','text':json.dumps(output,ensure_ascii=False)}],
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
