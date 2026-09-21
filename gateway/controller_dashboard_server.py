#!/usr/bin/env python3
"""Dashboard server variant that adds the authenticated HCH controller UI/API."""
from __future__ import annotations

import hmac
import json
import logging
import os
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from controller_core import ControllerError
from dashboard_server import ASSET_TYPES, DashboardHttpServer

LOG = logging.getLogger("passivelink-controller-web")
CONTROLLER_ASSETS = {"controller.css": "text/css; charset=utf-8", "controller.js": "text/javascript; charset=utf-8"}


class ControllerDashboardHttpServer(DashboardHttpServer):
    def __init__(self, *args, controller_runtime, **kwargs):
        super().__init__(*args, **kwargs)
        self.controller_runtime = controller_runtime
        self.controller_token = os.getenv("DANTHERM_CONTROLLER_TOKEN")

    def start(self) -> None:
        dashboard = self

        class Handler(BaseHTTPRequestHandler):
            def _session(self):
                return dashboard.auth.authenticate_cookie(self.headers.get("Cookie", ""))

            def _require_auth(self):
                session = self._session()
                if session is not None:
                    return session
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None

            def _read_json(self):
                try:
                    length = min(int(self.headers.get("Content-Length", "0")), 65536)
                    payload = json.loads(self.rfile.read(length) or b"{}")
                    return payload if isinstance(payload, dict) else None
                except (ValueError, TypeError, json.JSONDecodeError):
                    return None

            def _csrf(self, session):
                return session is not None and hmac.compare_digest(
                    self.headers.get("X-CSRF-Token", ""), session.get("csrf") or ""
                )

            def _machine_auth(self):
                if not dashboard.controller_token:
                    return False
                supplied = self.headers.get("Authorization", "")
                expected = f"Bearer {dashboard.controller_token}"
                return hmac.compare_digest(supplied, expected)

            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path == "/api/auth/status":
                    session = self._session()
                    self._json({
                        "configured": dashboard.auth.configured(),
                        "enabled": dashboard.auth.enabled(),
                        "authenticated": session is not None,
                        "username": session.get("username") if session else None,
                        "csrf": session.get("csrf") if session else None,
                    })
                    return
                if parsed.path in ("/login", "/setup"):
                    self._file(dashboard.web_root / "login.html", "text/html; charset=utf-8")
                    return
                if parsed.path in ("/assets/auth.css", "/assets/auth.js"):
                    target = dashboard.web_root / Path(parsed.path).name
                    self._file(target, ASSET_TYPES.get(target.suffix))
                    return
                if not dashboard.auth.configured():
                    self.send_response(302); self.send_header("Location", "/setup"); self.end_headers(); return
                if self._session() is None and dashboard.auth.enabled():
                    self.send_response(302); self.send_header("Location", "/login"); self.end_headers(); return

                if parsed.path in ("/", "/index.html"):
                    self._file(dashboard.web_root / "index.html", "text/html; charset=utf-8")
                elif parsed.path in ("/controller", "/controller.html"):
                    self._file(dashboard.web_root / "controller.html", "text/html; charset=utf-8")
                elif parsed.path == "/api/controller/state":
                    self._json(dashboard.controller_runtime.snapshot())
                elif parsed.path in ("/state.json", "/api"):
                    self._json(dashboard.snapshot())
                elif parsed.path == "/api/diagnostics/report":
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
                    sid, csrf = dashboard.auth.session(data["username"].strip())
                    return self._login_reply(sid, csrf)
                if self.path == "/api/auth/login":
                    data = self._read_json() or {}
                    ip = self.client_address[0]
                    if not dashboard.auth.allow_attempt(ip):
                        return self._json_error(429, "For mange forsøg. Vent fem minutter.")
                    if not dashboard.auth.verify(data.get("username", ""), data.get("password", "")):
                        dashboard.auth.failed(ip)
                        return self._json_error(401, "Forkert brugernavn eller adgangskode")
                    sid, csrf = dashboard.auth.session(data["username"])
                    return self._login_reply(sid, csrf)

                # Machine-to-machine HA heartbeat uses a dedicated bearer token.
                if self.path == "/api/controller/heartbeat":
                    if not self._machine_auth():
                        return self._json_error(401, "Controller token mangler eller er ugyldigt")
                    data = self._read_json() or {}
                    try:
                        return self._json(dashboard.controller_runtime.heartbeat(str(data.get("demand", "normal"))))
                    except ControllerError as error:
                        return self._json_error(400, str(error))

                session = self._require_auth()
                if session is None:
                    return
                if not self._csrf(session):
                    return self._json_error(403, "Ugyldig sikkerhedstoken")
                if self.path == "/api/auth/logout":
                    dashboard.auth.logout(self.headers.get("Cookie", "")); return self._json({"ok": True})
                if self.path == "/api/auth/settings":
                    data = self._read_json() or {}
                    try:
                        dashboard.auth.update(
                            data.get("current_password", ""), data.get("username", ""),
                            data.get("password", ""), data.get("enabled", True),
                        )
                    except PermissionError as error:
                        return self._json_error(401, str(error))
                    except ValueError as error:
                        return self._json_error(400, str(error))
                    return self._json({"ok": True})
                if self.path == "/api/controller/config":
                    data = self._read_json() or {}
                    try:
                        return self._json(dashboard.controller_runtime.configure(data))
                    except ControllerError as error:
                        return self._json_error(400, str(error))
                    except RuntimeError as error:
                        return self._json_error(503, str(error))
                if self.path != "/api/admin/action" or not dashboard.admin_token:
                    return self.send_error(405)
                body = json.dumps(self._read_json() or {}).encode()
                request = urllib.request.Request(
                    f"{dashboard.admin_url.rstrip('/')}/action", data=body, method="POST",
                    headers={"Authorization": f"Bearer {dashboard.admin_token}", "Content-Type": "application/json"},
                )
                try:
                    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=4) as response:
                        payload, status = response.read(), response.status
                except urllib.error.HTTPError as error:
                    payload, status = error.read(), error.code
                except OSError:
                    return self.send_error(503, "Admin helper unavailable")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers(); self.wfile.write(payload)

            def _login_reply(self, sid, csrf):
                body = json.dumps({"ok": True, "csrf": csrf}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Set-Cookie", f"dantherm_session={sid}; Path=/; HttpOnly; SameSite=Strict; Max-Age=43200")
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
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body)

            def log_message(self, format_, *args):
                LOG.debug(format_, *args)

        self.server = ThreadingHTTPServer((self.host, self.port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, name="dashboard-http", daemon=True)
        self.thread.start()

        def record_history():
            while not self.history_stop.is_set():
                self.snapshot()
                self.history_stop.wait(self.history.sample_seconds)

        self.history_stop.clear()
        self.history_thread = threading.Thread(target=record_history, name="dashboard-history", daemon=True)
        self.history_thread.start()
        LOG.info("Controller WebUI listening on %s:%s", self.host, self.port)
