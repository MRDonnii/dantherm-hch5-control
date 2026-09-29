import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from event_log import ALARM_KINDS, EventLog
from webui_mail import AlarmMailer, MailService

BUS = {"bus_unhealthy": {"code": "bus_unhealthy", "severity": "critical", "text": "Ingen RS485", "since": 100}}


class EventLogTests(unittest.TestCase):
    def test_raised_and_cleared_with_duration_survive_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.json"
            log = EventLog(path)
            self.assertEqual([e["kind"] for e in log.sync_alarms(BUS, now=100)], ["alarm_raised"])
            self.assertEqual(log.sync_alarms(BUS, now=130), [])
            restarted = EventLog(path)  # a restart must not log the active alarm again
            self.assertEqual(restarted.sync_alarms(BUS, now=160), [])
            cleared = restarted.sync_alarms({}, now=400)
            self.assertEqual(cleared[0]["kind"], "alarm_cleared")
            self.assertEqual(cleared[0]["duration"], 300)
            self.assertEqual([e["kind"] for e in restarted.list()], ["alarm_cleared", "alarm_raised"])
            self.assertEqual(restarted.active_alarms(), [])

    def test_security_events_can_be_filtered_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = EventLog(Path(tmp) / "events.json")
            log.add("login", "Logget ind", user="admin")
            log.sync_alarms(BUS)
            self.assertEqual([e["kind"] for e in log.list(kinds=ALARM_KINDS)], ["alarm_raised"])

    def test_alarm_monitor_logs_without_mail(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = EventLog(Path(tmp) / "events.json")
            state = {"diagnostics_alarms": list(BUS.values())}
            AlarmMailer(MailService(Path(tmp) / "mail.json"), lambda: state, events=log).check(now=100)
            self.assertEqual(log.active_alarms()[0]["code"], "bus_unhealthy")


if __name__ == "__main__":
    unittest.main()
