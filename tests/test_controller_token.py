import http.cookiejar
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from controller_dashboard_server import ControllerDashboardHttpServer
from controller_token import ControllerTokenStore
from event_log import EventLog

PASSWORD = "long-test-password"


class FakeRuntime:
    def snapshot(self): return {"enabled": True, "active_master": "unknown"}


class TokenStoreTests(unittest.TestCase):
    def test_generated_token_replaces_installer_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ControllerTokenStore(Path(tmp) / "t.json", "installer-token-123456789")
            self.assertEqual(store.status()["source"], "installer")
            token = store.generate("tek")
            self.assertNotEqual(token, "installer-token-123456789")
            self.assertEqual(store.current(), token)
            self.assertEqual(store.status()["source"], "webui")
            self.assertEqual(oct((Path(tmp) / "t.json").stat().st_mode & 0o777), "0o600")
            self.assertEqual(ControllerTokenStore(Path(tmp) / "t.json", None).current(), token)  # survives restart


class TokenHttpTests(unittest.TestCase):
    def test_generate_over_http_switches_machine_auth(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get("DANTHERM_CONTROLLER_TOKEN")
            os.environ["DANTHERM_CONTROLLER_TOKEN"] = "installer-token-123456789"
            try:
                server = ControllerDashboardHttpServer("127.0.0.1", 0, {}, "Test", None, web_root=ROOT / "gateway/webui",
                                                       history_path=Path(tmp) / "h.sqlite3", controller_runtime=FakeRuntime())
            finally:
                if old is None: os.environ.pop("DANTHERM_CONTROLLER_TOKEN", None)
                else: os.environ["DANTHERM_CONTROLLER_TOKEN"] = old
            server.auth.path = Path(tmp) / "auth.json"
            server.auth.session_path = Path(tmp) / "sessions.json"
            server.tokens.path = Path(tmp) / "controller-token.json"
            server.events = EventLog(Path(tmp) / "events.json")
            server.auth.save("admin", PASSWORD, True)
            server.auth.create_user("bruger", PASSWORD, "user")
            server.start(); base = f"http://127.0.0.1:{server.server.server_address[1]}"

            def state(token):
                request = urllib.request.Request(f"{base}/api/controller/state", headers={"Authorization": f"Bearer {token}"})
                # Without a valid token the request falls through to the login redirect.
                try:
                    body = urllib.request.urlopen(request).read()
                except urllib.error.HTTPError:
                    return False
                try:
                    return json.loads(body).get("active_master") == "unknown"
                except ValueError:
                    return False

            def login(name):
                opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
                csrf = json.load(opener.open(urllib.request.Request(f"{base}/api/auth/login", method="POST",
                    data=json.dumps({"username": name, "password": PASSWORD}).encode(), headers={"Content-Type": "application/json"})))["csrf"]
                return opener, csrf

            def post(session, path):
                opener, csrf = session
                try:
                    response = opener.open(urllib.request.Request(f"{base}{path}", data=b"{}", method="POST",
                                                                  headers={"Content-Type": "application/json", "X-CSRF-Token": csrf}))
                    return response.status, json.load(response)
                except urllib.error.HTTPError as error:
                    return error.code, None

            try:
                self.assertTrue(state("installer-token-123456789"))
                self.assertEqual(post(login("bruger"), "/api/integration/token/generate")[0], 403)
                admin = login("admin")
                status, body = post(admin, "/api/integration/token/generate")
                self.assertEqual(status, 200)
                self.assertEqual(body["source"], "webui")
                self.assertTrue(state(body["token"]))
                self.assertFalse(state("installer-token-123456789"))  # the old token stops working
                self.assertEqual(post(admin, "/api/integration/token/reveal")[1]["token"], body["token"])
                self.assertIn("token_generated", {e["kind"] for e in server.events.list()})
            finally:
                server.stop()


if __name__ == "__main__":
    unittest.main()
