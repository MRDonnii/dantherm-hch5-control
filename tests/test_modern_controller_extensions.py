import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from controller_core import ControllerEngine, ControllerState, HardwareAdapter


class ModernControllerExtensionTests(unittest.TestCase):
    def make_engine(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        state = ControllerState(Path(temp.name) / "controller.json")
        return ControllerEngine(state, HardwareAdapter())

    def test_quick_boost_is_timed_overlay_without_changing_base_mode(self):
        engine = self.make_engine()
        engine.config.configure({"mode": "local_auto", "quick_boost_level": 5, "quick_boost_minutes": 15})
        engine.update_measurements(rh=40, co2=600)
        result = engine.resolve()
        self.assertEqual(result["mode"], "local_auto")
        self.assertTrue(result["quick_boost_active"])
        self.assertEqual(result["effective_source"], "quick_boost")
        self.assertEqual(result["effective_level"], 5)
        self.assertGreater(result["quick_boost_remaining_seconds"], 0)

        engine.config.configure({"quick_boost_minutes": 0})
        result = engine.resolve()
        self.assertFalse(result["quick_boost_active"])
        self.assertNotEqual(result["effective_source"], "quick_boost")

    def test_fireplace_cancels_quick_boost(self):
        engine = self.make_engine()
        engine.config.configure({"quick_boost_minutes": 30})
        self.assertGreater(engine.config.snapshot()["quick_boost_remaining_seconds"], 0)
        engine.config.configure({"fireplace_minutes": 15})
        result = engine.config.snapshot()
        self.assertEqual(result["quick_boost_minutes"], 0)
        self.assertEqual(result["quick_boost_remaining_seconds"], 0)

    def test_vacation_with_end_time_expires_automatically(self):
        engine = self.make_engine()
        engine.config.configure({
            "vacation_enabled": True,
            "vacation_level": 1,
            "vacation_until": str(time.time() - 1),
        })
        result = engine.resolve()
        self.assertFalse(result["vacation_enabled"])
        self.assertFalse(result["vacation_active"])
        self.assertIsNone(result["vacation_until"])

    def test_free_cooling_qualification_minimum_on_and_minimum_off(self):
        engine = self.make_engine()
        engine.config.configure({
            "cooling_enabled": True,
            "cooling_room_setpoint": 23,
            "cooling_hysteresis": 0.5,
            "cooling_outdoor_min": 12,
            "cooling_min_delta": 2,
            "cooling_level": 4,
            "cooling_start_delay_seconds": 60,
            "cooling_min_on_seconds": 120,
            "cooling_min_off_seconds": 60,
        })
        engine.update_measurements(room=25, outdoor=18, rh=40, co2=600)

        result = engine.resolve(now=1000)
        self.assertFalse(result["cooling_active"])
        self.assertEqual(result["cooling_state"], "qualifying")
        self.assertEqual(result["cooling_qualification_remaining_seconds"], 60)

        result = engine.resolve(now=1060)
        self.assertTrue(result["cooling_active"])
        self.assertEqual(result["effective_bypass"], "on")

        engine.update_measurements(room=22, outdoor=18)
        result = engine.resolve(now=1100)
        self.assertTrue(result["cooling_active"])
        self.assertEqual(result["cooling_state"], "minimum_on_hold")

        result = engine.resolve(now=1181)
        self.assertFalse(result["cooling_active"])
        self.assertEqual(result["effective_bypass"], "off")

        engine.update_measurements(room=25, outdoor=18)
        result = engine.resolve(now=1190)
        self.assertFalse(result["cooling_active"])
        self.assertEqual(result["cooling_state"], "minimum_off_hold")

        result = engine.resolve(now=1242)
        self.assertFalse(result["cooling_active"])
        self.assertEqual(result["cooling_state"], "qualifying")

        result = engine.resolve(now=1302)
        self.assertTrue(result["cooling_active"])


if __name__ == "__main__":
    unittest.main()
