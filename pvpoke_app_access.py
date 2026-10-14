"""Short-lived browser credentials issued only after existing MCP authentication.

These tokens authorize app endpoints only, never the MCP gateway itself.
The URL fragment keeps the credential out of HTTP URLs and access logs.
"""
import secrets
import threading
import time


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
