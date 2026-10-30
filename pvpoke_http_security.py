"""Bound application workers as defense in depth behind the production proxy."""
import hmac
import logging
import socket
import threading
import time
from http.server import ThreadingHTTPServer


def safe_equal(left, right):
    if not isinstance(left, str) or len(left) > 4096 or not left.isascii():
        return False
    return hmac.compare_digest(left.encode('ascii'), right.encode('ascii'))


class RateBudget:
    """Fixed set of owner budgets; attacker input cannot grow this mapping."""
    def __init__(self):
        self._buckets = {}
        self._lock = threading.Lock()

    def allow(self, name, count, seconds):
        now = time.monotonic()
        with self._lock:
            tokens, before = self._buckets.get(name, (count, now))
            tokens = min(count, tokens + (now - before) * count / seconds)
            allowed = tokens >= 1
            self._buckets[name] = (tokens - 1 if allowed else tokens, now)
            return allowed


class BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32

    def __init__(self, *args, max_workers=24, socket_timeout=10, request_timeout=90, **kwargs):
        self._slots = threading.BoundedSemaphore(max_workers)
        self.socket_timeout, self.request_timeout = socket_timeout, request_timeout
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            try:
                request.settimeout(0.1)
                request.sendall(b'HTTP/1.0 503 Service Unavailable\r\nRetry-After: 1\r\n'
                                b'Content-Length: 0\r\nConnection: close\r\n\r\n')
            except OSError:
                pass
            self.shutdown_request(request)
            return
        request.settimeout(self.socket_timeout)
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        # Absolute deadline also bounds clients trickling bytes before idle expiry.
        def expire():
            try:
                request.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        timer = threading.Timer(self.request_timeout, expire)
        timer.daemon = True
        timer.start()
        try:
            super().process_request_thread(request, client_address)
        finally:
            timer.cancel()
            self._slots.release()

    def handle_error(self, request, client_address):
        import sys
        if isinstance(sys.exception(), (BrokenPipeError, ConnectionResetError, TimeoutError)):
            return
        # Avoid dumping attacker-controlled request data or credentials in traces.
        logging.error('HTTP handler failed: %s', type(sys.exception()).__name__)
