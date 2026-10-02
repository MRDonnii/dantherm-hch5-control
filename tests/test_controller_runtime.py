import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from controller_core import ControllerError, HardwareAdapter
from controller_runtime import ControllerRuntime


class ControllerRuntimeTests(unittest.TestCase):
    def make_runtime(self, gateway_state=None, steps=4):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        runtime = ControllerRuntime(
            gateway_state=gateway_state or {},
            hardware=HardwareAdapter(),
            state_path=Path(temp.name) / "controller.json",
        )
        if steps == 6:
            runtime.config.configure({"fan_step_count": 6, "local_normal_level": 3})
        return runtime

    @staticmethod
    def decision(runtime, rooms):
        runtime.room_inputs({
            "source": "home_assistant", "valid_for_s": 180, "rooms": rooms,
        })
        return runtime.smart_requested_level

    def test_weather_humidity_requires_fresh_bus_t1(self):
        state = {"outdoor_temp": 15.4, "bus_traffic": True, "bus_last_frame_age": 1}
        runtime = self.make_runtime(state)
        runtime.external_signals({"weather": {"source": "weather.home", "condition": "cloudy",
                                               "temperature_c": 16, "humidity_pct": 60}})
        runtime.config.data["outdoor_humidity_source"] = "weather"
        self.assertIsNotNone(runtime._outdoor_humidity())
        state["bus_last_frame_age"] = 12
        self.assertIsNone(runtime._outdoor_humidity())
        self.assertEqual(runtime.weather_snapshot()["humidity_reason"], "T1 er ikke tilgængelig")

    def test_afterheat_outdoor_lockout_is_reported_at_15_c_and_above(self):
        # HAC1 never heats at 15 C outdoor or above; report it as a lockout.
        for outdoor, expected in ((14.15, False), (15.0, True), (15.63, True), (None, None)):
            with self.subTest(outdoor=outdoor):
                state = {} if outdoor is None else {"outdoor_temp": outdoor}
                snapshot = self.make_runtime(state).snapshot()
                self.assertIs(snapshot["actual_afterheat_outdoor_lockout"], expected)
                self.assertEqual(snapshot["afterheat_outdoor_cutoff"], 15.0)

    def test_setting_changes_are_logged_with_source(self):
        import os
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        log = Path(temp.name) / "change-log.jsonl"
        os.environ["DANTHERM_CHANGE_LOG"] = str(log)
        self.addCleanup(os.environ.pop, "DANTHERM_CHANGE_LOG", None)
        runtime = self.make_runtime()
        runtime.configure({"afterheat_setpoint": 25}, apply=False, source="webui:john")
        runtime.configure({"afterheat_setpoint": 25}, apply=False, source="home_assistant")
        self.assertEqual(len(runtime.change_log), 1)
        event = runtime.change_log[0]
        self.assertEqual(event["source"], "webui:john")
        self.assertEqual(event["changes"]["afterheat_setpoint"], [20, 25])
        self.assertEqual(log.read_text(encoding="utf-8").count("\n"), 1)
        self.assertEqual(runtime.snapshot()["change_log"][0]["source"], "webui:john")

    def test_energy_signals_are_read_only_and_expire(self):
        runtime = self.make_runtime()
        applied = []
        runtime.apply_once = lambda: applied.append("hardware")
        result = runtime.external_signals({
            "unit_energy_measured_today_kwh": 1.37,
            "electricity_price_dkk_kwh": 2.06,
            "heat_price_dkk_kwh": 0.596,
            "valid_for_s": 30,
        })
        self.assertEqual(result["unit_energy_measured_today_kwh"], 1.37)
        self.assertEqual(result["heat_price_dkk_kwh"], 0.596)
        self.assertEqual(applied, [])
        runtime.energy_signals_until = time.time() - 1
        self.assertIsNone(runtime.snapshot()["unit_energy_measured_today_kwh"])
        with self.assertRaises(ControllerError):
            runtime.external_signals({"electricity_price_dkk_kwh": -1})

    def test_afterheat_coil_is_validated_and_never_applies_hardware(self):
        runtime = self.make_runtime()
        applied = []
        runtime.hardware_writes_allowed = lambda: True
        runtime.apply_once = lambda: applied.append("hardware")

        self.assertEqual(runtime.snapshot()["afterheat_coil"], "electric")
        self.assertEqual(runtime.configure({"afterheat_coil": "water"})["afterheat_coil"], "water")
        self.assertEqual(applied, [])
        with self.assertRaises(ControllerError):
            runtime.configure({"afterheat_coil": "gas"})
        self.assertEqual(runtime.snapshot()["afterheat_coil"], "water")

    def test_t3_t5_updates_are_local_and_do_not_apply_hardware(self):
        runtime = self.make_runtime()
        applied = []
        runtime.hardware_writes_allowed = lambda: True
        runtime.apply_once = lambda: applied.append("hardware")

        runtime.configure({"t3_setpoint": 22})
        runtime.configure({"t5_setpoint": 24})

        self.assertEqual(runtime.config.data["t3_setpoint"], 22)
        self.assertEqual(runtime.config.data["t5_setpoint"], 24)
        self.assertEqual(applied, [])

    def test_stale_t2_t2ah_and_t5_are_not_reported_as_live_values(self):
        stale_sample = time.monotonic() - 46
        runtime = self.make_runtime({
            "supply_temperature": 21.5,
            "supply_temp": 21.5,
            "supply_temperature_sample_monotonic": stale_sample,
            "temperature_sample_monotonic": stale_sample,
            "heating_coil_after_temperature": 23.2,
            "heating_coil_after_temperature_sample_monotonic": stale_sample,
            "heating_coil_frost_temperature": 6.8,
            "heating_coil_frost_temperature_sample_monotonic": stale_sample,
            "hrc2_t5_temperature": 23.2,
            "hrc2_t5_temperature_sample_monotonic": stale_sample,
            "extract_temp": 20.1,
        })

        snapshot = runtime.snapshot()

        self.assertIsNone(snapshot["actual_supply_before_heater_temperature"])
        self.assertIsNone(snapshot["actual_supply_air_temperature"])
        self.assertIsNone(snapshot["actual_afterheat_frost_temperature"])
        # The stale T5 is not used; without HA rooms the room is the extract air (T3).
        self.assertEqual(snapshot["measurements"]["room"], 20.1)

    def test_free_cooling_uses_the_ha_room_average_not_a_missing_hrc2(self):
        # Without an HRC2 the unit reports T5 as 0 after a power cut.
        runtime = self.make_runtime({"hrc2_t5_temperature": 0.0, "hrc2_t5_temperature_sample_monotonic": time.monotonic(),
                                     "extract_temp": 22.0})
        runtime.room_inputs({"source": "home_assistant", "valid_for_s": 180, "rooms": {
            "Hus": {"temperature": 23.4, "control": False}}})
        self.assertEqual(runtime.snapshot()["measurements"]["room"], 23.4)

    def test_generic_temperature_timestamp_does_not_refresh_t2(self):
        runtime = self.make_runtime({
            "supply_temperature": 21.5,
            "supply_temp": 21.5,
            "temperature_sample_monotonic": time.monotonic(),
        })

        self.assertIsNone(runtime.snapshot()["actual_supply_before_heater_temperature"])

    def test_bypass_travel_time_and_direction_are_reported(self):
        # The damper reports no position, so progress is the time since it
        # left its end position against the measured ~180 s travel.
        state = {"bypass_raw": 64, "bypass_travel_direction": "opening",
                 "bypass_travel_started_monotonic": time.monotonic() - 42}
        snapshot = self.make_runtime(state).snapshot()
        self.assertEqual(snapshot["actual_bypass_travel_direction"], "opening")
        self.assertAlmostEqual(snapshot["actual_bypass_travel_seconds"], 42, delta=1)
        self.assertEqual(snapshot["bypass_travel_expected_seconds"], 180)
        resting = self.make_runtime({"bypass_raw": 255, "bypass_travel_started_monotonic": None}).snapshot()
        self.assertIsNone(resting["actual_bypass_travel_seconds"])
        self.assertIsNone(resting["actual_bypass_travel_direction"])

    def test_smart_auto_can_request_every_level_1_to_6_from_co2(self):
        expected = {250: 1, 700: 2, 800: 3, 900: 4, 1100: 5, 1300: 6}
        for co2, level in expected.items():
            with self.subTest(co2=co2):
                runtime = self.make_runtime(steps=6)
                self.assertEqual(self.decision(runtime, {"Room": {"co2": co2}}), level)

    def test_smart_auto_uses_the_four_dantherm_steps_from_co2(self):
        expected = {250: 1, 700: 2, 800: 3, 900: 4, 1300: 4}
        for co2, level in expected.items():
            with self.subTest(co2=co2):
                runtime = self.make_runtime()
                self.assertEqual(self.decision(runtime, {"Room": {"co2": co2}}), level)

    def test_bathroom_rh_uses_separate_threshold_and_level_cap(self):
        runtime = self.make_runtime()
        runtime.config.configure({
            "bathroom_rh_setpoint": 65,
            "bathroom_rh_hysteresis": 5,
            "bathroom_max_level": 4,
        })
        # A bathroom can be humid without immediately forcing full boost.
        self.assertLessEqual(self.decision(runtime, {"Bath": {"humidity": 58}}), 4)
        self.assertEqual(self.decision(runtime, {"Bath": {"humidity": 78}}), 4)
        # A shower-like fast rise starts drying, still at the configured level.
        runtime = self.make_runtime()
        runtime.config.configure({"bathroom_max_level": 4})
        runtime._room_rh_history["Bath"].append((time.time() - 300, 48.0))
        self.assertEqual(self.decision(runtime, {"Bath": {"humidity": 58}}), 4)
        self.assertEqual(runtime.smart_controlling_metric, "humidity")

    def test_normal_room_rh_keeps_global_policy(self):
        runtime = self.make_runtime()
        self.assertGreaterEqual(
            self.decision(runtime, {"Utility": {"humidity": 58, "room_type": "normal"}}),
            4,
        )

    def test_room_priority_changes_mild_response(self):
        cases = (("low", 3), ("auto", 4), ("normal", 4), ("high", 5), ("critical", 6))
        for priority, expected in cases:
            with self.subTest(priority=priority):
                runtime = self.make_runtime(steps=6)
                self.assertEqual(
                    self.decision(runtime, {"Room": {"co2": 900, "priority": priority}}),
                    expected,
                )

    def test_monitor_only_room_does_not_control_but_remains_diagnostic(self):
        runtime = self.make_runtime()
        level = self.decision(runtime, {
            "Monitor": {"co2": 2000, "control": False, "priority": "critical"},
            "Control": {"co2": 700, "control": True},
        })
        self.assertEqual(level, 2)
        snapshot = runtime.snapshot()
        self.assertEqual(snapshot["smart_max_co2"], 2000)
        self.assertEqual(snapshot["smart_max_co2_room"], "Monitor")

    def test_severe_auto_room_beats_mild_high_priority_room(self):
        runtime = self.make_runtime(steps=6)
        self.assertEqual(self.decision(runtime, {
            "Severe": {"co2": 1300, "priority": "auto"},
            "Mild": {"co2": 850, "priority": "high"},
        }), 6)
        self.assertEqual(runtime.smart_controlling_room, "Severe")

    def test_unit_sensor_is_combined_with_home_assistant_rooms(self):
        runtime = self.make_runtime({"co2": 1300, "humidity": 40})
        self.assertEqual(self.decision(runtime, {"Bedroom": {"co2": 600}}), 4)
        self.assertEqual(runtime.smart_controlling_room, "HCH5 / lokale sensorer")

    def test_invalid_metadata_measurement_and_room_count_are_rejected(self):
        runtime = self.make_runtime()
        cases = (
            {"Room": {"co2": "bad"}},
            {"Room": {"co2": 900, "priority": "urgent"}},
            {f"Room {index}": {"co2": 800} for index in range(33)},
        )
        for rooms in cases:
            with self.assertRaises(ControllerError):
                self.decision(runtime, rooms)

    def test_stale_smart_input_falls_back_to_local_auto(self):
        runtime = self.make_runtime({"co2": 600, "humidity": 40})
        runtime.config.configure({"mode": "smart_auto", "downshift_delay_seconds": 30})
        self.decision(runtime, {"Bedroom": {"co2": 1600}})
        runtime.engine.current_auto_level = 6
        runtime.engine.boost_until = 0
        runtime.engine.last_level_change = 1
        runtime.config.data["ha_last_seen"] = time.time() - 999
        result = runtime.engine.resolve(now=time.time())
        self.assertEqual(result["effective_source"], "local_fallback")
        self.assertLess(result["effective_level"], 6)


if __name__ == "__main__":
    unittest.main()
