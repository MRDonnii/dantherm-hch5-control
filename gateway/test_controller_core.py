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

    def test_t3_t5_setpoints_default_off_and_validate(self):
        state, _engine = self.make()
        self.assertIsNone(state.data["t3_setpoint"])
        self.assertIsNone(state.data["t5_setpoint"])
        state.configure({"t5_setpoint": 21})
        self.assertEqual(ControllerState(state.path).data["t5_setpoint"], 21)
        state.configure({"t5_setpoint": None})
        self.assertIsNone(state.data["t5_setpoint"])
        for bad in (5, 40, "x", True):
            with self.assertRaises(ControllerError):
                state.configure({"t3_setpoint": bad})

    def test_always_enabled_and_old_disabled_state_migrates(self):
        state, engine = self.make()
        self.assertTrue(state.data["enabled"])
        self.assertIsNotNone(engine.resolve()["effective_level"])
        state.path.write_text('{"enabled": false, "mode": "manual", "manual_level": 2}')
        migrated = ControllerState(state.path)
        self.assertTrue(migrated.data["enabled"])
        with self.assertRaises(ControllerError):
            migrated.configure({"enabled": False})

    def test_four_dantherm_steps_follow_the_commissioning(self):
        state, _ = self.make()
        profiles = state.data["profiles"]
        self.assertEqual(set(profiles), {1, 2, 3, 4})
        pairs = {level: (p["extract"], p["supply"]) for level, p in profiles.items()}
        # Step 3 = gear 64, steps 2 and 1 one and two offsets (25) below, step 4 = gear 100.
        self.assertEqual(pairs, {1: (14, 14), 2: (39, 39), 3: (64, 64), 4: (100, 100)})
        state.configure({"fan_settings": {"extract": 80, "supply": 70, "offset": 20, "max_supply": 90}})
        pairs = {level: (p["extract"], p["supply"]) for level, p in state.data["profiles"].items()}
        self.assertEqual(pairs, {1: (40, 30), 2: (60, 50), 3: (80, 70), 4: (100, 90)})

    def test_manual_level_uses_profile(self):
        state, engine = self.make()
        state.configure({"mode": "manual", "manual_level": 3})
        result = engine.resolve()
        self.assertEqual(result["effective_level"], 3)
        self.assertEqual((result["effective_profile"]["extract"], result["effective_profile"]["supply"]), (64, 64))

    def test_manual_step_4_returns_to_step_3_after_four_hours(self):
        state, engine = self.make()
        state.configure({"mode": "manual", "manual_level": 4})
        until = state.data["max_level_until"]
        self.assertAlmostEqual(until - time.time(), 4 * 3600, delta=5)
        self.assertEqual(engine.resolve(now=until - 60)["effective_level"], 4)
        self.assertEqual(engine.resolve(now=until + 1)["effective_level"], 3)
        self.assertEqual(state.data["manual_level"], 3)
        self.assertIsNone(state.data["max_level_until"])

    def test_profile_can_be_calibrated(self):
        state, engine = self.make()
        # Older clients edit step 3 and 4 directly; that is the commissioning.
        state.configure({"profiles": {"3": {"extract": 72, "supply": 60}, "4": {"supply": 90}}})
        self.assertEqual(state.data["fan_settings"], {"supply": 60, "extract": 72, "offset": 25, "max_supply": 90, "max_extract": 100})
        state.configure({"mode": "manual", "manual_level": 2})
        result = engine.resolve()
        self.assertEqual((result["effective_profile"]["extract"], result["effective_profile"]["supply"]), (47, 35))
        with self.assertRaises(ControllerError):
            state.configure({"profiles": {"2": {"extract": 50}}})

    def test_rejects_supply_above_extract(self):
        state, _ = self.make()
        with self.assertRaises(ControllerError):
            state.configure({"fan_settings": {"extract": 50, "supply": 55}})
        state.configure({"fan_settings": {"extract": 50, "supply": 50}})

    def test_rejects_values_outside_the_dantherm_ranges(self):
        state, _ = self.make()
        for bad in ({"extract": 45}, {"supply": 92, "extract": 92}, {"offset": 9}, {"offset": 31},
                    {"max_extract": 60}, {"max_supply": 101}):
            with self.assertRaises(ControllerError, msg=bad):
                state.configure({"fan_settings": bad})

    def test_rh_raises_local_auto(self):
        state, engine = self.make()
        state.configure({"mode": "local_auto", "rh_setpoint": 50})
        engine.update_measurements(rh=61, co2=600)
        result = engine.resolve()
        self.assertEqual(result["effective_level"], 4)
        self.assertIn("RH", result["effective_reason"])

    def test_co2_raises_local_auto(self):
        state, engine = self.make()
        state.configure({"mode": "local_auto", "co2_setpoint": 800})
        engine.update_measurements(rh=40, co2=1250)
        result = engine.resolve()
        self.assertEqual(result["effective_level"], 4)
        self.assertIn("CO2", result["effective_reason"])

    def test_downshift_waits_for_hysteresis_and_delay(self):
        state, engine = self.make()
        state.configure({"mode": "local_auto", "downshift_delay_seconds": 30})
        engine.update_measurements(rh=70, co2=1800)
        high = engine.resolve(now=1000)
        self.assertEqual(high["effective_level"], 4)
        engine.boost_until = 0
        engine.update_measurements(rh=40, co2=500)
        still_high = engine.resolve(now=1010)
        self.assertEqual(still_high["effective_level"], 4)
        low = engine.resolve(now=1040)
        self.assertEqual(low["effective_level"], state.data["local_normal_level"])

    def test_smart_auto_uses_exact_ha_target_when_fresh(self):
        state, engine = self.make()
        state.configure({"mode": "smart_auto"})
        state.heartbeat("high", requested_level=2, reason="CO2 Bedroom")
        self.assertEqual(engine.resolve()["effective_level"], 2)
        state.heartbeat("boost", requested_level=4, reason="RH Bathroom")
        self.assertEqual(engine.resolve()["effective_level"], 4)
        # A six-step integration asking for 6 gets the maximum.
        state.heartbeat("boost", requested_level=6, reason="RH Bathroom")
        self.assertEqual(state.data["ha_requested_level"], 4)

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
        state.configure({"afterheat_setpoint": 35})
        reloaded = ControllerState(state.path)
        self.assertEqual(reloaded.data["afterheat_setpoint"], 35)
        with self.assertRaises(ControllerError):
            reloaded.configure({"afterheat_setpoint": 9})

    def test_afterheat_off_persists_and_new_setpoint_enables_it(self):
        state, _ = self.make()
        state.configure({"afterheat_enabled": False})
        self.assertFalse(ControllerState(state.path).data["afterheat_enabled"])
        state.configure({"afterheat_setpoint": 10})
        self.assertTrue(state.data["afterheat_enabled"])

    def test_bypass_persists_and_old_auto_migrates_to_off(self):
        state, _ = self.make()
        state.configure({"bypass": "on"})
        self.assertEqual(ControllerState(state.path).data["bypass"], "on")
        state.path.write_text('{"bypass": "auto"}')
        self.assertEqual(ControllerState(state.path).data["bypass"], "off")

    def test_bypass_and_fireplace_are_mutually_exclusive(self):
        state, _ = self.make()
        state.configure({"bypass": "on"})
        with self.assertRaises(ControllerError):
            state.configure({"fireplace_minutes": 15})
        state.configure({"bypass": "off", "fireplace_minutes": 15})
        with self.assertRaises(ControllerError):
            state.configure({"bypass": "on"})

    def test_bypass_write_is_deduplicated_and_separate_from_afterheat(self):
        calls = []
        state, _ = self.make()
        engine = ControllerEngine(state, HardwareAdapter(
            write_fan_pair=lambda extract, supply: None,
            set_bypass=lambda value: calls.append(("bypass", value)),
            set_fireplace=lambda enabled: None,
            set_afterheat_setpoint=lambda value: calls.append(("afterheat", value)),
        ))
        engine.apply()
        engine.apply()
        state.configure({"bypass": "on"})
        engine.apply()
        self.assertEqual(calls.count(("bypass", "off")), 1)
        self.assertEqual(calls.count(("bypass", "on")), 1)
        self.assertEqual(calls.count(("afterheat", 20)), 1)

    def test_fireplace_timer_expires_and_restores_selected_fan_profile(self):
        calls = []
        state, _ = self.make()
        engine = ControllerEngine(state, HardwareAdapter(
            write_fan_pair=lambda extract, supply: calls.append(("fan", extract, supply)),
            set_fireplace=lambda enabled: calls.append(("fireplace", enabled)),
            set_afterheat_setpoint=lambda value: None,
        ))
        state.configure({"mode": "manual", "manual_level": 2,
                         "fireplace_minutes": 15})
        engine.apply()
        self.assertTrue(state.snapshot()["fireplace"])
        self.assertGreater(state.snapshot()["fireplace_remaining_seconds"], 0)
        state.data["fireplace_until"] = time.time() - 1
        expired = engine.apply()
        self.assertFalse(expired["fireplace"])
        self.assertEqual(expired["fireplace_remaining_seconds"], 0)
        self.assertEqual(expired["mode"], "manual")
        self.assertEqual(expired["effective_level"], 2)
        self.assertEqual(calls.count(("fan", 39, 39)), 2)
        self.assertEqual(calls[-2:], [("fireplace", False), ("fan", 39, 39)])

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
        self.assertEqual(calls.count(("fan", 64, 64)), 1)
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

    def test_afterheat_refreshes_every_four_seconds_and_off_is_explicit(self):
        calls = []
        state, _ = self.make()
        engine = ControllerEngine(state, HardwareAdapter(
            write_fan_pair=lambda extract, supply: None,
            set_fireplace=lambda enabled: None,
            set_afterheat_setpoint=calls.append,
        ))
        engine.apply()
        engine.apply()
        self.assertEqual(calls, [20])
        engine.last_applied_at["afterheat_setpoint"] -= 4.1
        engine.apply()
        self.assertEqual(calls, [20, 20])
        state.configure({"afterheat_enabled": False})
        engine.apply()
        self.assertEqual(calls, [20, 20, None])

    def test_afterheat_off_while_unit_is_off(self):
        calls = []
        state, _ = self.make()
        engine = ControllerEngine(state, HardwareAdapter(
            write_fan_pair=lambda extract, supply: None,
            set_fireplace=lambda enabled: None,
            set_afterheat_setpoint=calls.append,
            set_standby=lambda enabled: None,
        ))
        engine.apply()
        state.configure({"standby_minutes": 60})
        engine.apply()
        self.assertEqual(calls, [20, None])
        state.configure({"standby_minutes": 0})
        engine.apply()
        self.assertEqual(calls, [20, None, 20])

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
