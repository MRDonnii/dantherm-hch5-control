"""API token that Home Assistant uses for the controller API.

The installer writes a token to gateway.env (DANTHERM_CONTROLLER_TOKEN). A
token generated in the WebUI is stored in the state directory and replaces
it; the old one stops working at once. update.sh reads the same file for its
post-update health check.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from pathlib import Path


class ControllerTokenStore:
    def __init__(self, path, env_token: str | None = None):
        self.path = Path(path)
        self.env_token = env_token or None
        self.lock = threading.Lock()
        self._cache: tuple[float, dict | None] | None = None

    def _stored(self) -> dict | None:
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            self._cache = None
            return None
        if self._cache and self._cache[0] == mtime:
            return self._cache[1]
        try:
            data = json.loads(self.path.read_text())
            data = data if isinstance(data, dict) and isinstance(data.get("token"), str) and len(data["token"]) >= 20 else None
        except (OSError, ValueError):
            data = None
        self._cache = (mtime, data)
        return data

    def current(self) -> str | None:
        stored = self._stored()
        return stored["token"] if stored else self.env_token

    def status(self) -> dict:
        stored = self._stored()
        token = self.current()
        return {
            "configured": bool(token),
            "source": "webui" if stored else ("installer" if self.env_token else "none"),
            "hint": f"…{token[-4:]}" if token else None,
            "created_at": stored.get("created_at") if stored else None,
            "created_by": stored.get("created_by") if stored else None,
        }

    def generate(self, user: str | None = None) -> str:
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"token": token, "created_at": time.time(), "created_by": user}))
            os.chmod(tmp, 0o600)
            tmp.replace(self.path)
            self._cache = None
        return token
