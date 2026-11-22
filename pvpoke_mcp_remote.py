#!/usr/bin/env python3
"""Authenticated cloud prototype for PvPoke: single user, single worker.
Test protocol compliance with real ChatGPT MCP client before relying on it.
Not a hardened multi-tenant production service.
"""
import json
import hashlib
import re
import sqlite3
from pvpoke_input_limits import MAX_APP_REQUEST_BYTES
from pvpoke_battle_service import MAX_REQUEST_BYTES as MAX_BATTLE_REQUEST_BYTES, _unique_object, _reject_constant
import base64
import threading
import logging
import os
import hmac
import time
from functools import lru_cache
from urllib.parse import urlparse
try:
    import jwt
    from jwt import PyJWKClient, InvalidTokenError
except ImportError:
    jwt = None
    PyJWKClient = None
    class InvalidTokenError(Exception):
        pass
from http.server import BaseHTTPRequestHandler
from pvpoke_http_security import BoundedHTTPServer, RateBudget, safe_equal
import pvpoke_bridge_core as backend
from pvpoke_iv_workflow import IVWorkflow
from pvpoke_app_ui import HTML as APP_HTML
from pvpoke_party_ui import HTML as PARTY_HTML
from pvpoke_missing_comparison import APP_PATH as MISSING_APP_PATH, API_PATH as MISSING_API_PATH
from pvpoke_missing_comparison import PAGE_PATH as MISSING_PAGE_PATH, MAX_REQUEST_BYTES as MAX_MISSING_REQUEST_BYTES
from pvpoke_missing_comparison import enabled as missing_enabled
from pvpoke_individual_sync import (
    ACTIONS as SYNC_ACTIONS, KIND as SYNC_KIND, READER_PATH as READER_SYNC_PATH,
    WEB_PATH as WEB_SYNC_PATH, IndividualConnections,
)
from pvpoke_sandbox_workspace import APP_PATH as SANDBOX_APP_PATH, API_PATH as SANDBOX_API_PATH
from pvpoke_sandbox_workspace import PAGE_PATH as SANDBOX_PAGE_PATH, enabled as sandbox_enabled
from pvpoke_sandbox_workspace import OBSERVED_ACTIONS, observed_enabled
from pvpoke_app_access import AppAccess, BrowserLogin
from pvpoke_app_input import parse_import
from pvpoke_score_search import search_low_scores
from pvpoke_reader_cleanup import reader_cleanup_payload
import pvpoke_flashcards as flashcards
import pvpoke_browser_migration as browser_migration

APP_ACCESS = AppAccess()

IV_RUNNER = IVWorkflow(backend)
RATE_BUDGET = RateBudget()
BACKUP_SLOTS = threading.BoundedSemaphore(1)
APP_REQUEST_SLOTS = threading.BoundedSemaphore(4)
MCP_COMPUTE_TOOLS = frozenset({'start_battle', 'start_24_conditions', 'run_iv_selection'})

HOST, PORT = os.environ.get('PVP_BIND_HOST', '0.0.0.0'), int(os.environ.get('PORT', '8787'))
API_KEY = os.environ.get('PVP_API_KEY', '')
if len(API_KEY) < 32:
    raise SystemExit('PVP_API_KEY must be set to a random value at least 32 characters long')
BROWSER_LOGIN = BrowserLogin(API_KEY)
from visual_backup import VisualBackup, BackupTokens, BackupError, BACKUP_HTML, MAX_ARCHIVE
VISUAL_BACKUP = VisualBackup()
BACKUP_TOKENS = BackupTokens(API_KEY)
INDIVIDUAL_CONNECTIONS = IndividualConnections(API_KEY)
if VISUAL_BACKUP.enabled:
    threading.Thread(target=VISUAL_BACKUP.probe, daemon=True).start()
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

_JWKS_KEY_CACHE = {}  # {kid: (key, expire_time)} max 16 items
_JWKS_NEG_CACHE = {}  # {kid: expire_time} max 128 items
_JWT_BAD_SIG_CACHE = {}  # {token_digest: expire_time} max 512 items
_JWT_GOOD_SIG_CACHE = {}  # {token_digest: expire_time} max 32 items (rate-gate helper only; never skips jwt.decode)
_JWKS_CACHE_LOCK = threading.Lock()
_LAST_JWKS_REFRESH_AT = 0.0
_JWKS_FULL_SET_FRESH_UNTIL = 0.0
JWKS_SLOTS = threading.BoundedSemaphore(2)
OAUTH_VERIFY_SLOTS = threading.BoundedSemaphore(2)
JWKS_FETCH_TIMEOUT = 5.0


def _unverified_claims_match(token):
    parts = token.split('.')
    if len(parts) != 3 or any(not p for p in parts):
        return False
    padded = parts[1] + '=' * (-len(parts[1]) % 4)
    unverified = json.loads(base64.urlsafe_b64decode(padded.encode('ascii')).decode('utf-8'))
    if not isinstance(unverified, dict):
        return False
    if unverified.get('iss') != AUTH0_ISSUER:
        return False
    aud_claim = unverified.get('aud')
    if isinstance(aud_claim, list):
        if JWT_AUDIENCE not in aud_claim:
            return False
    elif aud_claim != JWT_AUDIENCE:
        return False
    if not safe_equal(str(unverified.get('sub', '')), AUTH0_ALLOWED_SUB):
        return False
    exp = unverified.get('exp')
    if isinstance(exp, bool) or not isinstance(exp, (int, float)) or exp + 15 < time.time():
        return False
    if OAUTH_SCOPE:
        scopes = set(str(unverified.get('scope', '')).split())
        permissions = unverified.get('permissions', [])
        if not isinstance(permissions, list):
            permissions = []
        if OAUTH_SCOPE not in (scopes | set(str(x) for x in permissions)):
            return False
    return True


