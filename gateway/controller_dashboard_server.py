#!/usr/bin/env python3
"""Dashboard server variant that adds the authenticated HCH controller UI/API."""
from __future__ import annotations

import gzip
import hmac
import json
import logging
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from controller_core import ControllerError
from dashboard_server import ASSET_TYPES, DashboardHttpServer, WEBUI_CSP
from balancing_store import BalancingError, BalancingStore
from controller_token import ControllerTokenStore
from event_log import ALARM_KINDS, EventLog
from webui_auth import ROLE_LABELS
from webui_mail import AlarmMailer, MailError, MailService
from webui_permissions import admin_action_allowed, can, capabilities, config_allowed

LOG = logging.getLogger("passivelink-controller-web")
CONTROLLER_ASSETS = {
    "controller.css": "text/css; charset=utf-8",
    "controller.js": "text/javascript; charset=utf-8",
    "master_status.js": "text/javascript; charset=utf-8",
    # Sniffer assets
    "sniffer.html": "text/html; charset=utf-8",
    "sniffer.js": "text/javascript; charset=utf-8",
    "sniffer.css": "text/css; charset=utf-8",
}


# Vite names these after their content, so a browser may keep them for good.
IMMUTABLE_ASSET = re.compile(r"^/assets/v2-[A-Za-z0-9_-]+\.(?:js|css)$")
COMPRESSIBLE_TYPES = ("application/json", "text/", "image/svg+xml")
# Left out of /api/controller/state?compact=1. The History page and the
# legacy controller page ask for the full answer.
COMPACT_OMITTED_KEYS = ("decision_log", "change_log")


