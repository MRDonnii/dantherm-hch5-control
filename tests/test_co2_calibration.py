import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from controller_core import ControllerError, HardwareAdapter
from controller_runtime import ControllerRuntime

try:
    from dantherm_controller_gateway import Gateway
except ImportError:  # serial/yaml missing in a bare test environment
    Gateway = None


class Co2CalibrationTests(unittest.TestCase):
    def make_runtime(self, gateway_state):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return ControllerRuntime(
            gateway_state=gateway_state,
            hardware=HardwareAdapter(),
            state_path=Path(temp.name) / "controller.json",
        )

    def make_gateway(self, runtime, state):
        gateway = Gateway.__new__(Gateway)
        gateway.state = state
        gateway.controller = runtime
        gateway.mqtt_enabled = False
        return gateway

    def test_offset_defaults_to_zero_and_is_range_checked(self):
        runtime = self.make_runtime({})
        self.assertEqual(runtime.config.data["co2_offset"], 0)
        runtime.config.configure({"co2_offset": -200})
        self.assertEqual(runtime.config.data["co2_offset"], -200)
        with self.assertRaises(ControllerError):
            runtime.config.configure({"co2_offset": 1500})

    @unittest.skipIf(Gateway is None, "gateway dependencies not installed")
    def test_unit_co2_is_published_with_offset_and_raw_is_kept(self):
        state = {}
        runtime = self.make_runtime(state)
        runtime.config.configure({"co2_offset": -200})
        gateway = self.make_gateway(runtime, state)
        gateway.publish("co2", 1083)
        self.assertEqual(state["co2"], 883)
        self.assertEqual(state["co2_raw"], 1083)
        snapshot = runtime.snapshot()
        self.assertEqual(snapshot["co2_raw"], 1083)
        self.assertEqual(snapshot["co2_measured"], 883)

    @unittest.skipIf(Gateway is None, "gateway dependencies not installed")
    def test_changing_offset_republishes_without_new_reading(self):
        state = {}
        runtime = self.make_runtime(state)
        gateway = self.make_gateway(runtime, state)
        gateway.publish("co2", 900)
        self.assertEqual(state["co2"], 900)
        runtime.config.configure({"co2_offset": -150})
        gateway._refresh_co2_offset()
        self.assertEqual(state["co2"], 750)

    @unittest.skipIf(Gateway is None, "gateway dependencies not installed")
    def test_smart_auto_controls_on_the_corrected_value(self):
        state = {}
        runtime = self.make_runtime(state)
        gateway = self.make_gateway(runtime, state)
        runtime.config.configure({"co2_offset": -200})
        gateway.publish("co2", 950)
        runtime.refresh_measurements()
        self.assertEqual(runtime.engine.measurements["co2"], 750)


if __name__ == "__main__":
    unittest.main()
