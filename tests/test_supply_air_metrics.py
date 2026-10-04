import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from advanced_control import supply_air_metrics


class SupplyAirMetricsTest(unittest.TestCase):
    def test_winter_values_from_measured_t2(self):
        # 0 C outdoor, 22 C extract, T2 19.8 C after the core, coil lifts to 21.8 C at 150 m3/h.
        m = supply_air_metrics(0.0, 22.0, 19.8, 21.8, 150.0, False, 0.4)
        self.assertEqual(m["corrected_t2_temperature"], 20.2)
        self.assertEqual(m["supply_recovery_percent"], 91.8)
        self.assertEqual(m["recovered_heat_w"], round(20.2 * 150 / 3600 * 1206))
        self.assertEqual(m["afterheat_lift"], 1.6)
        self.assertEqual(m["afterheat_power_w"], round(1.6 * 150 / 3600 * 1206))

    def test_nothing_without_t2(self):
        self.assertTrue(all(v is None for v in supply_air_metrics(0.0, 22.0, None, 21.8, 150.0, False).values()))

    def test_small_indoor_outdoor_difference_gives_no_recovery(self):
        m = supply_air_metrics(20.0, 22.0, 21.5, 21.6, 150.0, False)
        self.assertIsNone(m["supply_recovery_percent"])
        self.assertEqual(m["afterheat_lift"], 0.1)

    def test_bypass_has_no_recovery_and_cold_coil_no_power(self):
        m = supply_air_metrics(10.0, 22.0, 10.5, 10.3, 150.0, True)
        self.assertIsNone(m["supply_recovery_percent"])
        self.assertIsNone(m["recovered_heat_w"])
        self.assertEqual(m["afterheat_power_w"], 0)

    def test_without_airflow_only_temperatures(self):
        m = supply_air_metrics(0.0, 22.0, 19.8, 21.8, None, False)
        self.assertEqual(m["supply_recovery_percent"], 90.0)
        self.assertIsNone(m["recovered_heat_w"])
        self.assertIsNone(m["afterheat_power_w"])


if __name__ == "__main__":
    unittest.main()
