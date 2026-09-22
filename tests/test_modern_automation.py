import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from controller_core import ControllerEngine, ControllerError, ControllerState, HardwareAdapter


class ModernAutomationTests(unittest.TestCase):
    def make_engine(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        state = ControllerState(Path(temp.name) / "controller.json")
        return ControllerEngine(state, HardwareAdapter())

    def test_vacation_overrides_normal_level_and_disables_cooling(self):
        engine = self.make_engine()
        engine.config.configure({
            "vacation_enabled": True,
            "vacation_level": 1,
            "cooling_enabled": True,
            "cooling_room_setpoint": 22,
        })
        engine.update_measurements(room=27, outdoor=18)
        result = engine.resolve()
        self.assertEqual(result["effective_source"], "vacation")
        self.assertEqual(result["effective_level"], 1)
        self.assertFalse(result["cooling_active"])
        self.assertEqual(result["effective_bypass"], "off")

    def test_free_cooling_requests_bypass_and_minimum_level(self):
        engine = self.make_engine()
        engine.config.configure({
            "cooling_enabled": True,
            "cooling_room_setpoint": 23,
            "cooling_hysteresis": 0.5,
            "cooling_outdoor_min": 12,
            "cooling_min_delta": 2,
            "cooling_level": 4,
        })
        engine.update_measurements(room=25, outdoor=19, rh=40, co2=600)
        result = engine.resolve()
        self.assertTrue(result["cooling_active"])
        self.assertEqual(result["effective_bypass"], "on")
        self.assertGreaterEqual(result["effective_level"], 4)
        self.assertEqual(result["effective_source"], "free_cooling")

    def test_free_cooling_does_not_run_when_outdoor_air_is_too_warm(self):
        engine = self.make_engine()
        engine.config.configure({"cooling_enabled": True, "cooling_room_setpoint": 23, "cooling_min_delta": 2})
        engine.update_measurements(room=26, outdoor=25, rh=40, co2=600)
        result = engine.resolve()
        self.assertFalse(result["cooling_active"])
        self.assertEqual(result["effective_bypass"], "off")

    def test_night_reduction_is_adjustable_but_air_quality_can_override(self):
        engine = self.make_engine()
        engine.config.configure({"night_enabled": True, "night_start": "00:00", "night_end": "23:59", "night_level": 2})
        engine.update_measurements(rh=40, co2=600)
        engine.current_auto_level = 3
        result = engine.resolve(now=time.time())
        self.assertTrue(result["night_active"])
        self.assertLessEqual(result["effective_level"], 2)

        engine.update_measurements(rh=70, co2=1600)
        engine.current_auto_level = 5
        result = engine.resolve(now=time.time())
        self.assertGreaterEqual(result["effective_level"], 5)

    def test_schedule_accepts_week_and_raises_baseline_inside_window(self):
        engine = self.make_engine()
        schedule = {str(day): {"enabled": True, "start": "00:00", "end": "23:59", "level": 4} for day in range(7)}
        engine.config.configure({"schedule_enabled": True, "schedule": schedule})
        engine.update_measurements(rh=40, co2=600)
        engine.current_auto_level = 1
        result = engine.resolve(now=time.time())
        self.assertTrue(result["schedule_active"])
        self.assertGreaterEqual(result["effective_level"], 4)

    def test_invalid_schedule_time_is_rejected(self):
        engine = self.make_engine()
        with self.assertRaises(ControllerError):
            engine.config.configure({"schedule": {"0": {"start": "25:77"}}})

    def test_manual_bypass_still_has_priority_when_cooling_is_not_running(self):
        engine = self.make_engine()
        engine.config.configure({"bypass": "on", "mode": "manual", "manual_level": 3})
        result = engine.resolve()
        self.assertEqual(result["effective_bypass"], "on")


if __name__ == "__main__":
    unittest.main()
