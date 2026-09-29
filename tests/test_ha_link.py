import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from controller_dashboard_server import ControllerDashboardHttpServer
from webui_mail import AlarmMailer, MailService


class FakeConfig:
    def __init__(self, mode): self.data = {"mode": mode}


class FakeRuntime:
    def __init__(self, mode="smart_auto"):
        self.config = FakeConfig(mode); self.smart_inputs_received_at = None; self.smart_inputs_valid_for = 180
    def snapshot(self): return {"enabled": True, "active_master": "unknown", "mode": self.config.data["mode"]}


def server(tmp, mode="smart_auto"):
    return ControllerDashboardHttpServer("127.0.0.1", 0, {}, "Test", None, web_root=ROOT / "gateway/webui",
                                         history_path=Path(tmp) / "h.sqlite3", controller_runtime=FakeRuntime(mode))


class HaLinkTests(unittest.TestCase):
    def test_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = server(tmp)
            now = time.time()
            self.assertEqual(s.ha_link(now)["ha_link_state"], "waiting")          # just started
            self.assertEqual(s.ha_link(now + 400)["ha_link_state"], "never")
            s.ha_last_rejected, s.ha_rejected_ip = now + 390, "192.168.1.20"
            self.assertEqual(s.ha_link(now + 400)["ha_link_state"], "bad_token")  # old key after a new one
            s.ha_last_ok = now + 395
            link = s.ha_link(now + 400)
            self.assertEqual(link["ha_link_state"], "online")
            self.assertTrue(link["ha_link_required"])
            self.assertEqual(s.ha_link(now + 1000)["ha_link_state"], "offline")
            s.controller_runtime.smart_inputs_received_at = now + 990             # room data counts as contact
            self.assertEqual(s.ha_link(now + 1000)["ha_link_state"], "online")

    def test_alarm_only_when_smart_auto_depends_on_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = {"ha_link_state": "offline", "ha_link_required": True}
            mailer = AlarmMailer(MailService(Path(tmp) / "m.json"), lambda: state)
            self.assertNotIn("ha_offline", mailer.current_alarms(state, 1000))   # waits 5 minutes
            self.assertIn("ha_offline", mailer.current_alarms(state, 1400))
            state = {"ha_link_state": "bad_token", "ha_link_required": True}
            self.assertIn("forkert API-nøgle", mailer.current_alarms(state, 1500)["ha_offline"]["text"])
            self.assertEqual(mailer.current_alarms({"ha_link_state": "offline", "ha_link_required": False}, 1600), {})


if __name__ == "__main__":
    unittest.main()