def _cache_negative_kid(kid, now):
    with _JWKS_CACHE_LOCK:
        if len(_JWKS_NEG_CACHE) >= 128 and kid not in _JWKS_NEG_CACHE:
            oldest = min(_JWKS_NEG_CACHE.keys(), key=lambda k: _JWKS_NEG_CACHE[k])
            del _JWKS_NEG_CACHE[oldest]
        _JWKS_NEG_CACHE[kid] = now + 15.0


def _cache_bad_sig(token_digest, now):
    with _JWKS_CACHE_LOCK:
        _JWT_GOOD_SIG_CACHE.pop(token_digest, None)
        if len(_JWT_BAD_SIG_CACHE) >= 512 and token_digest not in _JWT_BAD_SIG_CACHE:
            oldest = min(_JWT_BAD_SIG_CACHE.keys(), key=lambda k: _JWT_BAD_SIG_CACHE[k])
            del _JWT_BAD_SIG_CACHE[oldest]
        _JWT_BAD_SIG_CACHE[token_digest] = now + 30.0


def _cache_good_sig(token_digest, now, exp_unix):
    ttl = max(1.0, min(300.0, float(exp_unix) - time.time() + 15.0))
    with _JWKS_CACHE_LOCK:
        _JWT_BAD_SIG_CACHE.pop(token_digest, None)
        if len(_JWT_GOOD_SIG_CACHE) >= 32 and token_digest not in _JWT_GOOD_SIG_CACHE:
            oldest = min(_JWT_GOOD_SIG_CACHE.keys(), key=lambda k: _JWT_GOOD_SIG_CACHE[k])
            del _JWT_GOOD_SIG_CACHE[oldest]
        _JWT_GOOD_SIG_CACHE[token_digest] = now + ttl


