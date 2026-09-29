"""Persistent event log: alarms raised and cleared, sign-ins and user changes.

Stored as a capped JSON file next to the login store. Which alarms are active
is kept in the same file, so a restart does not log a still-active alarm as
new again.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

MAX_EVENTS = 500
ALARM_KINDS = ("alarm_raised", "alarm_cleared")
SECURITY_KINDS = ("login", "login_failed", "user_created", "user_changed", "user_deleted", "password_reset", "token_generated")


class EventLog:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.events: list[dict] = []
        self.active: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return
        if isinstance(data, dict):
            self.events = [e for e in data.get("events", []) if isinstance(e, dict)][-MAX_EVENTS:]
            self.active = {str(k): v for k, v in (data.get("active") or {}).items() if isinstance(v, dict)}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"events": self.events[-MAX_EVENTS:], "active": self.active}, ensure_ascii=False))
            os.chmod(tmp, 0o600)
            tmp.replace(self.path)
        except OSError:
            pass  # the log must never take the WebUI down

    def add(self, kind: str, text: str, **fields) -> dict:
        event = {"time": round(fields.pop("at", None) or time.time(), 1), "kind": kind, "text": str(text)[:300]}
        event.update({k: v for k, v in fields.items() if v is not None})
        with self.lock:
            self.events.append(event)
            self.events = self.events[-MAX_EVENTS:]
            self._save()
        return event

    def sync_alarms(self, alarms: dict[str, dict], now: float | None = None) -> list[dict]:
        """Log alarms that appeared or cleared since the last call."""
        now = time.time() if now is None else now
        logged = []
        with self.lock:
            before = dict(self.active)
        for code, alarm in alarms.items():
            if code not in before:
                logged.append(self.add("alarm_raised", alarm.get("text", code), at=now, code=code,
                                       severity=alarm.get("severity"), since=alarm.get("since")))
        for code, alarm in before.items():
            if code not in alarms:
                started = alarm.get("since") or alarm.get("logged_at")
                logged.append(self.add("alarm_cleared", alarm.get("text", code), at=now, code=code,
                                       severity=alarm.get("severity"), since=started,
                                       duration=round(now - float(started)) if started else None))
        if logged or set(before) != set(alarms):
            with self.lock:
                self.active = {code: {"text": a.get("text"), "severity": a.get("severity"),
                                      "since": a.get("since") or before.get(code, {}).get("since") or now}
                               for code, a in alarms.items()}
                self._save()
        return logged

    def list(self, *, kinds: tuple[str, ...] | None = None, limit: int = 200) -> list[dict]:
        with self.lock:
            events = [e for e in self.events if kinds is None or e.get("kind") in kinds]
        return list(reversed(events[-limit:]))

    def active_alarms(self) -> list[dict]:
        with self.lock:
            return [{"code": code, **values} for code, values in sorted(self.active.items(), key=lambda i: i[1].get("since") or 0)]
