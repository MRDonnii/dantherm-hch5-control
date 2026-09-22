import sys
import unittest
import importlib.util
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

try:
    DEPENDENCIES_AVAILABLE = importlib.util.find_spec("paho.mqtt.client") is not None
except ModuleNotFoundError:
    DEPENDENCIES_AVAILABLE = False
if DEPENDENCIES_AVAILABLE:
    from dantherm_controller_gateway import Gateway
    from dantherm_gateway import Gateway as BaseGateway


class FakeMaster:
    def snapshot(self):
        return {"active_master": "hcp4", "hcp4_detection_reason": "foreign_write"}


class FakeController:
    def __init__(self, allowed):
        self.allowed = allowed
        self.master = FakeMaster()
        self.own_frames = []

    def hardware_writes_allowed(self):
        return self.allowed

    def note_own_frame(self, frame):
        self.own_frames.append(frame)


@unittest.skipUnless(DEPENDENCIES_AVAILABLE, "paho-mqtt is installed by the project installer/CI")
class HardwareBoundaryTests(unittest.TestCase):
    def make_gateway(self, allowed):
        gateway = Gateway.__new__(Gateway)
        gateway.controller = FakeController(allowed)
        return gateway

    def test_control_write_is_blocked_below_runtime_when_pi_is_not_master(self):
        gateway = self.make_gateway(False)
        with patch.object(BaseGateway, "serial_write") as low_level:
            with self.assertRaises(RuntimeError):
                gateway.serial_write(object(), b"12345678", "CONTROL fan_pair")
            low_level.assert_not_called()

    def test_allowed_control_write_is_registered_for_echo_matching(self):
        gateway = self.make_gateway(True)
        with patch.object(BaseGateway, "serial_write", return_value=8) as low_level:
            self.assertEqual(
                gateway.serial_write(object(), b"12345678", "CONTROL fan_pair"), 8
            )
            low_level.assert_called_once()
        self.assertEqual(gateway.controller.own_frames, [b"12345678"])


if __name__ == "__main__":
    unittest.main()
