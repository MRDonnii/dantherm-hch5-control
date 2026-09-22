import http.cookiejar
import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import Mock

import sys

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))
from controller_dashboard_server import ControllerDashboardHttpServer


class FakeRuntime:
    def __init__(self): self.calls = []
    def snapshot(self): return {"enabled": False}
    def configure(self, patch): self.calls.append(("config", patch)); return {"enabled": patch.get("enabled", False)}
    def heartbeat(self, demand): self.calls.append(("heartbeat", demand)); return {"ha_demand": demand}


class ControllerDashboardTests(unittest.TestCase):
    def test_setup_returns_json_when_auth_store_cannot_be_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = FakeRuntime()
            server = ControllerDashboardHttpServer(
                "127.0.0.1", 0, {}, "Test", None,
                web_root=ROOT / "gateway/webui", history_path=Path(tmp) / "history.sqlite3",
                controller_runtime=runtime,
            )
            server.auth.path = Path(tmp) / "auth.json"
            server.auth.save = Mock(side_effect=PermissionError("read-only auth store"))
            server.start(); port = server.server.server_address[1]
            try:
                setup = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/auth/setup",
                    data=json.dumps({"username": "admin", "password": "long-test-password"}).encode(),
                    headers={"Content-Type": "application/json"}, method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(setup)
                self.assertEqual(error.exception.code, 500)
                self.assertEqual(
                    json.load(error.exception),
                    {"error": "Kunne ikke gemme login-konfigurationen"},
                )
            finally:
                server.stop()

    def test_config_needs_session_and_csrf_while_heartbeat_needs_machine_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get("DANTHERM_CONTROLLER_TOKEN")
            os.environ["DANTHERM_CONTROLLER_TOKEN"] = "test-machine-token"
            runtime = FakeRuntime()
            server = ControllerDashboardHttpServer(
                "127.0.0.1", 0, {}, "Test", None,
                web_root=ROOT / "gateway/webui", history_path=Path(tmp) / "history.sqlite3",
                controller_runtime=runtime,
            )
            server.auth.path = Path(tmp) / "auth.json"
            server.auth.save("admin", "long-test-password", True)
            server.start(); port = server.server.server_address[1]
            try:
                unauth = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/controller/config", data=b"{}",
                    headers={"Content-Type": "application/json"}, method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as error: urllib.request.urlopen(unauth)
                self.assertEqual(error.exception.code, 401)
                heartbeat = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/controller/heartbeat",
                    data=b'{"demand":"high"}', method="POST",
                    headers={"Content-Type": "application/json", "Authorization": "Bearer test-machine-token"},
                )
                self.assertEqual(urllib.request.urlopen(heartbeat).status, 200)
                self.assertEqual(runtime.calls[-1], ("heartbeat", "high"))
                state_request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/controller/state",
                    headers={"Authorization": "Bearer test-machine-token"},
                )
                self.assertFalse(json.load(urllib.request.urlopen(state_request))["enabled"])
                opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
                login = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/auth/login",
                    data=json.dumps({"username": "admin", "password": "long-test-password"}).encode(),
                    headers={"Content-Type": "application/json"}, method="POST",
                )
                csrf = json.load(opener.open(login))["csrf"]
                config = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/controller/config", data=b'{"enabled":false}', method="POST",
                    headers={"Content-Type": "application/json", "X-CSRF-Token": csrf},
                )
                self.assertEqual(opener.open(config).status, 200)
                self.assertEqual(runtime.calls[-1], ("config", {"enabled": False}))
            finally:
                server.stop()
                if old is None: os.environ.pop("DANTHERM_CONTROLLER_TOKEN", None)
                else: os.environ["DANTHERM_CONTROLLER_TOKEN"] = old


if __name__ == "__main__": unittest.main()
