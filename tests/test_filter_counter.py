import tempfile
import time
import unittest
from pathlib import Path

from test_bypass_and_discovery import crc16, make_gateway  # noqa: F401  (sets up the paho stub)


def filter_gateway(tmp):
    gateway = make_gateway()
    gateway.filter_unit = None
    gateway.filter_enabled = True
    gateway.filter_state_path = Path(tmp) / "filter-state.json"
    gateway.filter_reset_epoch = time.time() - 300 * 86400
    gateway.filter_interval_days = 360
    gateway.last_bus_frame = 0.0
    return gateway


def response(values):
    body = bytes([1, 3, len(values) * 2]) + b"".join(v.to_bytes(2, "big") for v in values)
    return body + crc16(body).to_bytes(2, "little")


class FilterCounterTests(unittest.TestCase):
    def test_block_1024_is_the_units_filter_counter(self):
        with tempfile.TemporaryDirectory() as tmp:
            gateway = filter_gateway(tmp)
            gateway.apply_filter_block([1, 12, 249, 235, 0, 0], "test")
            s = gateway.state
            self.assertEqual((s["filter_period_months"], s["filter_life_raw"], s["filter_hours_since_change"]), (12, 249, 235))
            self.assertEqual(s["filter_life_percent"], 98)
            self.assertEqual(s["filter_days_remaining"], 356)  # ceil((12 x 730 - 235) h / 24)
            self.assertEqual((s["filter_status"], s["filter_source"]), ("ok", "Anlæg (HAC1)"))
            # The Pi's own timer follows the unit.
            self.assertAlmostEqual(gateway.filter_reset_epoch, time.time() - 235 * 3600, delta=60)
            # The button on the unit resets the counter.
            before = s["filter_changed_at"]
            gateway.apply_filter_block([1, 12, 255, 0, 0, 0], "test")
            self.assertEqual((s["filter_life_percent"], s["filter_hours_since_change"]), (100, 0))
            self.assertGreater(s["filter_changed_at"], before + 230 * 3600)

    def test_passive_block_from_hcp4_traffic_and_odd_values_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            gateway = filter_gateway(tmp)
            gateway.decode(response([1, 6, 128, 4000, 0, 0]))
            self.assertEqual(gateway.state["filter_period_months"], 6)
            self.assertEqual(gateway.state["filter_status"], "skift_snart")
            gateway.apply_filter_block([0, 12, 255, 0, 0, 0], "test")
            gateway.apply_filter_block([1, 40, 255, 0, 0, 0], "test")
            self.assertEqual(gateway.state["filter_hours_since_change"], 4000)


if __name__ == "__main__":
    unittest.main()
