import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from controller_core import ControllerError, HardwareAdapter
from controller_runtime import ControllerRuntime


class ControllerRuntimeTests(unittest.TestCase):
    def make_runtime(self, gateway_state=None):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return ControllerRuntime(
            gateway_state=gateway_state or {},
            hardware=HardwareAdapter(),
            state_path=Path(temp.name) / "controller.json",
        )

    @staticmethod
    def decision(runtime, rooms):
        runtime.room_inputs({
            "source": "home_assistant", "valid_for_s": 180, "rooms": rooms,
        })
        return runtime.smart_requested_level

    def test_afterheat_outdoor_lockout_is_reported_at_15_c_and_above(self):
        # HAC1 never heats at 15 C outdoor or above; report it as a lockout.
        for outdoor, expected in ((14.15, False), (15.0, True), (15.63, True), (None, None)):
            with self.subTest(outdoor=outdoor):
                state = {} if outdoor is None else {"outdoor_temp": outdoor}
                snapshot = self.make_runtime(state).snapshot()
                self.assertIs(snapshot["actual_afterheat_outdoor_lockout"], expected)
                self.assertEqual(snapshot["afterheat_outdoor_cutoff"], 15.0)

    def test_smart_auto_can_request_every_level_1_to_6_from_co2(self):
        expected = {250: 1, 700: 2, 800: 3, 900: 4, 1100: 5, 1300: 6}
        for co2, level in expected.items():
            with self.subTest(co2=co2):
                runtime = self.make_runtime()
                self.assertEqual(self.decision(runtime, {"Room": {"co2": co2}}), level)

    def test_bathroom_rh_uses_separate_threshold_and_level_cap(self):
        runtime = self.make_runtime()
        runtime.config.configure({
            "bathroom_rh_setpoint": 65,
            "bathroom_rh_hysteresis": 5,
            "bathroom_max_level": 4,
        })
        # A bathroom can be humid without immediately forcing full boost.
        self.assertLessEqual(self.decision(runtime, {"Bath": {"humidity": 58}}), 4)
        self.assertEqual(self.decision(runtime, {"Bath": {"humidity": 78}}), 4)
        # A shower-like fast rise is still recognised, but remains capped.
        runtime = self.make_runtime()
        runtime.config.configure({"bathroom_max_level": 4})
        runtime._room_rh_history["Bath"].append((time.time() - 300, 48.0))
        self.assertLessEqual(self.decision(runtime, {"Bath": {"humidity": 68}}), 4)
        self.assertEqual(runtime.smart_controlling_metric, "rh_rise")

    def test_normal_room_rh_keeps_global_policy(self):
        runtime = self.make_runtime()
        self.assertGreaterEqual(
            self.decision(runtime, {"Utility": {"humidity": 58, "room_type": "normal"}}),
            5,
        )

    def test_room_priority_changes_mild_response(self):
        cases = (("low", 3), ("auto", 4), ("normal", 4), ("high", 5), ("critical", 6))
        for priority, expected in cases:
            with self.subTest(priority=priority):
                runtime = self.make_runtime()
                self.assertEqual(
                    self.decision(runtime, {"Room": {"co2": 900, "priority": priority}}),
                    expected,
                )

    def test_monitor_only_room_does_not_control_but_remains_diagnostic(self):
        runtime = self.make_runtime()
        level = self.decision(runtime, {
            "Monitor": {"co2": 2000, "control": False, "priority": "critical"},
            "Control": {"co2": 700, "control": True},
        })
        self.assertEqual(level, 2)
        snapshot = runtime.snapshot()
        self.assertEqual(snapshot["smart_max_co2"], 2000)
        self.assertEqual(snapshot["smart_max_co2_room"], "Monitor")

    def test_severe_auto_room_beats_mild_high_priority_room(self):
        runtime = self.make_runtime()
        self.assertEqual(self.decision(runtime, {
            "Severe": {"co2": 1300, "priority": "auto"},
            "Mild": {"co2": 850, "priority": "high"},
        }), 6)
        self.assertEqual(runtime.smart_controlling_room, "Severe")

    def test_unit_sensor_is_combined_with_home_assistant_rooms(self):
        runtime = self.make_runtime({"co2": 1300, "humidity": 40})
        self.assertEqual(self.decision(runtime, {"Bedroom": {"co2": 600}}), 6)
        self.assertEqual(runtime.smart_controlling_room, "HCH5 / lokale sensorer")

    def test_invalid_metadata_measurement_and_room_count_are_rejected(self):
        runtime = self.make_runtime()
        cases = (
            {"Room": {"co2": "bad"}},
            {"Room": {"co2": 900, "priority": "urgent"}},
            {f"Room {index}": {"co2": 800} for index in range(33)},
        )
        for rooms in cases:
            with self.assertRaises(ControllerError):
                self.decision(runtime, rooms)

    def test_stale_smart_input_falls_back_to_local_auto(self):
        runtime = self.make_runtime({"co2": 600, "humidity": 40})
        runtime.config.configure({"mode": "smart_auto", "downshift_delay_seconds": 30})
        self.decision(runtime, {"Bedroom": {"co2": 1600}})
        runtime.engine.current_auto_level = 6
        runtime.engine.boost_until = 0
        runtime.engine.last_level_change = 1
        runtime.config.data["ha_last_seen"] = time.time() - 999
        result = runtime.engine.resolve(now=time.time())
        self.assertEqual(result["effective_source"], "local_fallback")
        self.assertLess(result["effective_level"], 6)


if __name__ == "__main__":
    unittest.main()
