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
    from dantherm_controller_gateway import Gateway, enable_adaptive_active_reads
    from dantherm_gateway import Gateway as BaseGateway
    from master_arbitration import MasterArbitrator, crc16


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

    def test_controller_gateway_enables_adaptive_reads_by_default_but_preserves_opt_out(self):
        config = {"serial": {}}
        enable_adaptive_active_reads(config)
        self.assertTrue(config["serial"]["active_reads_enabled"])

        disabled = {"serial": {"active_reads_enabled": False}}
        enable_adaptive_active_reads(disabled)
        self.assertFalse(disabled["serial"]["active_reads_enabled"])

    def test_active_read_is_blocked_while_hcp4_read_requests_are_recent(self):
        arb = MasterArbitrator()
        request_body = bytes([0x40, 3, 0, 180, 0, 30])
        request = request_body + crc16(request_body).to_bytes(2, "little")
        now = arb.started_monotonic + 20
        arb.observe_frame(request, now=now - 0.1)
        gateway = self.make_gateway(True)
        gateway.controller.master = arb

        with patch("dantherm_controller_gateway.time.monotonic", return_value=now):
            with patch.object(BaseGateway, "serial_write") as low_level:
                self.assertEqual(gateway.serial_write(object(), request, "ACTIVE_READ"), 0)
                low_level.assert_not_called()

    def test_read_helper_returns_without_retrying_while_hcp4_owns_bus(self):
        arb = MasterArbitrator()
        request_body = bytes([0x40, 3, 0, 180, 0, 30])
        request = request_body + crc16(request_body).to_bytes(2, "little")
        arb.observe_frame(request)
        gateway = self.make_gateway(True)
        gateway.controller.master = arb

        with patch.object(BaseGateway, "wait_quiet") as wait_quiet:
            self.assertIsNone(gateway.read_register_block(object(), 0x40, 180, 30))
            wait_quiet.assert_not_called()

    def test_active_read_echo_is_registered_when_pi_owns_bus(self):
        arb = MasterArbitrator(startup_observation=3)
        t0 = arb.started_monotonic
        arb.evaluate(bus_healthy=True, now=t0 + 3.1)
        gateway = self.make_gateway(True)
        gateway.controller.master = arb
        request_body = bytes([0x40, 3, 0, 180, 0, 30])
        request = request_body + crc16(request_body).to_bytes(2, "little")

        with patch("dantherm_controller_gateway.time.monotonic", return_value=t0 + 3.2):
            with patch.object(BaseGateway, "serial_write", return_value=8) as low_level:
                self.assertEqual(
                    gateway.serial_write(object(), request, "ACTIVE_READ"), 8
                )
                low_level.assert_called_once()
        self.assertEqual(gateway.controller.own_frames, [request])


if __name__ == "__main__":
    unittest.main()
