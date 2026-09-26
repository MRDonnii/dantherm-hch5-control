import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from diagnostics import Diagnostics

T0 = datetime(2026, 1, 15, 12, 0).timestamp()


def winter(**extra):
    s = {"outdoor_temperature": -5.0, "extract_temperature": 22.0, "exhaust_temperature": 2.0,
         "actual_supply_before_heater_temperature": 18.0, "supply_recovery_percent": 85.0,
         "actual_bypass": False, "rs485_healthy": True, "effective_level": 2,
         "supply_airflow_estimate_m3h": 120.0, "unit_power_w": 30.0,
         "recovered_heat_w": 900.0, "afterheat_power_w": 100.0, "filter_life_percent": 80}
    s.update(extra)
    return s


class DiagnosticsTest(unittest.TestCase):
    def test_frost_is_raised_only_after_its_delay_and_clears(self):
        d = Diagnostics()
        r = d.update(winter(exhaust_temperature=0.0), T0)
        self.assertEqual(r["frost_state"], "risk")
        self.assertEqual(r["diagnostics_alarm_count"], 0)
        r = d.update(winter(exhaust_temperature=0.0), T0 + 301)
        self.assertEqual([a["code"] for a in r["diagnostics_alarms"]], ["frost_risk"])
        self.assertEqual(r["diagnostics_status"], "warning")
        r = d.update(winter(), T0 + 310)
        self.assertEqual(r["frost_state"], "watch")
        self.assertEqual(r["diagnostics_alarm_count"], 0)

    def test_low_recovery_and_bus_alarm(self):
        d = Diagnostics()
        d.update(winter(supply_recovery_percent=50.0, rs485_healthy=False), T0)
        r = d.update(winter(supply_recovery_percent=50.0, rs485_healthy=False), T0 + 1801)
        codes = {a["code"] for a in r["diagnostics_alarms"]}
        self.assertIn("recovery_low", codes)
        self.assertIn("bus_unhealthy", codes)
        self.assertEqual(r["diagnostics_status"], "critical")

    def test_no_recovery_alarms_in_mild_weather(self):
        d = Diagnostics()
        d.update(winter(outdoor_temperature=18.0, supply_recovery_percent=10.0), T0)
        r = d.update(winter(outdoor_temperature=18.0, supply_recovery_percent=10.0), T0 + 7200)
        self.assertEqual(r["diagnostics_alarm_count"], 0)

    def test_bypass_not_closing(self):
        d = Diagnostics()
        s = winter(actual_supply_before_heater_temperature=-3.0, actual_bypass_request="off")
        d.update(s, T0)
        r = d.update(s, T0 + 1201)
        self.assertIn("bypass_not_closing", {a["code"] for a in r["diagnostics_alarms"]})

    def test_sfp_reference_and_filter_clogging(self):
        d = Diagnostics()
        t = T0
        for _ in range(40):
            t += 10
            r = d.update(winter(), t)
        self.assertEqual(r["specific_fan_power"], 900)
        self.assertEqual(r["filter_power_ratio"], 1.0)
        for _ in range(60):
            t += 10
            r = d.update(winter(unit_power_w=40.0), t)
        self.assertGreaterEqual(r["filter_power_ratio"], 1.3)
        for _ in range(400):
            t += 10
            r = d.update(winter(unit_power_w=40.0), t)
        self.assertIn("filter_clogging", {a["code"] for a in r["diagnostics_alarms"]})
        # Filter change: life jumps up, the reference starts over.
        r = d.update(winter(unit_power_w=40.0, filter_life_percent=100), t + 10)
        self.assertIsNone(r["filter_power_ratio"])

    def test_energy_is_integrated_persisted_and_resets_daily(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "diagnostics.json"
            d = Diagnostics(path)
            d.update(winter(), T0)
            r = d.update(winter(), T0 + 36)  # 36 s at 900 W = 9 Wh
            self.assertAlmostEqual(r["recovered_energy_kwh"], 0.009, places=4)
            self.assertAlmostEqual(d.today["unit_kwh"], 0.0003, places=6)
            self.assertEqual(r["recovery_factor"], None)
            d.save()
            again = Diagnostics(path)
            r = again.update(winter(), T0 + 86400)
            self.assertAlmostEqual(r["recovered_energy_kwh"], 0.009, places=4)
            self.assertEqual(r["recovered_energy_today_kwh"], 0.0)

    def test_nothing_breaks_without_data(self):
        r = Diagnostics().update({}, T0)
        self.assertEqual(r["frost_state"], "unknown")
        self.assertIsNone(r["specific_fan_power"])
        self.assertEqual(r["diagnostics_status"], "ok")


if __name__ == "__main__":
    unittest.main()
