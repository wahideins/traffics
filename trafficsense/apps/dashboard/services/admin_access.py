"""Kebijakan akses panel admin (murni Python, mudah diuji).

* Bila TRAFFICSENSE_ADMIN_PASSWORD diatur: butuh login dengan sandi itu (cookie bertanda tangan).
* Bila tidak diatur: panel hanya dapat dibuka dari komputer server itu sendiri (localhost),
  dan ditolak bila ada tanda permintaan melewati proxy (X-Forwarded-For), karena proxy
  di komputer yang sama akan membuat semua klien terlihat seperti localhost.
"""
import hmac
import threading
import time

LOCAL_ADDRESSES = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}

OK, LOGIN, FORBIDDEN = "ok", "login", "forbidden"


def decide(*, password_set, remote_addr, forwarded, authenticated):
    if password_set:
        return OK if authenticated else LOGIN
    if remote_addr in LOCAL_ADDRESSES and not forwarded:
        return OK
    return FORBIDDEN


def password_matches(candidate, expected):
    if not expected:
        return False
    return hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))


class LoginThrottle:
    """Batasi percobaan login salah per alamat (di memori; cukup untuk satu proses)."""

    def __init__(self, max_failures=5, window=300.0, clock=time.monotonic):
        self._max, self._window, self._clock = max_failures, window, clock
        self._failures = {}
        self._lock = threading.Lock()

    def _recent(self, key):
        now = self._clock()
        recent = [t for t in self._failures.get(key, []) if now - t < self._window]
        self._failures[key] = recent
        return recent

    def allowed(self, key):
        with self._lock:
            return len(self._recent(key)) < self._max

    def fail(self, key):
        with self._lock:
            self._recent(key).append(self._clock())

    def reset(self, key):
        with self._lock:
            self._failures.pop(key, None)
