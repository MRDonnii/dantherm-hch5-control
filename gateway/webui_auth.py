"""Small local authentication store with salted hashes and server-side sessions."""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from http.cookies import SimpleCookie
from pathlib import Path

SHORT_SESSION_SECONDS = 12 * 60 * 60
REMEMBER_SESSION_SECONDS = 30 * 24 * 60 * 60


class AuthManager:
    def __init__(self, path="/var/lib/dantherm-hch5-ha/webui-auth.json"):
        self.path = Path(path)
        self.session_path = self.path.with_name("webui-sessions.json")
        self.lock = threading.Lock()
        self.sessions = {}
        self.failures = {}
        self._load_sessions()

    def load(self):
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return None

    def configured(self):
        return bool(self.load())

    def enabled(self):
        data = self.load()
        return bool(data and data.get("enabled", True))

    @staticmethod
    def _hash(password, salt):
        return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 310000).hex()

    def verify(self, username, password):
        data = self.load()
        return bool(
            data
            and hmac.compare_digest(str(data.get("username", "")), username)
            and hmac.compare_digest(str(data.get("password_hash", "")), self._hash(password, data["salt"]))
        )

    def save(self, username, password, enabled=True):
        if len(username.strip()) < 3 or len(password) < 10:
            raise ValueError("Brugernavn skal være mindst 3 tegn og adgangskoden mindst 10 tegn")
        salt = secrets.token_hex(16)
        data = {
            "version": 1,
            "username": username.strip(),
            "salt": salt,
            "password_hash": self._hash(password, salt),
            "enabled": bool(enabled),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    def update(self, current_password, username, password, enabled):
        data = self.load()
        if not data or not self.verify(data["username"], current_password):
            raise PermissionError("Forkert nuværende adgangskode")
        self.save(username or data["username"], password or current_password, enabled)
        self.sessions.clear()
        self._save_sessions()

    def allow_attempt(self, ip):
        now = time.time()
        values = [t for t in self.failures.get(ip, []) if now - t < 300]
        self.failures[ip] = values
        return len(values) < 5

    def failed(self, ip):
        self.failures.setdefault(ip, []).append(time.time())

    def _load_sessions(self):
        try:
            payload = json.loads(self.session_path.read_text())
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(payload, dict):
            return
        now = time.time()
        for sid, session in payload.items():
            if not isinstance(session, dict) or not session.get("remember"):
                continue
            try:
                expires = float(session["expires"])
            except (KeyError, TypeError, ValueError):
                continue
            if expires <= now:
                continue
            self.sessions[str(sid)] = {
                "username": str(session.get("username", "")),
                "csrf": str(session.get("csrf", "")),
                "expires": expires,
                "remember": True,
            }

    def _save_sessions(self):
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        remembered = {
            sid: session
            for sid, session in self.sessions.items()
            if session.get("remember") and float(session.get("expires", 0)) > now
        }
        if not remembered:
            try:
                self.session_path.unlink(missing_ok=True)
            except OSError:
                pass
            return
        tmp = self.session_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(remembered, separators=(",", ":")))
        os.chmod(tmp, 0o600)
        tmp.replace(self.session_path)

    def session(self, username, remember=False):
        sid = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        lifetime = REMEMBER_SESSION_SECONDS if remember else SHORT_SESSION_SECONDS
        self.sessions[sid] = {
            "username": username,
            "csrf": csrf,
            "expires": time.time() + lifetime,
            "remember": bool(remember),
        }
        if remember:
            self._save_sessions()
        return sid, csrf

    def session_max_age(self, sid):
        session = self.sessions.get(sid) or {}
        return REMEMBER_SESSION_SECONDS if session.get("remember") else SHORT_SESSION_SECONDS

    def authenticate_cookie(self, header):
        data = self.load()
        if not data:
            return None
        if not data.get("enabled", True):
            return {"username": data.get("username"), "csrf": None}
        try:
            cookie = SimpleCookie(header)
            sid = cookie["dantherm_session"].value
            session = self.sessions.get(sid)
        except (KeyError, AttributeError):
            return None
        if not session or session["expires"] < time.time():
            self.sessions.pop(sid, None)
            self._save_sessions()
            return None
        # Keep normal sessions sliding for 12 hours. Remembered sessions are
        # fixed at 30 days from login, matching the UI promise exactly.
        if not session.get("remember"):
            session["expires"] = time.time() + SHORT_SESSION_SECONDS
        return session

    def logout(self, header):
        try:
            cookie = SimpleCookie(header)
            self.sessions.pop(cookie["dantherm_session"].value, None)
            self._save_sessions()
        except (KeyError, AttributeError):
            pass
