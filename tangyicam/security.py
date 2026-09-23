"""LAN pairing and session validation. No Blender dependency; secrets stay in RAM."""
import collections
import hashlib
import hmac
import math
import secrets
import threading
import time

COOKIE_NAME = "tc_session"
SESSION_SECONDS = 8 * 60 * 60


class Pairing:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.RLock()
        self.sessions = {}
        self.attempts = collections.deque()
        self.admin_token = secrets.token_urlsafe(32)
        self.rotate()

    def _new_code(self):
        previous = getattr(self, "code", None)
        while True:
            self.code = "%06d" % secrets.randbelow(1000000)
            if self.code != previous:
                break
        self.deadline = self.clock() + 600

    def rotate(self):
        with self.lock:
            self.sessions.clear()
            self._new_code()

    def status(self):
        with self.lock:
            return {"code": self.code, "expires_in": max(0, int(self.deadline - self.clock()))}

    def pair(self, code, address):
        with self.lock:
            now = self.clock()
            while self.attempts and now - self.attempts[0][0] >= 60:
                self.attempts.popleft()
            if len(self.attempts) >= 30 or sum(ip == address for _, ip in self.attempts) >= 6:
                return None, "too_many_attempts"
            self.attempts.append((now, address))
            if now >= self.deadline:
                return None, "expired_code"
            if not isinstance(code, str) or not code.isascii() or not code.isdigit() or len(code) != 6 or not hmac.compare_digest(code, self.code):
                return None, "invalid_code"
            self.sessions = {k: exp for k, exp in self.sessions.items() if exp > now}
            if len(self.sessions) >= 8:
                return None, "session_limit"
            token = secrets.token_urlsafe(32)
            self.sessions[self._digest(token)] = now + SESSION_SECONDS
            self._new_code()  # A displayed code can only be redeemed once.
            return token, None

    @staticmethod
    def _digest(token):
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def valid(self, token):
        if not isinstance(token, str) or not token.isascii() or not 20 <= len(token) <= 100:
            return False
        with self.lock:
            return self.sessions.get(self._digest(token), 0) > self.clock()

    def revoke(self, token):
        if isinstance(token, str) and token.isascii():
            with self.lock:
                self.sessions.pop(self._digest(token), None)


def validate_control(value):
    """Reject malformed/oversized input before it touches Blender state."""
    if not isinstance(value, dict) or len(value) > 32:
        return None
    out = {}
    ranges = {"mx": (-4, 4), "my": (-4, 4), "mz": (-4, 4), "zoom": (-1, 1),
              "boost": (1, 4), "speed": (0.1, 8), "gain": (0.5, 3),
              "tscale": (0.05, 1), "lens": (1, 500), "scrub": (0, 1)}
    for name, item in value.items():
        if name in ranges:
            if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item):
                return None
            lo, hi = ranges[name]
            out[name] = max(lo, min(hi, item))
        elif name == "q":
            if item is None:
                out[name] = None
            elif (isinstance(item, list) and len(item) == 4 and
                  all(type(x) in (int, float) and math.isfinite(x) and abs(x) <= 2 for x in item)):
                norm = sum(x*x for x in item) ** 0.5
                if norm < 0.01:
                    return None
                out[name] = [x / norm for x in item]
            else:
                return None
        elif name in ("horizon", "recenter", "home", "rec"):
            if item is None and name == "rec":
                out[name] = None
            elif type(item) is bool:
                out[name] = item
            else:
                return None
        elif name in ("seq", "stab"):
            if type(item) is not int or not 0 <= item <= (5 if name == "stab" else 2**53 - 1):
                return None
            out[name] = item
        elif name in ("mode", "shade"):
            allowed = ("WALK", "FPV", "DOLLY") if name == "mode" else ("SOLID", "MATERIAL", "RENDERED", "WIREFRAME")
            if item not in allowed:
                return None
            out[name] = item
        elif name == "shot":
            if not isinstance(item, str) or len(item) > 200:
                return None
            out[name] = item
        elif name == "key":
            if not isinstance(item, dict) or item.get("cmd") not in ("add", "del", "build", "export", "goto"):
                return None
            arg = item.get("arg", 0)
            if type(arg) is not int or not 0 <= arg <= 100000:
                return None
            out[name] = {"cmd": item["cmd"], "arg": arg}
        else:
            return None
    return out
