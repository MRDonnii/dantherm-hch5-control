import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from controller_core import ControllerEngine, ControllerError, ControllerState, HardwareAdapter
from controller_runtime import ControllerRuntime


class AirQualityMaximumTests(unittest.TestCase):
    def make_state(self, saved=None):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "controller.json"
        if saved is not None:
            path.write_text(json.dumps(saved))
        return ControllerState(path)

    def make_runtime(self):
        state = self.make_state()
        return ControllerRuntime(gateway_state={}, hardware=HardwareAdapter(), state_path=state.path)

    def test_existing_six_step_settings_keep_full_air_quality_range(self):
        state = self.make_state({"fan_step_count": 6})
        self.assertEqual(state.data["air_quality_max_level"], 6)
        state.configure({"air_quality_max_level": 4})
        self.assertEqual(ControllerState(state.path).data["air_quality_max_level"], 4)
        with self.assertRaises(ControllerError):
            state.configure({"air_quality_max_level": 7})

    def test_local_co2_and_humidity_stop_at_cap_without_delaying_a_lower_cap(self):
        state = self.make_state()
        state.configure({"local_normal_level": 2, "air_quality_max_level": 3})
        engine = ControllerEngine(state)
        engine.update_measurements(co2=2200, rh=80)
        self.assertEqual(engine.resolve()["effective_level"], 3)
        engine.current_auto_level = 4
        engine.boost_until = 10**12
        state.configure({"air_quality_max_level": 2})
        self.assertEqual(engine.resolve()["effective_level"], 2)
        state.configure({"local_normal_level": 3})
        self.assertEqual(engine.resolve()["effective_level"], 3)
        state.configure({"mode": "manual", "manual_level": 4})
        self.assertEqual(engine.resolve()["effective_level"], 4)

    def test_smart_air_quality_cap_keeps_bathroom_and_pm25_limits_separate(self):
        runtime = self.make_runtime()
        runtime.config.configure({"mode": "smart_auto", "local_normal_level": 2,
                                  "air_quality_max_level": 3, "bathroom_max_level": 4,
                                  "pm25_enabled": True, "pm25_max_level": 4})
        runtime.room_inputs({"rooms": {"Stue": {"co2": 2400, "priority": "critical"}}})
        self.assertEqual(runtime.smart_requested_level, 3)
        runtime.engine.current_auto_level = 4
        runtime.engine.boost_until = 10**12
        runtime.config.configure({"air_quality_max_level": 2})
        runtime.room_inputs({"rooms": {"Stue": {"humidity": 85}}})
        self.assertEqual(runtime.engine.resolve()["effective_level"], 2)

        runtime.room_inputs({"rooms": {"Badeværelse": {"humidity": 85}}})
        self.assertEqual(runtime.smart_requested_level, 4)
        runtime.room_inputs({"rooms": {"Køkken": {"pm25": 100}}})
        self.assertEqual(runtime.smart_requested_level, 4)


if __name__ == "__main__":
    unittest.main()
