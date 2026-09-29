import http.cookiejar
import json
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from controller_dashboard_server import ControllerDashboardHttpServer
from balancing_store import BalancingStore
from event_log import EventLog
from webui_auth import AuthManager
from webui_mail import AlarmMailer, MailService
from webui_permissions import admin_action_allowed, config_allowed

PASSWORD = "long-test-password"


class FakeRuntime:
    def __init__(self): self.calls = []; self.state = {"enabled": True}
    def snapshot(self): return dict(self.state)
    def configure(self, patch, source="api"): self.calls.append(patch); return {"enabled": True, **patch}


class FakeSmtp:
    sent = []
    def __init__(self, settings): self.settings = settings
    def send_message(self, message): FakeSmtp.sent.append(message)
    def quit(self): pass


class AuthStoreTests(unittest.TestCase):
    def test_version_one_store_is_read_as_single_admin(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "auth.json"
            auth = AuthManager(path)
            salt = "ab" * 16
            path.write_text(json.dumps({"version": 1, "username": "owner", "salt": salt,
                                        "password_hash": auth._hash(PASSWORD, salt), "enabled": True}))
            self.assertTrue(auth.verify("owner", PASSWORD))
            self.assertEqual(auth.role("owner"), "admin")
            # Reading never rewrites the old file (update.sh checks its hash).
            self.assertEqual(json.loads(path.read_text())["version"], 1)

    def test_roles_expiry_and_last_admin_protection(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth = AuthManager(Path(tmp) / "auth.json")
            auth.save("admin", PASSWORD, True)
            auth.create_user("tekniker", PASSWORD, "technician", "tek@example.com", time.time() + 3600)
            auth.create_user("familie", PASSWORD, "user")
            self.assertTrue(auth.verify("TEKNIKER", PASSWORD))
            self.assertEqual({u["role"] for u in auth.list_users()}, {"admin", "technician", "user"})
            with self.assertRaises(ValueError):
                auth.create_user("familie", PASSWORD, "user")
            with self.assertRaises(ValueError):
                auth.delete_user("admin")
            with self.assertRaises(ValueError):
                auth.update_user("admin", role="user")

            sid, _ = auth.session("tekniker")
            self.assertEqual(auth.authenticate_cookie(f"dantherm_session={sid}")["role"], "technician")
            auth.update_user("tekniker", role="user")
            self.assertEqual(auth.authenticate_cookie(f"dantherm_session={sid}")["role"], "user")
            auth.update_user("tekniker", disabled=True)
            self.assertIsNone(auth.authenticate_cookie(f"dantherm_session={sid}"))
            self.assertFalse(auth.verify("tekniker", PASSWORD))

            data = json.loads((Path(tmp) / "auth.json").read_text())
            next(u for u in data["users"] if u["username"] == "familie")["expires_at"] = time.time() - 1
            (Path(tmp) / "auth.json").write_text(json.dumps(data))
            self.assertFalse(auth.verify("familie", PASSWORD))

    def test_reset_token_is_single_use(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth = AuthManager(Path(tmp) / "auth.json")
            auth.save("admin", PASSWORD, True)
            auth.create_user("bruger", PASSWORD, "user", "bruger@example.com")
            self.assertIsNone(auth.create_reset_token("admin"))  # no e-mail on file
            user, token = auth.create_reset_token("BRUGER@example.com")
            self.assertEqual(user["username"], "bruger")
            self.assertTrue(auth.reset_token_valid(token))
            auth.reset_password(token, "another-long-password")
            self.assertTrue(auth.verify("bruger", "another-long-password"))
            with self.assertRaises(PermissionError):
                auth.reset_password(token, "third-long-password")


class PermissionTests(unittest.TestCase):
    def test_plain_user_is_limited_to_daily_controls(self):
        self.assertEqual(config_allowed("user", {"mode": "manual", "manual_level": 3}), [])
        self.assertEqual(config_allowed("user", {"mode": "manual", "co2_setpoint": 900}), ["co2_setpoint"])
        self.assertEqual(config_allowed("technician", {"co2_setpoint": 900}), [])
        self.assertTrue(admin_action_allowed("user", "check_update"))
        self.assertFalse(admin_action_allowed("user", "reboot"))
        self.assertTrue(admin_action_allowed("technician", "reboot"))


class MailTests(unittest.TestCase):
    def setUp(self):
        FakeSmtp.sent = []

    def service(self, tmp):
        mail = MailService(Path(tmp) / "mail.json", smtp_factory=FakeSmtp)
        mail.update({"enabled": True, "host": "smtp.example.com", "from_address": "hch5@example.com",
                     "recipients": "a@example.com; b@example.com", "password": "secret"})
        return mail

    def test_password_is_never_public_and_kept_on_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            mail = self.service(tmp)
            public = mail.update({"port": 465, "security": "ssl"})
            self.assertNotIn("password", public)
            self.assertTrue(public["password_set"])
            self.assertEqual(mail.load()["password"], "secret")
            self.assertEqual(public["recipients"], ["a@example.com", "b@example.com"])
            with self.assertRaises(ValueError):
                mail.update({"recipients": "not-an-address"})

    def test_alarm_mail_on_new_and_resolved_alarm(self):
        with tempfile.TemporaryDirectory() as tmp:
            mail = self.service(tmp)
            mail.send_async = lambda to, subject, body, kind="mail": mail.send_now(to, subject, body, kind=kind)
            state = {"diagnostics_alarms": [{"code": "bus_unhealthy", "severity": "critical", "text": "Ingen RS485", "since": 1}]}
            mailer = AlarmMailer(mail, lambda: state)
            self.assertEqual([k for k, _ in mailer.check(now=1000)], ["raised"])
            self.assertEqual(mailer.check(now=1030), [])
            self.assertIn("KRITISK", FakeSmtp.sent[0]["Subject"])
            state["diagnostics_alarms"] = [{"code": "recovery_mismatch", "severity": "info", "text": "x", "since": 2}]
            self.assertEqual([k for k, _ in mailer.check(now=1060)], ["resolved"])  # info is below "warning"
            self.assertEqual(len(FakeSmtp.sent), 2)


class HttpRoleTests(unittest.TestCase):
    def test_roles_are_enforced_over_http(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = FakeRuntime()
            server = ControllerDashboardHttpServer(
                "127.0.0.1", 0, {}, "Test", None,
                web_root=ROOT / "gateway/webui", history_path=Path(tmp) / "history.sqlite3",
                controller_runtime=runtime,
            )
            server.auth.path = Path(tmp) / "auth.json"
            server.auth.session_path = Path(tmp) / "sessions.json"
            server.mail = MailService(Path(tmp) / "mail.json", smtp_factory=FakeSmtp)
            server.balancing = BalancingStore(Path(tmp) / "balancing.json")
            server.events = EventLog(Path(tmp) / "events.json")
            server.auth.save("admin", PASSWORD, True)
            server.start(); port = server.server.server_address[1]
            base = f"http://127.0.0.1:{port}"

            def login(name):
                opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
                reply = json.load(opener.open(urllib.request.Request(
                    f"{base}/api/auth/login", data=json.dumps({"username": name, "password": PASSWORD}).encode(),
                    headers={"Content-Type": "application/json"}, method="POST")))
                return opener, reply["csrf"]

            def post(session, path, payload):
                opener, csrf = session
                request = urllib.request.Request(f"{base}{path}", data=json.dumps(payload).encode(), method="POST",
                                                 headers={"Content-Type": "application/json", "X-CSRF-Token": csrf})
                try:
                    response = opener.open(request)
                    return response.status, json.load(response)
                except urllib.error.HTTPError as error:
                    return error.code, json.load(error)

            try:
                admin = login("admin")
                status, _ = post(admin, "/api/users/create", {"username": "tekniker", "password": PASSWORD, "role": "technician"})
                self.assertEqual(status, 200)
                self.assertEqual(post(admin, "/api/users/create", {"username": "bruger", "password": PASSWORD, "role": "user"})[0], 200)
                self.assertEqual(post(admin, "/api/users/delete", {"username": "admin"})[0], 400)

                user = login("bruger")
                auth_status = json.load(user[0].open(f"{base}/api/auth/status"))
                self.assertEqual(auth_status["role"], "user")
                self.assertNotIn("configure", auth_status["permissions"])
                self.assertEqual(post(user, "/api/controller/config", {"mode": "manual"})[0], 200)
                self.assertEqual(post(user, "/api/controller/config", {"co2_setpoint": 900})[0], 403)
                self.assertEqual(post(user, "/api/users/create", {"username": "x12", "password": PASSWORD})[0], 403)
                self.assertEqual(post(user, "/api/mail/settings", {"host": "evil"})[0], 403)
                self.assertEqual(post(user, "/api/admin/action", {"action": "reboot"})[0], 403)
                self.assertEqual(post(user, "/api/balancing/project", {"rooms": []})[0], 403)
                user_events = json.load(user[0].open(f"{base}/api/events"))
                self.assertTrue(all(e["kind"].startswith("alarm") for e in user_events["events"]))

                tech = login("tekniker")
                self.assertEqual(post(tech, "/api/controller/config", {"co2_setpoint": 900})[0], 200)
                self.assertEqual(post(tech, "/api/balancing/project", {"rooms": [{"name": "Bad", "type": "bathroom", "area": 6, "height": 2.4, "extract": True}]})[0], 200)
                admin_events = json.load(admin[0].open(f"{base}/api/events"))
                self.assertIn("login", {e["kind"] for e in admin_events["events"]})
                self.assertEqual(post(tech, "/api/users/create", {"username": "x12", "password": PASSWORD})[0], 403)
                status, mail = post(tech, "/api/mail/settings", {"enabled": True, "host": "smtp.example.com",
                                                                 "from_address": "hch5@example.com", "recipients": ["a@example.com"]})
                self.assertEqual(status, 200)
                self.assertTrue(mail["configured"])
                self.assertEqual(post(tech, "/api/mail/test", {})[0], 200)
                self.assertEqual(len(FakeSmtp.sent), 1)
            finally:
                server.stop()


if __name__ == "__main__":
    unittest.main()
