"""Short-lived browser credentials issued only after existing MCP authentication.

These tokens authorize app endpoints only, never the MCP gateway itself.
The URL fragment keeps the credential out of HTTP URLs and access logs.
"""
import base64
import hashlib
import hmac
import secrets
import threading
import time
from http.cookies import SimpleCookie
from pvpoke_auth_store import CredentialStore


class AppAccess:
    def __init__(self, ttl=3600, capacity=32):
        self.ttl, self.capacity = ttl, capacity
        self._tokens = {}
        self._lock = threading.Lock()

    def issue(self, origin):
        with self._lock:
            now = time.monotonic()
            self._tokens = {k: until for k, until in self._tokens.items() if until > now}
            while len(self._tokens) >= self.capacity:
                del self._tokens[min(self._tokens, key=self._tokens.get)]
            token = secrets.token_urlsafe(32)
            self._tokens[token] = now + self.ttl
        return {'url': origin + '/app#access=' + token, 'expires_in_seconds': self.ttl}

    def valid(self, raw):
        if not isinstance(raw, str) or not raw.startswith('Bearer '):
            return False
        with self._lock:
            token = raw[7:]
            until = self._tokens.get(token, 0)
            if until <= time.monotonic():
                self._tokens.pop(token, None)
                return False
            return True

    def revoke(self, raw):
        with self._lock:
            self._tokens.pop(raw.removeprefix('Bearer '), None)


class BrowserLogin:
    """Signed app cookie with durable per-session revocation; never authorizes /mcp.

    The 30-day cookie survives Railway restarts without storing the root key
    in browser storage. Only credential fingerprints are persisted. Changing PVP_API_KEY revokes it.
    """
    COOKIE_NAME = 'pvpoke_app_login'

    def __init__(self, api_key, ttl=30 * 24 * 60 * 60, store=None):
        self.ttl = ttl
        self.store = store or CredentialStore()
        self._secret = hashlib.sha256(('pvpoke-browser-login-v1:' + api_key).encode()).digest()

    def _sign(self, payload):
        return base64.urlsafe_b64encode(
            hmac.new(self._secret, payload.encode('ascii'), hashlib.sha256).digest()
        ).decode('ascii').rstrip('=')

    def _cookie(self, value, max_age, secure):
        flags = '; Secure' if secure else ''
        return (f'{self.COOKIE_NAME}={value}; Max-Age={max_age}; Path=/app-api; '
                f'HttpOnly; SameSite=Strict{flags}')

    def issue(self, secure=True):
        expires = int(time.time()) + self.ttl
        payload = f'v1.{expires}.{secrets.token_urlsafe(16)}'
        value = payload + '.' + self._sign(payload)
        self.store.active(value, 'browser', expires)
        return self._cookie(value, self.ttl, secure)

    def clear(self, secure=True):
        return self._cookie('', 0, secure)

    def revoke(self, cookie_header):
        if self.valid(cookie_header):
            cookies = SimpleCookie()
            cookies.load(cookie_header)
            self.store.revoke(self.store.fingerprint(cookies[self.COOKIE_NAME].value), 'browser')

    def valid(self, cookie_header):
        if not cookie_header or len(cookie_header) > 4096:
            return False
        try:
            cookies = SimpleCookie()
            cookies.load(cookie_header)
            item = cookies.get(self.COOKIE_NAME)
            if item is None:
                return False
            parts = item.value.split('.')
            if len(parts) != 4 or parts[0] != 'v1':
                return False
            expires = int(parts[1])
            now = time.time()
            if not now < expires <= now + self.ttl:
                return False
            payload = '.'.join(parts[:3])
            return (hmac.compare_digest(self._sign(payload), parts[3]) and
                    self.store.active(item.value, 'browser', expires))
        except (ValueError, TypeError):
            return False
