#!/usr/bin/env python3
"""Authenticated cloud prototype for PvPoke: single user, single worker.
Test protocol compliance with real ChatGPT MCP client before relying on it.
Not a hardened multi-tenant production service.
"""
import json
import logging
import os
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pvpoke_bridge_core as backend

HOST, PORT = '0.0.0.0', int(os.environ.get('PORT', '8787'))
API_KEY = os.environ.get('PVP_API_KEY', '')
if len(API_KEY) < 32:
    raise SystemExit('PVP_API_KEY must be set to a random value at least 32 characters long')
ALLOWED_ORIGINS = {'https://chatgpt.com', 'https://chat.openai.com', f'http://127.0.0.1:{PORT}', f'http://localhost:{PORT}'}
VERSION = '2025-06-18'

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
    },
    'required': [*POKEMON['required'], 'atk', 'def', 'hp'],
}
PREP = {
    'type': 'object',
    'properties': {
        'candidate': POKEMON,
        'ivs': {'type': 'string', 'description': 'One ATK,DEF,HP triplet per line, e.g. 0,15,15\\n1,15,14'},
        'opponents': {'type': 'array', 'items': OPPONENT, 'minItems': 1},
        'shields': {'type': 'string', 'enum': ['all', 'equal', 'disadvantage'], 'default': 'all'},
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
    if name == 'prepare_battle':
        return backend.preview(args['candidate'], args['ivs'], args['opponents'], args.get('shields', 'all'))
    if name == 'start_battle':
        return backend.start(args['candidate'], args['ivs'], args['opponents'], args.get('shields', 'all'))
    if name == 'get_status':
        return backend.status()
    if name == 'get_results':
        return backend.results(args.get('shield', 's1'), args.get('offset', 0), args.get('limit', 10))
    raise KeyError(f'Unknown tool: {name}')

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
    def do_GET(self):
        if self.path == '/health':
            self.respond(200, {'ok':True, 'version':'0.2-cloud-prototype'})
        else:
            self.respond(405, {'error': 'POST /mcp for MCP requests'})
    def do_POST(self):
        token = self.headers.get('Authorization', '')
        if not hmac.compare_digest(token, 'Bearer ' + API_KEY):
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Bearer')
            self.send_header('Content-Length', '0')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
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
                          'instructions':'Local testing server only. Call get_catalog and prepare_battle before start_battle.'}
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
