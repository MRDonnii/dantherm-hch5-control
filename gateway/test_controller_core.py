import tempfile
import time
import unittest
from pathlib import Path

from controller_core import ControllerEngine, ControllerError, ControllerState, HardwareAdapter


class ControllerTests(unittest.TestCase):
    def make(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        state = ControllerState(Path(directory.name) / "state.json")
        return state, ControllerEngine(state)

    def test_always_enabled_and_old_disabled_state_migrates(self):
        state, engine = self.make()
        self.assertTrue(state.data["enabled"])
        self.assertIsNotNone(engine.resolve()["effective_level"])
        state.path.write_text('{"enabled": false, "mode": "manual", "manual_level": 2}')
        migrated = ControllerState(state.path)
        self.assertTrue(migrated.data["enabled"])
        with self.assertRaises(ControllerError):
            migrated.configure({"enabled": False})

    def test_six_profiles_are_monotonic_and_balanced(self):
        state, _ = self.make()
        profiles = state.data["profiles"]
        self.assertEqual(set(profiles), set(range(1, 7)))
        for level in range(1, 7):
            self.assertGreater(profiles[level]["extract"], profiles[level]["supply"])
        self.assertEqual((profiles[1]["extract"], profiles[1]["supply"]), (25, 13))
        self.assertEqual((profiles[3]["extract"], profiles[3]["supply"]), (55, 43))
        self.assertEqual((profiles[5]["extract"], profiles[5]["supply"]), (85, 73))
        self.assertEqual((profiles[6]["extract"], profiles[6]["supply"]), (100, 88))

    def test_manual_level_uses_profile(self):
        state, engine = self.make()
        state.configure({"mode": "manual", "manual_level": 4})
        result = engine.resolve()
        self.assertEqual(result["effective_level"], 4)
        self.assertEqual((result["effective_profile"]["extract"], result["effective_profile"]["supply"]), (70, 58))

    def test_profile_can_be_calibrated(self):
        state, engine = self.make()
        state.configure({"profiles": {"4": {"extract": 72, "supply": 60}}})
        state.configure({"mode": "manual", "manual_level": 4})
        result = engine.resolve()
        self.assertEqual(result["effective_profile"]["extract"], 72)
        self.assertEqual(result["effective_profile"]["supply"], 60)

    def test_rejects_supply_not_below_extract(self):
        state, _ = self.make()
        with self.assertRaises(ControllerError):
            state.configure({"profiles": {"3": {"extract": 50, "supply": 50}}})

    def test_rejects_non_monotonic_profiles(self):
        state, _ = self.make()
        with self.assertRaises(ControllerError):
            state.configure({"profiles": {"4": {"extract": 54, "supply": 42}}})

    def test_rh_raises_local_auto(self):
        state, engine = self.make()
        state.configure({"mode": "local_auto", "rh_setpoint": 50})
        engine.update_measurements(rh=61, co2=600)
        result = engine.resolve()
        self.assertGreaterEqual(result["effective_level"], 5)
        self.assertIn("RH", result["effective_reason"])

    def test_co2_raises_local_auto(self):
        state, engine = self.make()
        state.configure({"mode": "local_auto", "co2_setpoint": 800})
        engine.update_measurements(rh=40, co2=1250)
        result = engine.resolve()
        self.assertEqual(result["effective_level"], 6)
        self.assertIn("CO2", result["effective_reason"])

    def test_downshift_waits_for_hysteresis_and_delay(self):
        state, engine = self.make()
        state.configure({"mode": "local_auto", "downshift_delay_seconds": 30})
        engine.update_measurements(rh=70, co2=1800)
        high = engine.resolve(now=1000)
        self.assertEqual(high["effective_level"], 6)
        engine.boost_until = 0
        engine.update_measurements(rh=40, co2=500)
        still_high = engine.resolve(now=1010)
        self.assertEqual(still_high["effective_level"], 6)
        low = engine.resolve(now=1040)
        self.assertEqual(low["effective_level"], state.data["local_normal_level"])

    def test_smart_auto_uses_ha_when_fresh(self):
        state, engine = self.make()
        state.configure({"mode": "smart_auto"})
        state.heartbeat("high", requested_level=5)
        self.assertEqual(engine.resolve()["effective_level"], 5)
        state.heartbeat("boost", requested_level=6)
        self.assertEqual(engine.resolve()["effective_level"], 6)

    def test_smart_auto_falls_back_to_local(self):
        state, engine = self.make()
        state.configure({"mode": "smart_auto"})
        state.data["ha_last_seen"] = time.time() - 999
        engine.update_measurements(rh=40, co2=600)
        result = engine.resolve()
        self.assertEqual(result["effective_source"], "local_fallback")
        self.assertEqual(result["effective_level"], 3)

    def test_afterheat_setpoint_persists(self):
        state, _ = self.make()
        state.configure({"afterheat_setpoint": 22})
        reloaded = ControllerState(state.path)
        self.assertEqual(reloaded.data["afterheat_setpoint"], 22)
        with self.assertRaises(ControllerError):
            reloaded.configure({"afterheat_setpoint": 17})

    def test_fireplace_timer_expires_and_restores_selected_fan_profile(self):
        calls = []
        state, _ = self.make()
        engine = ControllerEngine(state, HardwareAdapter(
            write_fan_pair=lambda extract, supply: calls.append(("fan", extract, supply)),
            set_fireplace=lambda enabled: calls.append(("fireplace", enabled)),
            set_afterheat_setpoint=lambda value: None,
        ))
        state.configure({"mode": "manual", "manual_level": 4,
                         "fireplace_minutes": 15})
        engine.apply()
        self.assertTrue(state.snapshot()["fireplace"])
        self.assertGreater(state.snapshot()["fireplace_remaining_seconds"], 0)
        state.data["fireplace_until"] = time.time() - 1
        expired = engine.apply()
        self.assertFalse(expired["fireplace"])
        self.assertEqual(expired["fireplace_remaining_seconds"], 0)
        self.assertEqual(expired["mode"], "manual")
        self.assertEqual(expired["effective_level"], 4)
        self.assertEqual(calls.count(("fan", 70, 58)), 2)
        self.assertEqual(calls[-2:], [("fireplace", False), ("fan", 70, 58)])

    def test_fireplace_timer_only_accepts_predefined_durations(self):
        state, _ = self.make()
        for minutes in (0, 15, 30):
            state.configure({"fireplace_minutes": minutes})
        with self.assertRaises(ControllerError):
            state.configure({"fireplace_minutes": 20})

    def test_apply_deduplicates_writes(self):
        calls = []
        state, _ = self.make()
        adapter = HardwareAdapter(
            write_fan_pair=lambda extract, supply: calls.append(("fan", extract, supply)),
            set_fireplace=lambda enabled: calls.append(("fireplace", enabled)),
            set_afterheat_setpoint=lambda value: calls.append(("afterheat", value)),
        )
        engine = ControllerEngine(state, adapter)
        state.configure({"mode": "manual", "manual_level": 3})
        engine.apply()
        engine.apply()
        self.assertEqual(calls.count(("fan", 55, 43)), 1)
        self.assertEqual(calls.count(("fireplace", False)), 1)

    def test_apply_afterheat_only_when_explicit(self):
        calls = []
        state, _ = self.make()
        adapter = HardwareAdapter(
            write_fan_pair=lambda extract, supply: None,
            set_fireplace=lambda enabled: None,
            set_afterheat_setpoint=lambda value: calls.append(value),
        )
        engine = ControllerEngine(state, adapter)
        state.configure({"afterheat_setpoint": 21})
        engine.apply()
        engine.apply()
        self.assertEqual(calls, [21])

    def test_failed_write_has_bounded_retries(self):
        calls = []
        state, _ = self.make()
        def fail(extract, supply):
            calls.append((extract, supply))
            raise OSError("bus unavailable")
        engine = ControllerEngine(state, HardwareAdapter(
            write_fan_pair=fail, set_fireplace=lambda enabled: None,
            set_afterheat_setpoint=lambda value: None,
        ))
        engine.retry_base_seconds = 0
        state.configure({"mode": "manual", "manual_level": 3})
        for _ in range(10):
            try: engine.apply()
            except OSError: pass
        self.assertEqual(len(calls), 3)
        self.assertEqual(engine.write_failures, 3)

    def test_persistent_configuration(self):
        state, _ = self.make()
        state.configure({"local_normal_level": 4, "rh_setpoint": 52, "co2_setpoint": 900})
        other = ControllerState(state.path)
        self.assertEqual(other.data["local_normal_level"], 4)
        self.assertEqual(other.data["rh_setpoint"], 52)
        self.assertEqual(other.data["co2_setpoint"], 900)


if __name__ == "__main__":
    unittest.main()
