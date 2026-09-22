import tempfile
import time
import unittest
from collections import deque
from pathlib import Path

from controller_core import ControllerEngine, ControllerState, HardwareAdapter
from controller_runtime import ControllerRuntime


class SmartRoomControllerTests(unittest.TestCase):
    def make_runtime(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        runtime = ControllerRuntime(
            gateway_state={},
            hardware=HardwareAdapter(),
            state_path=Path(directory.name) / "controller.json",
        )
        runtime.config.configure({
            "mode": "smart_auto",
            "local_normal_level": 3,
            "local_min_level": 1,
            "local_max_level": 6,
            "co2_setpoint": 800,
            "auto_step_co2": 200,
            "rh_setpoint": 50,
            "auto_step_rh": 5,
        })
        return runtime

    def test_low_priority_still_reacts_above_threshold(self):
        runtime = self.make_runtime()
        runtime.smart_rooms = {
            "Bedroom": {"co2": 900.0, "control": True, "priority": "low"}
        }
        target, reason, room, metric, _ = runtime._derive_smart_target(time.time())
        self.assertEqual(target, 4)
        self.assertEqual(room, "Bedroom")
        self.assertEqual(metric, "co2")
        self.assertIn("Bedroom", reason)

    def test_high_priority_reacts_earlier(self):
        runtime = self.make_runtime()
        runtime.smart_rooms = {
            "Bathroom": {"humidity": 55.5, "control": True, "priority": "high"}
        }
        target, _, room, metric, _ = runtime._derive_smart_target(time.time())
        self.assertEqual(target, 6)
        self.assertEqual(room, "Bathroom")
        self.assertEqual(metric, "humidity")

    def test_severe_auto_room_beats_high_priority_mild_room(self):
        runtime = self.make_runtime()
        runtime.smart_rooms = {
            "Kitchen": {"co2": 900.0, "control": True, "priority": "high"},
            "Bedroom": {"co2": 1400.0, "control": True, "priority": "auto"},
        }
        target, reason, room, metric, diagnostics = runtime._derive_smart_target(time.time())
        self.assertEqual(target, 6)
        self.assertEqual(room, "Bedroom")
        self.assertEqual(metric, "co2")
        self.assertIn("Bedroom", reason)
        self.assertEqual(diagnostics["Kitchen"]["requested_level"], 5)

    def test_monitor_only_room_never_controls(self):
        runtime = self.make_runtime()
        runtime.smart_rooms = {
            "Office": {"co2": 3000.0, "control": False, "priority": "critical"}
        }
        target, _, room, metric, diagnostics = runtime._derive_smart_target(time.time())
        self.assertEqual(target, 3)
        self.assertIsNone(room)
        self.assertIsNone(metric)
        self.assertIsNone(diagnostics["Office"]["requested_level"])
        self.assertEqual(diagnostics["Office"]["reason"], "Monitor only")

    def test_fast_humidity_rise_requests_extra_ventilation(self):
        runtime = self.make_runtime()
        runtime.config.configure({"rh_setpoint": 75})
        now = time.time()
        runtime.smart_rooms = {
            "Bathroom": {"humidity": 58.0, "control": True, "priority": "auto"}
        }
        runtime._room_rh_history["Bathroom"] = deque([
            (now - 590, 50.0),
            (now, 58.0),
        ])
        target, reason, room, metric, _ = runtime._derive_smart_target(now)
        self.assertEqual(target, 5)
        self.assertEqual(room, "Bathroom")
        self.assertEqual(metric, "humidity_rise")
        self.assertIn("RH rise", reason)

    def test_smart_target_can_use_intermediate_level_four(self):
        runtime = self.make_runtime()
        runtime.smart_rooms = {
            "Bedroom": {"co2": 850.0, "control": True, "priority": "auto"}
        }
        runtime._recalculate_smart_demand(time.time(), heartbeat=True)
        self.assertEqual(runtime.smart_target_level, 4)
        self.assertEqual(runtime.config.data["ha_target_level"], 4)
        resolved = runtime.engine.resolve()
        self.assertEqual(resolved["effective_level"], 4)
        self.assertIn("Bedroom", resolved["effective_reason"])

    def test_expired_room_lease_forces_local_fallback(self):
        runtime = self.make_runtime()
        runtime.room_inputs({
            "valid_for_s": 30,
            "rooms": {"Bedroom": {"co2": 1400, "priority": "auto", "control": True}},
        })
        self.assertEqual(runtime.engine.resolve()["effective_source"], "ha_smart")
        runtime.smart_inputs_received_at = time.time() - 31
        runtime._expire_smart_lease()
        result = runtime.engine.resolve()
        self.assertEqual(result["effective_source"], "local_fallback")
        self.assertIsNone(runtime.config.data["ha_last_seen"])


class SmartTargetCoreTests(unittest.TestCase):
    def test_smart_auto_uses_exact_ha_target_level(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        state = ControllerState(Path(directory.name) / "state.json")
        state.configure({"enabled": True, "mode": "smart_auto"})
        state.heartbeat("high", target_level=2, reason="test room")
        engine = ControllerEngine(state)
        result = engine.resolve()
        self.assertEqual(result["effective_level"], 2)
        self.assertEqual(result["effective_reason"], "test room")


if __name__ == "__main__":
    unittest.main()