def _evaluate_oauth_token(raw, rate_checker=None):
    global _LAST_JWKS_REFRESH_AT, _JWKS_FULL_SET_FRESH_UNTIL
    if not AUTH0_ENABLED or jwt is None or not isinstance(raw, str) or not raw.startswith('Bearer ') or len(raw) > 4096 or not raw.isascii():
        return 'invalid'
    token = raw[7:]
    allow_fn = rate_checker if rate_checker is not None else RATE_BUDGET.allow
    budget_obj = getattr(allow_fn, '__self__', None)
    can_peek = hasattr(budget_obj, 'available')
    token_digest = hmac.new(API_KEY.encode('ascii'), token.encode('ascii'), 'sha256').hexdigest()
    ran_rsa = False
    try:
        header = jwt.get_unverified_header(token)
        if header.get('alg') != 'RS256':
            return 'invalid'
        kid = header.get('kid')
        if not isinstance(kid, str) or not (1 <= len(kid) <= 128):
            return 'invalid'
        if not _unverified_claims_match(token):
            return 'invalid'

        key = None
        was_known = False
        known_good_sig = False
        now = time.monotonic()
        with _JWKS_CACHE_LOCK:
            bad_expire = _JWT_BAD_SIG_CACHE.get(token_digest)
            if bad_expire is not None:
                if bad_expire > now:
                    return 'invalid'
                del _JWT_BAD_SIG_CACHE[token_digest]
            good_expire = _JWT_GOOD_SIG_CACHE.get(token_digest)
            if good_expire is not None:
                if good_expire > now:
                    known_good_sig = True
                else:
                    del _JWT_GOOD_SIG_CACHE[token_digest]
            entry = _JWKS_KEY_CACHE.get(kid)
            if entry is not None:
                cached_key, expire = entry
                was_known = True
                if expire > now:
                    key = cached_key
            if key is None:
                neg_expire = _JWKS_NEG_CACHE.get(kid)
                if neg_expire is not None:
                    if neg_expire > now:
                        return 'invalid'
                    del _JWKS_NEG_CACHE[kid]
                if not was_known and _JWKS_FULL_SET_FRESH_UNTIL > now:
                    if len(_JWKS_NEG_CACHE) >= 128 and kid not in _JWKS_NEG_CACHE:
                        oldest = min(_JWKS_NEG_CACHE.keys(), key=lambda k: _JWKS_NEG_CACHE[k])
                        del _JWKS_NEG_CACHE[oldest]
                    _JWKS_NEG_CACHE[kid] = now + 15.0
                    return 'invalid'

        if key is None:
            if was_known:
                if not allow_fn('known-jwks', 10, 60):
                    return 'rate_limited'
            else:
                if not allow_fn('unauth-jwks', 10, 60):
                    with _JWKS_CACHE_LOCK:
                        cooldown_ok = (now - _LAST_JWKS_REFRESH_AT) >= 15.0
                    if not (cooldown_ok and allow_fn('emergency-jwks', 1, 15)):
                        return 'rate_limited'

            if not JWKS_SLOTS.acquire(blocking=False):
                return 'unavailable'
            try:
                fetch_deadline = time.monotonic() + JWKS_FETCH_TIMEOUT
                fetched_keys = None
                if hasattr(JWKS, 'get_signing_keys'):
                    try:
                        fetched_keys = JWKS.get_signing_keys(refresh=True)
                    except TypeError:
                        fetched_keys = JWKS.get_signing_keys()
                if time.monotonic() > fetch_deadline:
                    return 'unavailable'
                if isinstance(fetched_keys, list) and fetched_keys:
                    refreshed_at = time.monotonic()
                    present_kids = set()
                    with _JWKS_CACHE_LOCK:
                        _LAST_JWKS_REFRESH_AT = refreshed_at
                        _JWKS_FULL_SET_FRESH_UNTIL = refreshed_at + 5.0
                        for item in fetched_keys:
                            item_kid = getattr(item, 'key_id', None)
                            if isinstance(item_kid, str) and 1 <= len(item_kid) <= 128:
                                present_kids.add(item_kid)
                                if len(_JWKS_KEY_CACHE) >= 16 and item_kid not in _JWKS_KEY_CACHE:
                                    oldest = min(_JWKS_KEY_CACHE.keys(), key=lambda k: _JWKS_KEY_CACHE[k][1])
                                    del _JWKS_KEY_CACHE[oldest]
                                _JWKS_KEY_CACHE[item_kid] = (item, refreshed_at + 300)
                                _JWKS_NEG_CACHE.pop(item_kid, None)
                        if was_known and kid not in present_kids:
                            _JWKS_KEY_CACHE.pop(kid, None)
                        if kid in _JWKS_KEY_CACHE:
                            key = _JWKS_KEY_CACHE[kid][0]
                else:
                    key = JWKS.get_signing_key_from_jwt(token)
                    if time.monotonic() > fetch_deadline:
                        return 'unavailable'
                    if key is not None:
                        refreshed_at = time.monotonic()
                        with _JWKS_CACHE_LOCK:
                            _LAST_JWKS_REFRESH_AT = refreshed_at
                            if len(_JWKS_KEY_CACHE) >= 16 and kid not in _JWKS_KEY_CACHE:
                                oldest = min(_JWKS_KEY_CACHE.keys(), key=lambda k: _JWKS_KEY_CACHE[k][1])
                                del _JWKS_KEY_CACHE[oldest]
                            _JWKS_KEY_CACHE[kid] = (key, refreshed_at + 300)
                            _JWKS_NEG_CACHE.pop(kid, None)
                if key is None:
                    _cache_negative_kid(kid, time.monotonic())
                    return 'invalid'
            finally:
                JWKS_SLOTS.release()

        if not known_good_sig:
            if can_peek:
                if not budget_obj.available('unauth-oauth-sig', 60, 60):
                    return 'rate_limited'
            else:
                if not allow_fn('unauth-oauth-sig', 60, 60):
                    return 'rate_limited'

        if not OAUTH_VERIFY_SLOTS.acquire(timeout=0.05):
            return 'unavailable'
        try:
            ran_rsa = True
            claims = jwt.decode(token, key.key, algorithms=['RS256'],
                                audience=JWT_AUDIENCE, issuer=AUTH0_ISSUER,
                                options={'require': ['iss', 'aud', 'exp', 'sub']}, leeway=15)
        finally:
            OAUTH_VERIFY_SLOTS.release()
        if not safe_equal(str(claims.get('sub', '')), AUTH0_ALLOWED_SUB):
            _cache_bad_sig(token_digest, time.monotonic())
            if can_peek:
                allow_fn('unauth-oauth-sig', 60, 60)
            return 'invalid'
        if OAUTH_SCOPE:
            scopes = set(str(claims.get('scope', '')).split())
            permissions = claims.get('permissions', [])
            if not isinstance(permissions, list):
                permissions = []
            if OAUTH_SCOPE not in (scopes | set(str(x) for x in permissions)):
                _cache_bad_sig(token_digest, time.monotonic())
                if can_peek:
                    allow_fn('unauth-oauth-sig', 60, 60)
                return 'invalid'
        _cache_good_sig(token_digest, time.monotonic(), claims['exp'])
        return 'ok'
    except (InvalidTokenError, ValueError, KeyError, TypeError, RecursionError) as exc:
        if ran_rsa:
            _cache_bad_sig(token_digest, time.monotonic())
            if can_peek:
                allow_fn('unauth-oauth-sig', 60, 60)
        logging.warning('OAuth token rejected: %s', type(exc).__name__)
        return 'invalid'
    except OSError as exc:
        logging.warning('OAuth authentication unavailable: %s', type(exc).__name__)
        return 'unavailable'
    except Exception as exc:
        logging.warning('OAuth authentication unavailable: %s', type(exc).__name__)
        return 'unavailable'


_OAUTH_LAST_OUTCOME = threading.local()


def oauth_token_valid(raw, rate_checker=None):
    status = _evaluate_oauth_token(raw, rate_checker=rate_checker)
    _OAUTH_LAST_OUTCOME.status = status
    return status == 'ok'


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
         'force_recalculate': {'type': 'boolean', 'default': False, 'description': 'Bypass saved battle ZIPs, matchup results and intermediate parts for this job.'},
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
                             args.get('report_format', 'decision'), args.get('selection_policy'),
                             args.get('meta_preset_id'), args.get('force_recalculate', False), args.get('request_id'))
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

@lru_cache(maxsize=1)
def cached_reader_cleanup():
    """Fixed snapshot / nonpersonal response. Do not cache user sessions."""
    catalog = backend._request('/api/catalog')
    if not catalog.get('ready'):
        raise ValueError('図鑑データを準備中です')
    return reader_cleanup_payload(catalog.get('species'))


