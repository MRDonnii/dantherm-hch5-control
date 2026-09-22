import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from controller_observability import install_controller_observability


class FakeMaster:
    def bus_age(self):
        return 1.0


class FakeRuntime:
    def __init__(self):
        self.gateway_state = {
            "bus_traffic": True,
            "bus_last_frame_age": 1.0,
            "humidity": 48.0,
            "co2": 650,
            "outdoor_temp": 12.0,
            "extract_temp": 22.0,
            "supply_temp": 19.0,
        }
        self.master = FakeMaster()
        self.level = 3

    @staticmethod
    def _first(state, *keys):
        for key in keys:
            if state.get(key) is not None:
                return state[key]
        return None

    def snapshot(self):
        return {
            "active_master": "pi",
            "effective_source": "local_auto",
            "effective_level": self.level,
            "effective_reason": "RH/CO2 normal",
            "effective_bypass": "off",
            "cooling_state": "disabled",
            "quick_boost_active": False,
            "vacation_active": False,
            "night_active": False,
            "schedule_active": False,
            "fireplace": False,
            "smart_inputs_online": False,
            "smart_ha_rooms": {},
            "smart_controlling_room": None,
            "smart_controlling_metric": None,
            "measurements": {"room": 22.0, "outdoor": 12.0},
            "actual_supply_air_temperature": 19.0,
        }


class ControllerObservabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.old_log = os.environ.get("DANTHERM_DECISION_LOG")
        os.environ["DANTHERM_DECISION_LOG"] = str(Path(self.temp.name) / "decision-log.jsonl")

    def tearDown(self):
        if self.old_log is None:
            os.environ.pop("DANTHERM_DECISION_LOG", None)
        else:
            os.environ["DANTHERM_DECISION_LOG"] = self.old_log

    def test_snapshot_adds_health_comfort_and_deduplicated_decision_log(self):
        runtime = FakeRuntime()
        install_controller_observability(runtime)
        first = runtime.snapshot()
        second = runtime.snapshot()
        self.assertEqual(first["data_health"]["state"], "healthy")
        self.assertEqual(first["comfort_guard"]["state"], "comfortable")
        self.assertEqual(first["decision_log_size"], 1)
        self.assertEqual(second["decision_log_size"], 1)

        runtime.level = 5
        third = runtime.snapshot()
        self.assertEqual(third["decision_log_size"], 2)
        self.assertEqual(third["decision_log"][-1]["level"], 5)
        self.assertTrue(Path(os.environ["DANTHERM_DECISION_LOG"]).exists())

    def test_stale_bus_marks_local_data_stale_without_affecting_control(self):
        runtime = FakeRuntime()
        runtime.gateway_state["bus_traffic"] = False
        runtime.gateway_state["bus_last_frame_age"] = 30.0
        install_controller_observability(runtime)
        snapshot = runtime.snapshot()
        self.assertEqual(snapshot["data_health"]["state"], "stale")
        self.assertFalse(snapshot["data_health"]["bus_fresh"])
        self.assertEqual(snapshot["effective_level"], 3)


if __name__ == "__main__":
    unittest.main()
