import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from controller_core import ControllerError, HardwareAdapter
from controller_runtime import ControllerRuntime


class BathroomControlTests(unittest.TestCase):
    def make_runtime(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return ControllerRuntime(gateway_state={}, hardware=HardwareAdapter(), state_path=Path(temp.name) / "controller.json")

    @staticmethod
    def send(runtime, rooms):
        runtime.room_inputs({"source": "home_assistant", "valid_for_s": 180, "rooms": rooms})
        return runtime.smart_requested_level

    def test_room_settings_validate_and_empty_entries_are_dropped(self):
        runtime = self.make_runtime()
        runtime.config.configure({"bathroom_rooms": {
            "Gæstebad": {"type": "bathroom", "rh_setpoint": 70, "max_level": 4},
            "Stue": {"type": "auto"},
        }})
        self.assertEqual(runtime.config.data["bathroom_rooms"], {"Gæstebad": {"type": "bathroom", "rh_setpoint": 70.0, "max_level": 4}})
        for bad in ({"A": {"type": "wc"}}, {"A": {"type": "bathroom", "rh_setpoint": 20}}, {"A": {"type": "bathroom", "max_level": 99}}):
            with self.assertRaises(ControllerError):
                runtime.config.configure({"bathroom_rooms": bad})
        for key, value in (("bathroom_rise_percent", 1), ("bathroom_rise_minutes", 60), ("bathroom_max_minutes", -5)):
            with self.assertRaises(ControllerError):
                runtime.config.configure({key: value})

    def test_webui_room_type_and_limits_win_over_home_assistant(self):
        runtime = self.make_runtime()
        runtime.config.configure({"local_normal_level": 3, "bathroom_rh_setpoint": 65})
        # "Kælder" is not a bathroom by name; HA says RH 72 %, above the common 65 % limit.
        self.send(runtime, {"Kælder": {"humidity": 72}})
        self.assertNotIn("Kælder", runtime._bathroom_episodes)
        runtime.config.configure({"bathroom_rooms": {"Kælder": {"type": "bathroom", "max_level": 4}}})
        level = self.send(runtime, {"Kælder": {"humidity": 72}})
        self.assertIn("Kælder", runtime._bathroom_episodes)
        self.assertLessEqual(level, 4)
        # A named bathroom can be turned into a normal room.
        runtime.config.configure({"bathroom_rooms": {"Bad": {"type": "normal"}}})
        self.send(runtime, {"Bad": {"humidity": 80}})
        self.assertNotIn("Bad", runtime._bathroom_episodes)
        # The raw HA data is still shown as sent.
        self.assertNotIn("webui_override", runtime.smart_rooms["Bad"])

    def test_own_limit_for_one_bathroom(self):
        runtime = self.make_runtime()
        runtime.config.configure({"local_normal_level": 3, "bathroom_rh_setpoint": 65, "bathroom_rooms": {"Bad": {"rh_setpoint": 80}}})
        self.send(runtime, {"Bad": {"humidity": 72}})
        self.assertNotIn("Bad", runtime._bathroom_episodes)   # below its own, higher limit
        self.send(runtime, {"Bad": {"humidity": 83}})
        self.assertIn("Bad", runtime._bathroom_episodes)

    def test_shower_detection_follows_the_settings(self):
        runtime = self.make_runtime()
        runtime.config.configure({"bathroom_rise_percent": 4, "bathroom_rise_minutes": 10})
        self.send(runtime, {"Bad": {"humidity": 50}})
        self.send(runtime, {"Bad": {"humidity": 55.5}})   # +5.5 %-points, below the old fixed 7
        self.assertIn("Bad", runtime._bathroom_episodes)

    def test_longest_drying_time_stops_a_stuck_sensor(self):
        runtime = self.make_runtime()
        runtime.config.configure({"bathroom_max_minutes": 30, "bathroom_rh_setpoint": 65})
        self.send(runtime, {"Bad": {"humidity": 80}})
        episode = runtime._bathroom_episodes["Bad"]
        episode["started"] -= 31 * 60
        runtime._recalculate_smart_demand()
        self.assertTrue(episode.get("expired"))
        status = {s["name"]: s for s in runtime.snapshot()["bathroom_status"]}
        self.assertEqual(status["Bad"]["state"], "expired")
        level = self.send(runtime, {"Bad": {"humidity": 82}})
        self.assertEqual(level, runtime.config.normal_level())
        self.send(runtime, {"Bad": {"humidity": 50}})      # below the end point: the episode is over
        self.assertNotIn("Bad", runtime._bathroom_episodes)

    def test_status_reports_drying_and_overrides(self):
        runtime = self.make_runtime()
        runtime.config.configure({"bathroom_rooms": {"Bad": {"max_level": 4}}})
        self.send(runtime, {"Bad": {"humidity": 80}, "Stue": {"humidity": 40}})
        status = {s["name"]: s for s in runtime.snapshot()["bathroom_status"]}
        self.assertEqual(list(status), ["Bad"])
        self.assertEqual(status["Bad"]["state"], "drying")
        self.assertEqual(status["Bad"]["max_level"], 4)
        self.assertTrue(status["Bad"]["webui_override"])

    def test_night_drying_can_be_switched_off(self):
        runtime = self.make_runtime()
        self.assertTrue(runtime.config.data["bathroom_night_drying"])
        runtime.config.configure({"bathroom_night_drying": False})
        self.assertFalse(runtime.config.data["bathroom_night_drying"])


if __name__ == "__main__":
    unittest.main()
