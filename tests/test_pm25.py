import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from controller_core import ControllerError, HardwareAdapter
from controller_runtime import ControllerRuntime


class Pm25Tests(unittest.TestCase):
    def make_runtime(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return ControllerRuntime(gateway_state={}, hardware=HardwareAdapter(), state_path=Path(temp.name) / "controller.json")

    @staticmethod
    def decide(runtime, rooms):
        runtime.room_inputs({"source": "home_assistant", "valid_for_s": 180, "rooms": rooms})
        return runtime.smart_requested_level, runtime.smart_controlling_metric

    def test_pm25_is_optional_and_lifts_the_level_when_enabled(self):
        runtime = self.make_runtime()
        normal = runtime.config.normal_level()
        rooms = {"Køkken": {"pm25": 70}}
        self.assertEqual(self.decide(runtime, rooms)[0], normal)  # off by default
        runtime.config.configure({"pm25_enabled": True, "pm25_setpoint": 25, "pm25_step": 15, "pm25_max_level": 5})
        level, metric = self.decide(runtime, rooms)
        self.assertEqual(metric, "pm25")
        self.assertEqual(level, min(5, normal + 3))  # 70 is 45 over the limit = 3 steps

    def test_ignored_rooms_and_cap(self):
        runtime = self.make_runtime()
        runtime.config.configure({"pm25_enabled": True, "pm25_max_level": 4, "pm25_ignored_rooms": ["Soveværelse"]})
        self.assertEqual(self.decide(runtime, {"Soveværelse": {"pm25": 300}})[0], runtime.config.normal_level())
        self.assertEqual(self.decide(runtime, {"Køkken": {"pm25": 300}})[0], 4)

    def test_pm25_only_room_is_accepted_and_validated(self):
        runtime = self.make_runtime()
        runtime.room_inputs({"rooms": {"Stue": {"pm2_5": 8}}})
        self.assertEqual(runtime.smart_rooms["Stue"]["pm25"], 8)
        with self.assertRaises(ControllerError):
            runtime.room_inputs({"rooms": {"Stue": {"pm25": -3}}})


if __name__ == "__main__":
    unittest.main()