class Handler(BaseHTTPRequestHandler):
    server_version = 'PvPokeMCPLite/0.1'
    def log_message(self, format, *args):
        # Requests can contain sensitive query strings; never echo raw URLs.
        logging.info('HTTP request handled')
    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        if APP_ORIGIN.startswith('https://'):
            self.send_header('Strict-Transport-Security', 'max-age=86400')
        super().end_headers()

    def html_policy(self, data):
        scripts = re.findall(rb'<script[^>]*>(.*?)</script\s*>', data, re.S | re.I)
        hashes = ' '.join("'sha256-" + base64.b64encode(hashlib.sha256(x).digest()).decode() + "'" for x in scripts)
        self.send_header('Content-Security-Policy',
                         "default-src 'none'; script-src " + (hashes or "'none'") +
                         "; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; "
                         "base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'none'")

    def send_rate_limited(self):
        self.send_response(429)
        self.send_header('Retry-After', '10')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def rate_allowed(self, name, count, seconds):
        if RATE_BUDGET.allow(name, count, seconds):
            return True
        self.send_rate_limited()
        return False

    def read_body(self, size):
        # A separate absolute read deadline defeats slow byte trickles.
        import socket
        def expire():
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        timer = threading.Timer(20, expire)
        timer.daemon = True
        timer.start()
        try:
            body = self.rfile.read(size)
            if len(body) != size:
                raise ValueError('Incomplete request body')
            return body
        finally:
            timer.cancel()

    def respond(self, code, obj=None, cookie=None):
        data = b'' if obj is None else json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        if obj is not None:
            self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        if cookie is not None:
            self.send_header('Set-Cookie', cookie)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        if data:
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                # A disconnected poll does not mean the calculation failed.
                pass
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
        if self.path == MISSING_PAGE_PATH:
            if not missing_enabled():
                return self.respond(404, {'error': 'Not found'})
            from pvpoke_missing_ui import HTML as missing_html
            page = missing_html.replace('data-sandbox="0"',
                                        'data-sandbox="1"' if sandbox_enabled() else 'data-sandbox="0"')
            page = page.replace('data-tactic-search="0"',
                                'data-tactic-search="1"'
                                if sandbox_enabled() and os.environ.get('PVP_TACTIC_SEARCH_ENABLED') == '1'
                                else 'data-tactic-search="0"')
            page = page.replace('data-observed-search="0"',
                                'data-observed-search="1"' if sandbox_enabled() and observed_enabled()
                                else 'data-observed-search="0"')
        elif self.path in (SANDBOX_PAGE_PATH, SANDBOX_PAGE_PATH + '?observed=1'):
            if not sandbox_enabled():
                return self.respond(404, {'error': 'Not found'})
            from pvpoke_sandbox_ui import HTML as sandbox_html
            page = sandbox_html.replace(
                '<!--MISSING_ANALYSIS_NAV-->', '<a href="/app/missing">不足分析</a>' if missing_enabled() else '')
            page = page.replace('data-tactic-search="0"',
                                'data-tactic-search="1"' if os.environ.get('PVP_TACTIC_SEARCH_ENABLED') == '1'
                                else 'data-tactic-search="0"')
            if observed_enabled():
                page = page.replace('data-observed-search="0"', 'data-observed-search="1"')
        elif self.path == '/app/migration':
            page = browser_migration.page()
        elif self.path == '/flashcards':
            page = flashcards.page()
        elif self.path == '/app/party':
            page = PARTY_HTML
        else:
            tools = ('<a href="/app/missing">不足分析</a>' if missing_enabled() else '')
            if sandbox_enabled():
                tools += '<a href="/app/sandbox">Sandbox</a>'
            page = APP_HTML.replace('<!--MISSING_ANALYSIS_NAV-->', tools)
        data = page.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.html_policy(data)
        self.end_headers()
        self.wfile.write(data)

    def individual_sync_request(self, args, reader_instance):
        if not missing_enabled():
            return self.respond(503, {'error': '個体同期を利用できません'})
        action = args.get('action')
        if reader_instance is not None:
            if action not in SYNC_ACTIONS or args.get('instance_id') != reader_instance:
                return self.respond(403, {'error': 'この個体に接続できません'})
        if action == 'connections':
            return self.respond(200, {'items': INDIVIDUAL_CONNECTIONS.store.list_active(SYNC_KIND)})
        if action == 'revoke':
            ident = args.get('id')
            if not isinstance(ident, str) or not re.fullmatch('[0-9a-f]{64}', ident):
                raise ValueError('接続IDを確認してください')
            INDIVIDUAL_CONNECTIONS.store.revoke(ident, SYNC_KIND)
            return self.respond(200, {'revoked': True})
        if action == 'issue':
            args = {'action': 'individual_get', 'instance_id': args.get('instance_id')}
        elif action not in SYNC_ACTIONS:
            raise ValueError('同期操作を確認してください')
        try:
            result = backend._request(MISSING_API_PATH, args, headers={'X-PvPoke-Token': backend._token()}, timeout=20)
        except backend.BridgeError as exc:
            for status in (400, 404, 409, 503):
                if f'HTTP {status}:' in str(exc):
                    return self.respond(status, {'error': '個体の確認状態または同期内容を確認してください'})
            return self.respond(503, {'error': '個体の保存先に接続できません'})
        if action == 'issue':
            return self.respond(200, {'connection': INDIVIDUAL_CONNECTIONS.issue(result['individual']['instance_id'])})
        return self.respond(200, result)

    def app_request(self, reader_instance=None):
        """Only explicit app operations; never proxy arbitrary backend paths."""
        if self.path not in ('/app-api/catalog', '/app-api/import', '/app-api/run', '/app-api/result', '/app-api/cancel',
                             '/app-api/session', '/app-api/logout', '/app-api/visual-backup-connections', '/app-api/visual-backup-revoke', '/app-api/meta-status',
                             '/app-api/meta-preview', '/app-api/meta-apply', '/app-api/meta-presets', '/app-api/meta-preset-save', '/app-api/meta-preset-export', '/app-api/low-score', '/app-api/visual-backup-token', '/app-api/flashcards',
                             '/app-api/party/list', '/app-api/party/get', '/app-api/party/save',
                             '/app-api/party/start', '/app-api/party/status', '/app-api/party/cancel',
                             '/app-api/party/meta-weights', '/app-api/battles/simulate', MISSING_APP_PATH, SANDBOX_APP_PATH,
                             WEB_SYNC_PATH, READER_SYNC_PATH):
            return self.respond(404, {'error': 'Not found'})
        origin = self.headers.get('Origin')
        if origin and origin not in (APP_ORIGIN, f'http://127.0.0.1:{PORT}', f'http://localhost:{PORT}'):
            return self.respond(403, {'error': 'Origin not allowed'})
        if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
            return self.respond(415, {'error': 'Content-Type must be application/json'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            workspace = self.path in (MISSING_APP_PATH, SANDBOX_APP_PATH)
            battle = self.path in ('/app-api/battles/simulate', SANDBOX_APP_PATH)
            limit = {MISSING_APP_PATH: MAX_MISSING_REQUEST_BYTES, WEB_SYNC_PATH: 8192, READER_SYNC_PATH: 8192}.get(
                self.path, MAX_BATTLE_REQUEST_BYTES if battle else MAX_APP_REQUEST_BYTES)
            if not 0 < size <= limit:
                return self.respond(413, {'error': 'Invalid body size'})
            raw = self.read_body(size)
            # All app routes must interpret the same JSON identically.
            # Duplicate keys and non-finite numbers cannot override state or
            # produce ambiguous validation results on legacy endpoints.
            args = json.loads(raw, object_pairs_hook=_unique_object,
                              parse_constant=_reject_constant)
            if not isinstance(args, dict):
                raise ValueError('入力はJSONオブジェクトで指定してください')
            if self.path in (WEB_SYNC_PATH, READER_SYNC_PATH):
                return self.individual_sync_request(args, reader_instance)
            if workspace:
                sandbox = self.path == SANDBOX_APP_PATH
                if sandbox and args.get('action') in ('search_start', 'search_step') and os.environ.get(
                        'PVP_TACTIC_SEARCH_ENABLED') != '1':
                    return self.respond(503, {'error': 'Tactic search is disabled'})
                if sandbox and args.get('action') in OBSERVED_ACTIONS and not observed_enabled():
                    return self.respond(503, {'error': 'Observed search is disabled'})
                if not (sandbox_enabled() if sandbox else missing_enabled()):
                    return self.respond(503, {'error': 'Analysis workspace is disabled'})
                if sandbox and args.get('action') in ('simulate', 'standard', 'search_start', 'search_step', 'observed_start', 'observed_step') and not self.rate_allowed('compute-owner', 12, 60):
                    return
                endpoint = SANDBOX_API_PATH if sandbox else MISSING_API_PATH
                try:
                    result = backend._request(endpoint, args, headers={'X-PvPoke-Token': backend._token()}, timeout=65)
                except backend.BridgeError as exc:
                    for status in (400, 409, 413, 422, 503):
                        if f'HTTP {status}:' in str(exc):
                            return self.respond(status, {'error': 'Analysis workspace request rejected or unavailable'})
                    return self.respond(503, {'error': 'Analysis workspace unavailable'})
                return self.respond(200, result)
            if self.path == '/app-api/battles/simulate':
                if os.environ.get('PVP_BATTLE_API_ENABLED') != '1':
                    return self.respond(503, {'error': 'Battle API is disabled'})
                try:
                    result = backend._request('/api/battles/simulate', args,
                                              headers={'X-PvPoke-Token': backend._token()},
                                              timeout=65)
                except backend.BridgeError as exc:
                    # Internal paths, exception details and tracebacks stay private.
                    error = str(exc)
                    for status in (400, 409, 413, 422, 503):
                        if f'HTTP {status}:' in error:
                            return self.respond(status, {'error': 'Battle request rejected or unavailable'})
                    return self.respond(503, {'error': 'Battle service unavailable'})
                if type(result) is not dict or result.get('status') != 'complete':
                    return self.respond(503, {'error': 'Battle result incomplete'})
                return self.respond(200, result)
            if self.path.startswith('/app-api/party/'):
                try:
                    result = backend._request('/api/party/' + self.path.rsplit('/', 1)[-1], args,
                                              headers={'X-PvPoke-Token': backend._token()}, timeout=75)
                    return self.respond(200, result)
                except backend.BridgeError as exc:
                    if 'HTTP 409:' in str(exc):
                        return self.respond(409, {'error': '保存競合、または他の計算中です'})
                    raise
            if self.path == '/app-api/session':
                return self.respond(200, {'expires_in_seconds': BROWSER_LOGIN.ttl},
                                    cookie=BROWSER_LOGIN.issue(secure=APP_ORIGIN.startswith('https://')))
            if self.path == '/app-api/logout':
                BROWSER_LOGIN.revoke(self.headers.get('Cookie', ''))
                APP_ACCESS.revoke(self.headers.get('Authorization', ''))
                return self.respond(200, {'logged_out': True},
                                    cookie=BROWSER_LOGIN.clear(secure=APP_ORIGIN.startswith('https://')))
            if self.path == '/app-api/visual-backup-connections':
                return self.respond(200, {'items': BACKUP_TOKENS.store.list_active('backup')})
            if self.path == '/app-api/visual-backup-revoke':
                ident = args.get('id', '')
                if not isinstance(ident, str) or not re.fullmatch('[0-9a-f]{64}', ident):
                    raise ValueError('接続IDを確認してください')
                BACKUP_TOKENS.store.revoke(ident, 'backup')
                return self.respond(200, {'revoked': True})
            if self.path == '/app-api/visual-backup-token':
                if not VISUAL_BACKUP.enabled:
                    return self.respond(503, {'error':'バックアップ保存先を準備中です'})
                return self.respond(200, {'connection':'pivbackup1.' + BACKUP_TOKENS.issue()})
            if self.path == '/app-api/low-score':
                ranking_catalog = backend._request('/api/catalog')
                if not ranking_catalog.get('ready'):
                    raise ValueError('英語名の図鑑データを準備中です。少し待ってから再実行してください')
                return self.respond(200, search_low_scores(args, ranking_catalog.get('species')))
            if self.path == '/app-api/flashcards':
                return self.respond(200, backend._request('/api/flashcards', headers={'X-PvPoke-Token': backend._token()}))
            if self.path == '/app-api/meta-presets':
                return self.respond(200, backend.meta_presets())
            if self.path == '/app-api/meta-preset-export':
                return self.respond(200, backend.export_meta_preset(
                    args.get('id'), args.get('expected_sha256')))
            if self.path == '/app-api/meta-preset-save':
                return self.respond(200, backend.save_meta_preset(args))
            if self.path == '/app-api/meta-status':
                return self.respond(200, backend.meta_status())
            if self.path == '/app-api/meta-preview':
                return self.respond(200, backend.preview_meta_opponents(args.get('csv')))
            if self.path == '/app-api/meta-apply':
                return self.respond(200, backend.apply_meta_opponents(
                    args.get('csv'), args.get('expected_previous_sha256'),
                    args.get('expected_sha256')))
            if self.path == '/app-api/catalog':
                result = backend._request('/api/catalog')
                result.pop('saved', None)
            elif self.path == '/app-api/import':
                cat = backend._request('/api/catalog')
                if not cat.get('ready'):
                    raise ValueError('ゲームデータを読み込み中です。少し待ってください')
                result = parse_import(args.get('text'), cat, args.get('current'), args.get('registered_movesets'))
            elif self.path == '/app-api/cancel':
                result = IV_RUNNER.cancel(args.get('run_ref'))
            elif self.path == '/app-api/run':
                if args.get('report_format', 'app') not in ('app', 'decision'):
                    raise ValueError('評価方法はappまたはdecisionです')
                # Browser has no access to Project files. Bind the job to the
                # currently installed server meta snapshot instead.
                if args.get('expected_meta_sha256') is None and args.get('meta_preset_id') is None:
                    args['expected_meta_sha256'] = backend.meta_status()['sha256']
                args.setdefault('report_format', 'app')
                result = call_tool('run_iv_selection', args)
            else:
                result = IV_RUNNER.result(args.get('run_ref'), args.get('wait_seconds', 12))
            if self.path in ('/app-api/run', '/app-api/result'):
                result['meta_verified_against_project'] = False
                result['meta_verification_source'] = 'server snapshot; Project file unavailable in browser'
            self.respond(200, result)
        except RecursionError:
            self.respond(400, {'error': 'Request JSON is too deeply nested'})
        except backend.BridgeError as exc:
            # The upstream message can contain internal hostnames, paths,
            # response bodies, or credentials. Never serialize it to a browser.
            # Preserve useful, explicitly recognized client-error status codes.
            upstream = re.match(r'^ローカルアプリ HTTP (400|404|409|413|422):', str(exc))
            status = int(upstream.group(1)) if upstream else 503
            message = ('入力内容または保存状態を確認してください' if upstream
                       else '内部計算サービスに接続できません。再試行してください')
            self.respond(status, {'error': message})
        except ValueError as exc:
            # Existing explicit input validation remains useful to the user.
            self.respond(400, {'error': str(exc)})
        except (TypeError, KeyError):
            # These may originate from internal code or data structures.
            self.respond(400, {'error': '入力形式が正しくありません'})
        except Exception as exc:
            # Exception messages/tracebacks may contain upstream secrets or data.
            logging.error('App request failed: %s', type(exc).__name__)
            self.respond(500, {'error': 'アプリの処理に失敗しました'})

    def visual_backup_request(self):
        origin = self.headers.get('Origin')
        if origin and origin != APP_ORIGIN:
            return self.respond(403, {'error': 'Origin not allowed'})
        if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
            return self.respond(415, {'error': 'Content-Type must be application/json'})
        try:
            if self.path not in ('/visual-backup/v1/status', '/visual-backup/v1/upload', '/visual-backup/v1/download'):
                return self.respond(404, {'error': 'Not found'})
            limit = (MAX_ARCHIVE * 4 // 3 + 4096) if self.path.endswith('/upload') else 4096
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= limit:
                return self.respond(413, {'error': 'バックアップの容量上限を超えています'})
            args = json.loads(self.read_body(size), object_pairs_hook=_unique_object,
                            parse_constant=_reject_constant)
            if not isinstance(args, dict):
                raise ValueError()
            if self.path.endswith('/status'):
                return self.respond(200, VISUAL_BACKUP.head())
            if self.path.endswith('/download'):
                return self.respond(200, VISUAL_BACKUP.download())
            data = base64.b64decode(args.get('archive', ''), validate=True)
            return self.respond(200, VISUAL_BACKUP.upload(data, args.get('expectedEtag')))
        except BackupError as exc:
            return self.respond(exc.status, {'error': str(exc)})
        except (ValueError, TypeError, KeyError):
            return self.respond(400, {'error': 'バックアップの入力が正しくありません'})
        except Exception as exc:
            logging.warning('Visual backup request failed: %s', type(exc).__name__)
            return self.respond(503, {'error': '保存先に接続できません。端末内の見本は残っています'})

    def do_GET(self):
        if self.path != '/health':
            is_app_shell = (
                self.path in ('/', '/app', '/app/party', '/app/migration',
                              MISSING_PAGE_PATH, SANDBOX_PAGE_PATH, SANDBOX_PAGE_PATH + '?observed=1')
                or self.path.startswith('/app?')
            )
            bucket = 'public-get' if is_app_shell else 'public-reader-get'
            limit = 300 if is_app_shell else 120
            if not self.rate_allowed(bucket, limit, 60):
                return
        if self.path == '/reader-api/v1/flashcards':
            tag = flashcards.etag()
            if self.headers.get('If-None-Match') == tag:
                self.send_response(304)
                self.send_header('ETag', tag)
                self.end_headers()
                return
            data = json.dumps(flashcards.public_catalog(), ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            self.send_response(200)
            for name, value in [('Content-Type', 'application/json; charset=utf-8'), ('Content-Length', str(len(data))), ('ETag', tag), ('Cache-Control', 'public, max-age=86400'), ('X-Content-Type-Options', 'nosniff')]:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path in ('/flashcards', '/app/party', '/app/migration', MISSING_PAGE_PATH, SANDBOX_PAGE_PATH,
                         SANDBOX_PAGE_PATH + '?observed=1'):
            return self.app_page()
        # This one read-only route contains only global, fixed PvP rankings
        # transformed into GO search terms. Do not expose private app APIs,
        # user IVs, stored presets, or credentials without authentication.
        if self.path == '/reader-api/v1/cleanup':
            try:
                return self.respond(200, cached_reader_cleanup())
            except ValueError as exc:
                return self.respond(503, {'error': str(exc)})
            except Exception as exc:
                logging.error('Reader cleanup response unavailable: %s', type(exc).__name__)
                return self.respond(503, {'error': '検索式を生成できませんでした'})
        if self.path == '/reader-backup':
            data=BACKUP_HTML.encode('utf-8')
            self.send_response(200)
            for name,value in [('Content-Type','text/html; charset=utf-8'),('Cache-Control','no-store'),('Referrer-Policy','no-referrer'),('X-Frame-Options','DENY'),('Content-Length',str(len(data)))]:
                self.send_header(name,value)
            self.html_policy(data)
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path in ('/', '/app') or self.path.startswith('/app?'):
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
            self.respond(200, {'ok':True, 'version':'0.3-security',
                              'commit':os.environ.get('RAILWAY_GIT_COMMIT_SHA', ''),
                              'visual_backup':{'enabled':VISUAL_BACKUP.enabled,'storage_probe':VISUAL_BACKUP.probe_ok}})
        else:
            self.respond(405, {'error': 'POST /mcp for MCP requests'})

    def do_POST(self):
        # Framing check first with zero budget cost
        if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1:
            return self.respond(400, {'error': 'Invalid request framing'})

        # Reject unknown POST paths before checking JWTs, cookies, or owner budgets.
        # In particular, POST /health must never become a costly auth entry point.
        if not (self.path == '/mcp' or self.path.startswith('/app-api/')
                or self.path.startswith('/visual-backup/v1/')):
            return self.respond(404, {'error': 'Not found'})

        if self.path.startswith('/visual-backup/v1/'):
            raw = self.headers.get('Authorization', '')
            token = raw[7:] if raw.startswith('Bearer ') else ''
            try:
                token_ok = BACKUP_TOKENS.valid(token)
            except (sqlite3.Error, OSError):
                return self.respond(503, {'error': '認証の保存先に接続できません。少し待って再試行してください'})
            if not token_ok:
                if not self.rate_allowed('unauth-backup', 60, 60):
                    return
                return self.unauthorized()
            if not self.rate_allowed('backup-owner', 12, 60):
                return
            if not BACKUP_SLOTS.acquire(blocking=False):
                return self.respond(503, {'error': 'バックアップの処理中です。少し待って再試行してください'})
            try:
                return self.visual_backup_request()
            finally:
                BACKUP_SLOTS.release()

        token = self.headers.get('Authorization', '')
        if self.path == READER_SYNC_PATH:
            if not self.rate_allowed('reader-sync-entry', 180, 60):
                return
            try:
                reader_instance = INDIVIDUAL_CONNECTIONS.instance(token)
            except (sqlite3.Error, OSError):
                return self.respond(503, {'error': '認証の保存先に接続できません'})
            if reader_instance is None:
                return self.unauthorized()
            if not APP_REQUEST_SLOTS.acquire(blocking=False):
                return self.respond(503, {'error': '処理中です。少し待って再試行してください'})
            try:
                return self.app_request(reader_instance)
            finally:
                APP_REQUEST_SLOTS.release()
        is_api_key = safe_equal(token, 'Bearer ' + API_KEY)
        is_app = self.path.startswith('/app-api/')
        app_session = is_app and APP_ACCESS.valid(token)
        cookie_ok = False
        if is_app:
            try:
                cookie_ok = BROWSER_LOGIN.valid(self.headers.get('Cookie', ''))
            except (sqlite3.Error, OSError):
                return self.respond(503, {'error': '認証の保存先に接続できません。少し待って再試行してください'})

        oauth_ok = False
        if not (is_api_key or app_session or cookie_ok) and AUTH0_ENABLED and token.startswith('Bearer ') and len(token) <= 4096 and token.isascii():
            _OAUTH_LAST_OUTCOME.status = None
            oauth_ok = oauth_token_valid(token, rate_checker=RATE_BUDGET.allow)
            if not oauth_ok:
                outcome = getattr(_OAUTH_LAST_OUTCOME, 'status', None)
                if outcome == 'rate_limited':
                    self.send_rate_limited()
                    return
                if outcome == 'unavailable':
                    return self.respond(503, {'error': '認証サービスに一時的に接続できません'})

        strong_auth = is_api_key or oauth_ok
        bearer_ok = strong_auth or app_session
        authenticated = bearer_ok or cookie_ok

        if not authenticated:
            if not self.rate_allowed('unauth-entry', 180, 60):
                return
            return self.unauthorized()

        if not self.rate_allowed('owner-entry', 300, 60):
            return

        # A remembered cookie cannot mint a new one: relogin requires a real key.
        if self.path == '/app-api/session' and not strong_auth:
            return self.unauthorized()
        if self.path in ('/app-api/visual-backup-token', '/app-api/visual-backup-connections', '/app-api/visual-backup-revoke') and not (strong_auth or cookie_ok):
            return self.unauthorized()
        if self.path == WEB_SYNC_PATH and not (strong_auth or cookie_ok):
            return self.unauthorized()
        compute_route = (self.path in ('/app-api/run', '/app-api/party/start') or
                         (self.path == '/app-api/battles/simulate' and
                          os.environ.get('PVP_BATTLE_API_ENABLED') == '1') or
                         (self.path == MISSING_APP_PATH and missing_enabled()))
        if compute_route and not self.rate_allowed('compute-owner', 12, 60):
            return
        if self.path in ('/app-api/session', '/app-api/visual-backup-token') and not self.rate_allowed('issue-owner', 12, 60):
            return
        if is_app:
            if not APP_REQUEST_SLOTS.acquire(blocking=False):
                return self.respond(503, {'error': '処理中です。少し待って再試行してください'})
            try:
                self.app_request()
            finally:
                APP_REQUEST_SLOTS.release()
            return
        if self.path != '/mcp':
            return self.respond(404, {'error': 'Not found'})
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
            data = json.loads(self.read_body(size),
                              object_pairs_hook=_unique_object,
                              parse_constant=_reject_constant)
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
                acquired_slot = False
                if name in MCP_COMPUTE_TOOLS:
                    if not self.rate_allowed('compute-owner', 12, 60):
                        return
                    if not APP_REQUEST_SLOTS.acquire(blocking=False):
                        self.respond(503, {'error': '処理中です。少し待って再試行してください'})
                        return
                    acquired_slot = True
                try:
                    try:
                        output = call_tool(name, params.get('arguments') or {})
                        result = {'content':[{'type':'text','text':json.dumps(output,ensure_ascii=False,separators=(',',':'))}],
                                  'isError':False}
                    except ValueError as exc:
                        # User-input validation stays actionable without exposing
                        # unexpected infrastructure exceptions.
                        result = {'content':[{'type':'text','text':str(exc)}],
                                  'isError':True}
                    except Exception as exc:
                        logging.warning('MCP tool request failed: %s', type(exc).__name__)
                        result = {'content':[{'type':'text',
                                              'text':'処理に失敗しました。入力と接続状況を確認してください'}],
                                  'isError':True}
                    self.respond(200, {'jsonrpc':'2.0','id':id_,'result':result})
                finally:
                    if acquired_slot:
                        APP_REQUEST_SLOTS.release()
                return
            else:
                self.respond(200, {'jsonrpc':'2.0','id':id_,
                                   'error':{'code':-32601,'message':'Method not found'}})
                return
            self.respond(200, {'jsonrpc':'2.0','id':id_,'result':result})
        except Exception as exc:
            logging.warning('MCP request rejected: %s', type(exc).__name__)
            self.respond(400, {'jsonrpc':'2.0','id':None,
                               'error':{'code':-32700,'message':'Invalid JSON-RPC request'}})

if __name__ == '__main__':
    print(f'Local MCP test server: http://{HOST}:{PORT}/mcp', flush=True)
    print('Authenticated prototype server. HTTPS must be terminated by hosting platform.', flush=True)
    BoundedHTTPServer((HOST, PORT), Handler, max_workers=48).serve_forever()