class ControllerDashboardHttpServer(DashboardHttpServer):
    def __init__(self, *args, controller_runtime, **kwargs):
        super().__init__(*args, **kwargs)
        self.controller_runtime = controller_runtime
        self.tokens = ControllerTokenStore(
            os.getenv("DANTHERM_CONTROLLER_TOKEN_FILE", str(self.auth.path.with_name("controller-token.json"))),
            os.getenv("DANTHERM_CONTROLLER_TOKEN"),
        )
        self.mail = MailService(os.getenv(
            "DANTHERM_WEBUI_MAIL_FILE", str(self.auth.path.with_name("webui-mail.json"))))
        self.events = EventLog(os.getenv(
            "DANTHERM_WEBUI_EVENTS_FILE", str(self.auth.path.with_name("webui-events.json"))))
        self.balancing = BalancingStore(os.getenv(
            "DANTHERM_WEBUI_BALANCING_FILE", str(self.auth.path.with_name("webui-balancing.json"))))
        # Contact from Home Assistant (any request with the right API key) and
        # requests with a wrong key, e.g. after a new key was generated.
        self.started_at = time.time()
        self.ha_last_ok: float | None = None
        self.ha_last_rejected: float | None = None
        self.ha_rejected_ip: str | None = None
        self.alarm_mailer = AlarmMailer(self.mail, lambda: {**controller_runtime.snapshot(), **self.ha_link()}, events=self.events)

    def ha_link(self, now: float | None = None) -> dict:
        """Whether Home Assistant is talking to the controller API right now."""
        now = time.time() if now is None else now
        runtime = self.controller_runtime
        contacts = [t for t in (self.ha_last_ok, getattr(runtime, "smart_inputs_received_at", None)) if t]
        last = max(contacts) if contacts else None
        lease = max(180, int(getattr(runtime, "smart_inputs_valid_for", 180) or 180) + 60)
        config = getattr(getattr(runtime, "config", None), "data", {}) or {}
        rejected = self.ha_last_rejected
        if last is not None and now - last <= lease:
            state = "online"
        elif rejected and now - rejected <= 600 and (last is None or rejected > last):
            state = "bad_token"
        elif last is not None:
            state = "offline"
        elif now - self.started_at < 300:
            state = "waiting"
        else:
            state = "never"
        return {
            "ha_link_state": state,
            "ha_link_last_contact": round(last, 1) if last else None,
            "ha_link_age_seconds": round(now - last) if last else None,
            "ha_link_required": config.get("mode") == "smart_auto",
            "ha_link_rejected_at": round(rejected, 1) if rejected else None,
            "ha_link_rejected_ip": self.ha_rejected_ip,
        }

    def reset_base_url(self) -> str:
        configured = self.mail.load().get("base_url")
        if configured:
            return configured
        # Never trust the request's Host header for a link sent by mail.
        host = self._system_snapshot().get("network_ipv4") or f"{socket.gethostname()}.local"
        return f"http://{host}:{self.port}"

    def stop(self):
        self.alarm_mailer.stop()
        super().stop()

    def start(self) -> None:
        dashboard = self

        class Handler(BaseHTTPRequestHandler):
            def _session(self):
                return dashboard.auth.authenticate_cookie(self.headers.get("Cookie", ""))

            def _require_auth(self):
                session = self._session()
                if session is not None:
                    return session
                self._login_required()
                return None

            def _login_required(self):
                # The WebUI sends the browser to the login page on this answer,
                # e.g. after a restart has ended a session without "Husk mig".
                body = json.dumps({"error": "Log ind igen", "login_required": True}).encode()
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body)

            def _read_json(self):
                try:
                    length = min(int(self.headers.get("Content-Length", "0")), 262144)
                    payload = json.loads(self.rfile.read(length) or b"{}")
                    return payload if isinstance(payload, dict) else None
                except (ValueError, TypeError, json.JSONDecodeError):
                    return None

            def _csrf(self, session):
                return session is not None and hmac.compare_digest(
                    self.headers.get("X-CSRF-Token", ""), session.get("csrf") or ""
                )

            def _need(self, session, capability):
                if can(session.get("role", "user"), capability):
                    return True
                self._json_error(403, "Din brugerrolle har ikke adgang til denne funktion")
                return False

            def _require(self, capability):
                session = self._require_auth()
                if session is None:
                    return None
                return session if self._need(session, capability) else None

            def _machine_auth(self):
                supplied = self.headers.get("Authorization", "")
                if not supplied.startswith("Bearer "):
                    return False
                token = dashboard.tokens.current()
                ok = bool(token) and hmac.compare_digest(supplied, f"Bearer {token}")
                if ok:
                    dashboard.ha_last_ok = time.time()
                else:
                    dashboard.ha_last_rejected = time.time()
                    dashboard.ha_rejected_ip = self.client_address[0]
                return ok

            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path == "/api/controller/state" and self._machine_auth():
                    self._json(self._controller_state(dashboard.controller_runtime.snapshot(), parsed))
                    return
                if parsed.path == "/api/onewire/water" and self.client_address[0] in ("127.0.0.1", "::1"):
                    # Read by the local 1-Wire service so its flow/return follow the WebUI.
                    self._json(dashboard.controller_runtime.onewire.water_assignment())
                    return
                if parsed.path == "/api/auth/status":
                    session = self._session()
                    role = session.get("role", "user") if session else None
                    user = dashboard.auth.user(session["username"]) if session else None
                    mail = dashboard.mail.load()
                    self._json({
                        "configured": dashboard.auth.configured(),
                        "enabled": dashboard.auth.enabled(),
                        "authenticated": session is not None,
                        "username": session.get("username") if session else None,
                        "csrf": session.get("csrf") if session else None,
                        "remembered": bool(session and session.get("remember")),
                        "role": role,
                        "role_label": ROLE_LABELS.get(role) if role else None,
                        "permissions": capabilities(role) if role else [],
                        "email": (user or {}).get("email", "") if session else None,
                        "password_reset_available": bool(dashboard.mail.configured(mail) and mail.get("password_reset_enabled")),
                    })
                    return
                if parsed.path == "/api/auth/reset/check":
                    token = parse_qs(parsed.query).get("token", [""])[0]
                    self._json({"valid": dashboard.auth.reset_token_valid(token)})
                    return
                if parsed.path in ("/login", "/setup", "/forgot", "/reset"):
                    self._file(dashboard.web_root / "login.html", "text/html; charset=utf-8")
                    return
                if parsed.path in ("/assets/auth.css", "/assets/auth.js", "/assets/favicon.svg", "/assets/apple-touch-icon.png", "/assets/brand-mark.svg"):
                    target = dashboard.web_root / Path(parsed.path).name
                    self._file(target, ASSET_TYPES.get(target.suffix))
                    return
                if not dashboard.auth.configured():
                    self.send_response(302); self.send_header("Location", "/setup"); self.end_headers(); return
                if self._session() is None and dashboard.auth.enabled():
                    if parsed.path in ("/state.json", "/api", "/history.json") or parsed.path.startswith("/api/"):
                        # A redirect would hand fetch() the login page instead of JSON.
                        self._login_required(); return
                    self.send_response(302); self.send_header("Location", "/login"); self.end_headers(); return

                if parsed.path in ("/", "/index.html"):
                    self._file(dashboard.web_root / "index.html", "text/html; charset=utf-8")
                elif parsed.path in ("/controller", "/controller.html"):
                    if self._require("configure") is not None:
                        self._file(dashboard.web_root / "controller.html", "text/html; charset=utf-8")
                elif parsed.path == "/sniffer":
                    # Sniffer UI (technicians and administrators)
                    if self._require("diagnostics") is not None:
                        self._file(dashboard.web_root / "sniffer.html", "text/html; charset=utf-8")
                elif parsed.path == "/api/sniffer/status":
                    if self._require("diagnostics") is None:
                        return
                    self._json(getattr(dashboard, "sniffer", {}).status() if getattr(dashboard, "sniffer", None) else {"running": False})
                elif parsed.path == "/api/sniffer/recent":
                    if self._require("diagnostics") is None:
                        return
                    recent = getattr(dashboard, "sniffer", None)
                    self._json(recent.recent_frames() if recent else [])
                elif parsed.path == "/api/users":
                    if self._require("users") is None:
                        return
                    self._json({"users": dashboard.auth.list_users(), "roles": ROLE_LABELS})
                elif parsed.path == "/api/events":
                    session = self._require_auth()
                    if session is None:
                        return
                    # Sign-ins and user changes are for administrators only.
                    kinds = None if can(session.get("role", "user"), "users") else ALARM_KINDS
                    try:
                        limit = max(1, min(500, int(parse_qs(parsed.query).get("limit", ["200"])[0])))
                    except ValueError:
                        limit = 200
                    self._json({"events": dashboard.events.list(kinds=kinds, limit=limit),
                                "active": dashboard.events.active_alarms()})
                elif parsed.path == "/api/balancing":
                    if self._require("configure") is not None:
                        self._json(dashboard.balancing.state())
                elif parsed.path == "/api/balancing/report":
                    if self._require("configure") is None:
                        return
                    report = dashboard.balancing.get_report(parse_qs(parsed.query).get("id", [""])[0])
                    self._json(report) if report else self._json_error(404, "Rapporten findes ikke")
                elif parsed.path == "/api/integration":
                    if self._require("configure") is None:
                        return
                    self._json({**dashboard.tokens.status(), "port": dashboard.port,
                                "address": dashboard._system_snapshot().get("network_ipv4")})
                elif parsed.path == "/api/mail":
                    if self._require("mail") is None:
                        return
                    self._json(dashboard.mail.public())
                elif parsed.path == "/api/controller/state":
                    self._json(self._controller_state({**dashboard.controller_runtime.snapshot(), **dashboard.ha_link()}, parsed))
                elif parsed.path in ("/state.json", "/api"):
                    self._json({**dashboard.snapshot(), **dashboard.ha_link(),
                                "weather": dashboard.controller_runtime.weather_snapshot()})
                elif parsed.path == "/api/diagnostics/report":
                    if self._require("diagnostics") is not None:
                        self._diagnostic_report()
                elif parsed.path == "/history.json":
                    name = parse_qs(parsed.query).get("range", ["24h"])[0]
                    self._json({"range": name, "samples": dashboard.history.query(name)})
                elif parsed.path.startswith("/assets/"):
                    name = Path(parsed.path).name
                    target = dashboard.web_root / name
                    content_type = CONTROLLER_ASSETS.get(name) or ASSET_TYPES.get(target.suffix)
                    self._file(target, content_type) if content_type else self.send_error(404)
                else:
                    self.send_error(404)

            @staticmethod
            def _controller_state(state, parsed):
                if parse_qs(parsed.query).get("compact") == ["1"]:
                    # Pollers every few seconds do not show the logs, which
                    # are about 90 % of the answer.
                    for key in COMPACT_OMITTED_KEYS:
                        state.pop(key, None)
                return state

            def _diagnostic_report(self):
                if not dashboard.admin_token:
                    return self.send_error(503, "Diagnostic helper unavailable")
                request = urllib.request.Request(
                    f"{dashboard.admin_url.rstrip('/')}/diagnostics",
                    headers={"Authorization": f"Bearer {dashboard.admin_token}"},
                )
                try:
                    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=60) as response:
                        helper_payload = response.read(8 * 1024 * 1024 + 1)
                        disposition = response.headers.get("Content-Disposition", "")
                except (OSError, urllib.error.URLError):
                    return self.send_error(503, "Diagnostic helper unavailable")
                if len(helper_payload) > 8 * 1024 * 1024:
                    return self.send_error(413, "Diagnostic report too large")
                snapshot = dashboard.snapshot()
                snapshot["controller"] = dashboard.controller_runtime.snapshot()
                safe_snapshot = {
                    key: ("[REDACTED]" if any(word in key.lower() for word in
                          ("token", "password", "secret", "cookie", "authorization")) else value)
                    for key, value in snapshot.items()
                }
                state = json.dumps(safe_snapshot, indent=2, ensure_ascii=False, default=str).encode("utf-8")
                body = helper_payload + b"\n\n==================== PASSIVELINK CURRENT STATE ====================\n" + state + b"\n"
                filename = "dantherm-debug.txt"
                if 'filename="' in disposition:
                    filename = disposition.split('filename="', 1)[1].split('"', 1)[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body)

            def do_POST(self):
                if self.path == "/api/auth/setup":
                    if dashboard.auth.configured():
                        return self._json_error(409, "Allerede konfigureret")
                    data = self._read_json() or {}
                    try:
                        dashboard.auth.save(data.get("username", ""), data.get("password", ""), True)
                    except ValueError as error:
                        return self._json_error(400, str(error))
                    except OSError:
                        LOG.exception("Could not save the initial WebUI user")
                        return self._json_error(500, "Kunne ikke gemme login-konfigurationen")
                    try:
                        remember = data.get("remember") is True
                        sid, csrf = dashboard.auth.session(data["username"].strip(), remember=remember)
                    except OSError:
                        LOG.exception("Could not create the initial WebUI session")
                        return self._json_error(500, "Kunne ikke gemme login-sessionen")
                    return self._login_reply(sid, csrf)

                if self.path == "/api/auth/login":
                    data = self._read_json() or {}
                    ip = self.client_address[0]
                    if not dashboard.auth.allow_attempt(ip):
                        return self._json_error(429, "For mange forsøg. Vent fem minutter.")
                    try:
                        verified = dashboard.auth.verify(data.get("username", ""), data.get("password", ""))
                    except (OSError, ValueError):
                        LOG.exception("Could not read the WebUI authentication store")
                        return self._json_error(500, "Kunne ikke læse login-konfigurationen")
                    if not verified:
                        dashboard.auth.failed(ip)
                        dashboard.events.add("login_failed", "Mislykket login", user=str(data.get("username", ""))[:64], ip=ip)
                        return self._json_error(401, "Forkert brugernavn eller adgangskode")
                    try:
                        remember = data.get("remember") is True
                        sid, csrf = dashboard.auth.session(data["username"], remember=remember)
                    except OSError:
                        LOG.exception("Could not create the WebUI login session")
                        return self._json_error(500, "Kunne ikke gemme login-sessionen")
                    dashboard.auth.record_login(data["username"])
                    dashboard.events.add("login", "Logget ind", user=str(data["username"])[:64], ip=ip)
                    return self._login_reply(sid, csrf)

                if self.path == "/api/auth/forgot":
                    data = self._read_json() or {}
                    key = f"forgot:{self.client_address[0]}"
                    if not dashboard.auth.allow_attempt(key):
                        return self._json_error(429, "For mange forsøg. Vent fem minutter.")
                    dashboard.auth.failed(key)
                    mail = dashboard.mail.load()
                    if not (dashboard.mail.configured(mail) and mail.get("password_reset_enabled")):
                        return self._json_error(503, "Nulstilling via mail er ikke sat op. Kontakt administratoren.")
                    found = dashboard.auth.create_reset_token(str(data.get("identifier", ""))[:254])
                    if found:
                        user, token = found
                        dashboard.mail.send_password_reset(
                            user["email"], user["username"], f"{dashboard.reset_base_url()}/reset?token={token}")
                    # Same answer whether or not the user exists.
                    return self._json({"ok": True})

                if self.path == "/api/auth/reset":
                    data = self._read_json() or {}
                    try:
                        who = dashboard.auth.reset_password(str(data.get("token", "")), str(data.get("password", "")))
                        dashboard.events.add("password_reset", "Adgangskode nulstillet via mail-link", user=who)
                    except PermissionError as error:
                        return self._json_error(400, str(error))
                    except (ValueError, KeyError) as error:
                        return self._json_error(400, str(error).strip("'"))
                    return self._json({"ok": True})

                # Machine-to-machine endpoints for Home Assistant. HA sends
                # intent and room measurements only; Pi remains source of truth.
                if self.path in ("/api/controller/heartbeat", "/api/controller/command", "/api/controller/inputs", "/api/controller/signals"):
                    if not self._machine_auth():
                        return self._json_error(401, "Controller token mangler eller er ugyldigt")
                    data = self._read_json() or {}
                    try:
                        if self.path == "/api/controller/heartbeat":
                            return self._json(dashboard.controller_runtime.heartbeat(str(data.get("demand", "normal"))))
                        if self.path == "/api/controller/command":
                            return self._json(dashboard.controller_runtime.configure(data, source="home_assistant"))
                        if self.path == "/api/controller/signals":
                            return self._json(dashboard.controller_runtime.external_signals(data))
                        return self._json(dashboard.controller_runtime.room_inputs(data))
                    except ControllerError as error:
                        return self._json_error(400, str(error))
                    except RuntimeError as error:
                        return self._json_error(503, str(error))

                session = self._require_auth()
                if session is None:
                    return
                if not self._csrf(session):
                    return self._json_error(403, "Ugyldig sikkerhedstoken")
                if self.path == "/api/auth/logout":
                    dashboard.auth.logout(self.headers.get("Cookie", "")); return self._json({"ok": True})
                if self.path == "/api/auth/settings":
                    data = self._read_json() or {}
                    enabled = data.get("enabled") if can(session.get("role"), "login_switch") else None
                    try:
                        dashboard.auth.update(
                            data.get("current_password", ""), data.get("username", ""),
                            data.get("password", ""), enabled, acting=session.get("username"),
                            email=data.get("email"),
                        )
                    except PermissionError as error:
                        return self._json_error(401, str(error))
                    except ValueError as error:
                        return self._json_error(400, str(error))
                    return self._json({"ok": True})
                if self.path.startswith("/api/users/"):
                    if not self._need(session, "users"):
                        return
                    return self._users_action(session, self._read_json() or {})
                if self.path.startswith("/api/balancing/"):
                    if not self._need(session, "configure"):
                        return
                    data = self._read_json() or {}
                    who = session.get("username")
                    try:
                        if self.path == "/api/balancing/project":
                            dashboard.balancing.save_project(data, who)
                            return self._json(dashboard.balancing.state())
                        if self.path == "/api/balancing/report":
                            summary = dashboard.balancing.add_report(data, who)
                            return self._json({"ok": True, "report": summary, **dashboard.balancing.state()})
                        if self.path == "/api/balancing/report/delete":
                            if not dashboard.balancing.delete_report(str(data.get("id", ""))):
                                return self._json_error(404, "Rapporten findes ikke")
                            return self._json(dashboard.balancing.state())
                    except BalancingError as error:
                        return self._json_error(400, str(error))
                    except OSError:
                        LOG.exception("Could not save balancing data")
                        return self._json_error(500, "Kunne ikke gemme indreguleringen")
                    return self.send_error(404)
                if self.path in ("/api/integration/token/generate", "/api/integration/token/reveal"):
                    if not self._need(session, "configure"):
                        return
                    if self.path.endswith("/generate"):
                        try:
                            token = dashboard.tokens.generate(session.get("username"))
                        except OSError:
                            LOG.exception("Could not save the controller token")
                            return self._json_error(500, "Kunne ikke gemme API-nøglen")
                        dashboard.events.add("token_generated", "Ny API-nøgle til Home Assistant genereret", user=session.get("username"))
                        return self._json({"token": token, **dashboard.tokens.status()})
                    token = dashboard.tokens.current()
                    if not token:
                        return self._json_error(404, "Der er ingen API-nøgle endnu")
                    return self._json({"token": token, **dashboard.tokens.status()})
                if self.path in ("/api/mail/settings", "/api/mail/test"):
                    if not self._need(session, "mail"):
                        return
                    data = self._read_json() or {}
                    try:
                        if self.path == "/api/mail/settings":
                            return self._json(dashboard.mail.update(data))
                        recipients = data.get("recipients")
                        dashboard.mail.send_test([str(r) for r in recipients] if isinstance(recipients, list) else None)
                        return self._json({"ok": True, "mail": dashboard.mail.public()})
                    except ValueError as error:
                        return self._json_error(400, str(error))
                    except MailError as error:
                        return self._json_error(502, str(error))
                    except OSError:
                        LOG.exception("Could not save mail settings")
                        return self._json_error(500, "Kunne ikke gemme mailindstillingerne")
                # Sniffer control endpoints (authenticated + CSRF, technicians)
                if self.path.startswith("/api/sniffer/") and not self._need(session, "diagnostics"):
                    return
                if self.path == "/api/sniffer/start":
                    # start a read-only capture
                    sniffer = getattr(dashboard, "sniffer", None)
                    if sniffer is None:
                        return self._json_error(503, "Sniffer unavailable")
                    return self._json(sniffer.start())
                if self.path == "/api/sniffer/stop":
                    sniffer = getattr(dashboard, "sniffer", None)
                    if sniffer is None:
                        return self._json_error(503, "Sniffer unavailable")
                    return self._json(sniffer.stop())
                if self.path == "/api/sniffer/marker":
                    sniffer = getattr(dashboard, "sniffer", None)
                    if sniffer is None:
                        return self._json_error(503, "Sniffer unavailable")
                    data = self._read_json() or {}
                    name = data.get("name") or data.get("marker") or "manual"
                    try:
                        return self._json(sniffer.marker(str(name)))
                    except Exception as e:
                        return self._json_error(500, str(e))
                if self.path == "/api/controller/config":
                    data = self._read_json() or {}
                    denied = config_allowed(session.get("role", "user"), data)
                    if denied:
                        return self._json_error(403, "Din brugerrolle må ikke ændre: " + ", ".join(denied))
                    try:
                        return self._json(dashboard.controller_runtime.configure(data, source=f"webui:{session.get('username') or 'ukendt'}"))
                    except ControllerError as error:
                        return self._json_error(400, str(error))
                    except RuntimeError as error:
                        return self._json_error(503, str(error))
                if self.path != "/api/admin/action":
                    return self.send_error(405)
                admin_action = self._read_json() or {}
                if not admin_action_allowed(session.get("role", "user"), str(admin_action.get("action", ""))):
                    return self._json_error(403, "Kun teknikere og administratorer kan udføre denne handling")
                if not dashboard.admin_token:
                    return self.send_error(405)
                body = json.dumps(admin_action).encode()
                timeout = 45 if admin_action.get("action") in {"wifi_scan", "wifi_connect"} else 4
                request = urllib.request.Request(
                    f"{dashboard.admin_url.rstrip('/')}/action", data=body, method="POST",
                    headers={"Authorization": f"Bearer {dashboard.admin_token}", "Content-Type": "application/json"},
                )
                try:
                    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=timeout) as response:
                        payload, status = response.read(), response.status
                except urllib.error.HTTPError as error:
                    payload, status = error.read(), error.code
                except OSError:
                    return self.send_error(503, "Admin helper unavailable")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers(); self.wfile.write(payload)

            def _users_action(self, session, data):
                auth = dashboard.auth
                name = str(data.get("username", ""))
                try:
                    if self.path == "/api/users/create":
                        user = auth.create_user(name, str(data.get("password", "")), str(data.get("role", "user")),
                                                data.get("email", ""), data.get("expires_at"))
                        dashboard.events.add("user_created", f"Bruger oprettet som {user['role_label']}", user=user["username"], by=session.get("username"))
                        return self._json({"ok": True, "user": user, "users": auth.list_users()})
                    if self.path == "/api/users/update":
                        changes = {key: data[key] for key in ("role", "email", "disabled", "expires_at") if key in data}
                        if data.get("password"):
                            changes["password"] = str(data["password"])
                        if name.lower() == str(session.get("username", "")).lower() and (
                                changes.get("role", "admin") != "admin" or changes.get("disabled")):
                            return self._json_error(400, "Du kan ikke fjerne din egen administratoradgang")
                        user = auth.update_user(name, **changes)
                        what = ", ".join(sorted("adgangskode" if key == "password" else key for key in changes)) or "intet"
                        dashboard.events.add("user_changed", f"Bruger ændret: {what}", user=user["username"], by=session.get("username"))
                        return self._json({"ok": True, "user": user, "users": auth.list_users()})
                    if self.path == "/api/users/delete":
                        if name.lower() == str(session.get("username", "")).lower():
                            return self._json_error(400, "Du kan ikke slette dig selv")
                        auth.delete_user(name)
                        dashboard.events.add("user_deleted", "Bruger slettet", user=name, by=session.get("username"))
                        return self._json({"ok": True, "users": auth.list_users()})
                    if self.path == "/api/users/send-reset":
                        if not dashboard.mail.ready():
                            return self._json_error(503, "Mailservicen er ikke sat op")
                        found = auth.create_reset_token(name)
                        if not found:
                            return self._json_error(400, "Brugeren har ingen e-mailadresse eller er ikke aktiv")
                        user, token = found
                        dashboard.mail.send_password_reset(
                            user["email"], user["username"], f"{dashboard.reset_base_url()}/reset?token={token}")
                        return self._json({"ok": True})
                except KeyError as error:
                    return self._json_error(404, str(error).strip("'"))
                except ValueError as error:
                    return self._json_error(400, str(error))
                except OSError:
                    LOG.exception("Could not save the WebUI user store")
                    return self._json_error(500, "Kunne ikke gemme brugerne")
                return self.send_error(404)

            def _login_reply(self, sid, csrf):
                max_age = dashboard.auth.session_max_age(sid)
                body = json.dumps({"ok": True, "csrf": csrf, "max_age": max_age}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Set-Cookie", f"dantherm_session={sid}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body)

            def _json_error(self, status, message):
                body = json.dumps({"error": message}).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body)

            def _json(self, payload):
                self._body(json.dumps(payload, separators=(",", ":"), default=str).encode(), "application/json")

            def _file(self, path, content_type):
                try:
                    body = path.read_bytes()
                except OSError:
                    self.send_error(404); return
                self._body(body, content_type)

            def _body(self, body, content_type):
                immutable = IMMUTABLE_ASSET.match(urlparse(self.path).path) is not None
                compress = (
                    len(body) >= 1024 and str(content_type or "").startswith(COMPRESSIBLE_TYPES)
                    and "gzip" in self.headers.get("Accept-Encoding", "")
                )
                if compress:
                    body = gzip.compress(body, compresslevel=5)
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "public, max-age=31536000, immutable" if immutable else "no-store")
                if compress:
                    self.send_header("Content-Encoding", "gzip")
                self.send_header("Vary", "Accept-Encoding")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", WEBUI_CSP)
                self.send_header("Content-Length", str(len(body)))
                try:
                    self.end_headers(); self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    # The browser gave up (poll timeout, page closed); nothing to answer.
                    LOG.debug("Client %s closed the connection before %s was sent", self.client_address[0], self.path)

            def log_message(self, format_, *args):
                LOG.debug(format_, *args)

        self.server = ThreadingHTTPServer((self.host, self.port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, name="dashboard-http", daemon=True)
        self.thread.start()

        self.start_background()
        self.alarm_mailer.site_name = self.device_name or "HCH5 Control"
        self.alarm_mailer.start()
        LOG.info("Controller WebUI listening on %s:%s", self.host, self.port)
