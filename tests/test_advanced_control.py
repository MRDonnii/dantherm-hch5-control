import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from advanced_control import absolute_humidity, airflow_plan
from controller_core import ControllerEngine, ControllerError, ControllerState, HardwareAdapter
from controller_runtime import ControllerRuntime


HOUSE = {"house_area_m2": 180, "ceiling_height_m": 2.3, "house_bathrooms": 1, "house_utility_rooms": 1}


class AirflowPlanTests(unittest.TestCase):
    def make_state(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return ControllerState(Path(temp.name) / "controller.json")

    def test_house_of_180_m2_needs_about_194_m3h_and_level_4(self):
        state = self.make_state()
        state.configure(HOUSE)
        plan = state.airflow_plan()
        self.assertEqual(plan["volume_m3"], 414)
        self.assertEqual(plan["supply_required_m3h"], 194)
        self.assertEqual(plan["extract_required_m3h"], 194)
        self.assertEqual(plan["wet_room_requirement_ls"], 45.0)
        # Default profiles, 375 m3/h at 100 %: level 3 supplies 161, level 4 218.
        self.assertEqual(plan["levels"][3]["supply_m3h"], 161)
        self.assertFalse(plan["levels"][3]["meets_requirement"])
        self.assertTrue(plan["levels"][4]["meets_requirement"])
        self.assertEqual(plan["base_level"], 4)
        self.assertEqual(plan["min_level"], 2)
        self.assertTrue(plan["estimated"])

    def test_wet_rooms_can_dominate_a_small_house(self):
        state = self.make_state()
        state.configure({"house_area_m2": 80, "house_bathrooms": 2, "house_utility_rooms": 1})
        plan = state.airflow_plan()
        self.assertEqual(plan["supply_required_m3h"], 86)
        self.assertEqual(plan["extract_required_m3h"], 216)  # 20 + 2*15 + 10 l/s

    def test_measured_airflow_overrides_estimate(self):
        state = self.make_state()
        state.configure({**HOUSE, "airflow_measured": {"3": {"supply": 200, "extract": 210}}})
        plan = state.airflow_plan()
        self.assertTrue(plan["levels"][3]["measured"])
        self.assertEqual(plan["base_level"], 3)

    def test_unreachable_requirement_is_reported(self):
        state = self.make_state()
        state.configure({"house_area_m2": 400, "airflow_max_m3h": 200})
        plan = airflow_plan(state.data, state.data["profiles"])
        self.assertFalse(plan["reachable"])
        self.assertEqual(plan["base_level"], 6)

    def test_invalid_values_are_rejected(self):
        state = self.make_state()
        for patch in (
            {"house_area_m2": 5}, {"ceiling_height_m": 9}, {"airflow_measured": {"7": {"supply": 100}}},
            {"airflow_measured": {"2": {"supply": 5000}}}, {"sizing_enabled": "yes"},
        ):
            with self.subTest(patch=patch), self.assertRaises(ControllerError):
                state.configure(patch)


class AdvancedEngineTests(unittest.TestCase):
    def make_engine(self, hardware=None):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        state = ControllerState(Path(temp.name) / "controller.json")
        return ControllerEngine(state, hardware or HardwareAdapter())

    def test_sizing_sets_base_level_and_floors_night(self):
        engine = self.make_engine()
        engine.config.configure({**HOUSE, "sizing_enabled": True, "night_enabled": True,
                                 "night_start": "00:00", "night_end": "00:00", "night_level": 1})
        engine.update_measurements(rh=40, co2=500)
        result = engine.resolve()
        self.assertEqual(result["effective_normal_level"], 4)
        self.assertEqual(result["effective_level"], 2)
        self.assertTrue(result["sizing_floor_active"])

    def test_sizing_never_overrides_manual(self):
        engine = self.make_engine()
        engine.config.configure({**HOUSE, "sizing_enabled": True, "mode": "manual", "manual_level": 1})
        self.assertEqual(engine.resolve()["effective_level"], 1)

    def test_absolute_humidity(self):
        self.assertAlmostEqual(absolute_humidity(20, 50), 8.63, places=1)
        self.assertIsNone(absolute_humidity(None, 50))

    def test_humidity_ignored_when_outdoor_air_is_wetter(self):
        engine = self.make_engine()
        engine.config.configure({"humidity_smart_enabled": True, "rh_setpoint": 50})
        # Warm humid summer day: 24 C / 80 % outside, 22 C / 60 % inside.
        engine.update_measurements(rh=60, co2=500, outdoor=24)
        engine.set_external({"outdoor_rh": 80, "extract_temp": 22})
        result = engine.resolve()
        self.assertFalse(result["humidity_drying"])
        self.assertEqual(result["effective_level"], 3)
        self.assertIn("udeluften tørrer ikke", result["effective_reason"])

        # Cold dry winter air dries the same indoor air: RH demand counts.
        engine.update_measurements(outdoor=2)
        engine.set_external({"outdoor_rh": 90, "extract_temp": 22})
        result = engine.resolve()
        self.assertTrue(result["humidity_drying"])
        self.assertGreater(result["effective_level"], 3)

    def test_dry_protection_caps_level_unless_co2_is_high(self):
        engine = self.make_engine()
        engine.config.configure({"dry_protection_enabled": True, "dry_rh_limit": 30, "dry_max_level": 2})
        engine.update_measurements(rh=25, co2=600, outdoor=-5)
        engine.set_external({"outdoor_rh": 80, "extract_temp": 21})
        result = engine.resolve()
        self.assertTrue(result["dry_protection_active"])
        self.assertEqual(result["effective_level"], 2)
        self.assertEqual(result["effective_source"], "dry_protection")

        engine.set_external({"outdoor_rh": 80, "extract_temp": 21, "max_room_co2": 1100})
        result = engine.resolve()
        self.assertFalse(result["dry_protection_active"])

    def test_afterheat_follows_room_one_degree_per_interval(self):
        written = []
        hardware = HardwareAdapter(set_afterheat_setpoint=written.append,
                                   write_fan_pair=lambda *_: None, set_fireplace=lambda *_: None)
        engine = self.make_engine(hardware)
        engine.config.configure({"afterheat_setpoint": 20, "afterheat_room_enabled": True,
                                 "afterheat_room_target": 21, "afterheat_room_gain": 2,
                                 "afterheat_room_min": 17, "afterheat_room_max": 24,
                                 "afterheat_room_step_minutes": 10})
        engine.set_external({"afterheat_room_temperature": 19.0})  # wants 20 + 2*2 = 24
        result = engine.resolve(now=1000.0)
        self.assertEqual(result["afterheat_effective_setpoint"], 21)
        self.assertEqual(result["afterheat_room_state"], "rising")
        self.assertEqual(engine.resolve(now=1000.0 + 300)["afterheat_effective_setpoint"], 21)
        self.assertEqual(engine.resolve(now=1000.0 + 600)["afterheat_effective_setpoint"], 22)
        engine.apply()  # resolves on the real clock, so the next step may be taken
        self.assertEqual(written[-1], engine.afterheat_effective)

        engine.set_external({})
        result = engine.resolve(now=5000.0)
        self.assertEqual(result["afterheat_effective_setpoint"], 20)
        self.assertEqual(result["afterheat_room_state"], "no_room_temperature")

    def test_afterheat_room_range_is_validated(self):
        engine = self.make_engine()
        with self.assertRaises(ControllerError):
            engine.config.configure({"afterheat_room_min": 25, "afterheat_room_max": 20})
        with self.assertRaises(ControllerError):
            engine.config.configure({"afterheat_room_source": "kitchen"})


class FireplaceAutoTests(unittest.TestCase):
    def make_runtime(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        runtime = ControllerRuntime(gateway_state={}, hardware=HardwareAdapter(),
                                    state_path=Path(temp.name) / "controller.json")
        runtime.hardware_writes_allowed = lambda: False
        return runtime

    @staticmethod
    def stove(runtime, temperature):
        runtime.room_inputs({"source": "home_assistant", "valid_for_s": 180, "rooms": {
            "Brændeovn": {"temperature": temperature, "control": False},
            "Stue": {"temperature": 21.0, "humidity": 45, "co2": 600},
        }})
        runtime.refresh_measurements()

    def test_stove_temperature_holds_fireplace_with_hysteresis(self):
        runtime = self.make_runtime()
        runtime.configure({"fireplace_auto_enabled": True, "fireplace_auto_source": "room:Brændeovn",
                           "fireplace_auto_on_temp": 25, "fireplace_auto_off_temp": 24,
                           "fireplace_afterrun_minutes": 15})
        t0 = time.time()
        self.stove(runtime, 24.5)
        runtime._update_fireplace_auto(now=t0)
        self.assertFalse(runtime.fireplace_auto_active)
        self.stove(runtime, 26.0)
        runtime._update_fireplace_auto(now=t0)
        self.assertTrue(runtime.fireplace_auto_active)
        self.assertTrue(runtime.config.data["fireplace"])
        self.assertEqual(runtime.config.data["fireplace_until"], t0 + 15 * 60)
        self.stove(runtime, 24.5)  # between off and on: stays on
        runtime._update_fireplace_auto(now=t0 + 100)
        self.assertTrue(runtime.fireplace_auto_active)
        self.stove(runtime, 23.0)
        runtime._update_fireplace_auto(now=t0 + 200)
        self.assertFalse(runtime.fireplace_auto_active)
        # Afterrun keeps the unit in fireplace mode until it expires.
        self.assertEqual(runtime.config.data["fireplace_until"], t0 + 100 + 15 * 60)

    def test_stove_room_never_drives_air_quality(self):
        runtime = self.make_runtime()
        runtime.configure({"fireplace_auto_source": "room:Brændeovn"})
        runtime.room_inputs({"source": "home_assistant", "valid_for_s": 180, "rooms": {
            "Brændeovn": {"temperature": 30.0, "humidity": 95},
        }})
        self.assertNotEqual(runtime.smart_controlling_room, "Brændeovn")
        self.assertIsNone(runtime.snapshot()["smart_max_rh_room"])

    def test_external_switch_and_manual_off_block_until_clear(self):
        runtime = self.make_runtime()
        runtime.configure({"fireplace_auto_enabled": True})
        snapshot = runtime.external_signals({"fireplace": True, "valid_for_s": 300})
        self.assertTrue(snapshot["fireplace_auto_active"])
        self.assertEqual(snapshot["fireplace_auto_reason"], "switch")
        self.assertTrue(snapshot["fireplace"])

        runtime.configure({"fireplace": False})
        runtime._update_fireplace_auto()
        self.assertFalse(runtime.config.data["fireplace"])
        self.assertEqual(runtime.fireplace_auto_reason, "blocked_until_clear")

        runtime.external_signals({"fireplace": False})
        runtime.external_signals({"fireplace": True})
        self.assertTrue(runtime.fireplace_auto_active)

    def test_maximum_duration_stops_fireplace(self):
        runtime = self.make_runtime()
        runtime.configure({"fireplace_auto_enabled": True, "fireplace_max_hours": 1})
        runtime.external_signals({"fireplace": True, "valid_for_s": 900})
        start = runtime.fireplace_auto_started_at
        runtime.fireplace_signal_until = start + 99999
        runtime._update_fireplace_auto(now=start + 3601)
        self.assertFalse(runtime.fireplace_auto_active)
        self.assertEqual(runtime.fireplace_auto_reason, "max_duration")

    def test_signal_validation(self):
        runtime = self.make_runtime()
        with self.assertRaises(ControllerError):
            runtime.external_signals({"fireplace": "on"})
        with self.assertRaises(ControllerError):
            runtime.external_signals({"fireplace": True, "valid_for_s": 5})

    def test_afterheat_room_auto_falls_back_to_t3_without_ha_rooms(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        runtime = ControllerRuntime(gateway_state={"extract_temp": 21.7, "hrc2_t5_temperature": 30.0},
                                    hardware=HardwareAdapter(), state_path=Path(temp.name) / "controller.json")
        self.assertEqual(runtime.config.data["afterheat_room_source"], "auto")
        runtime.refresh_measurements()
        self.assertEqual(runtime.engine.external["afterheat_room_temperature"], 21.7)
        self.assertEqual(runtime.snapshot()["afterheat_room_source_used"], "t3")

    def test_afterheat_room_auto_uses_owner_rooms_without_bathrooms_or_sensor_rooms(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        runtime = ControllerRuntime(gateway_state={"extract_temp": 24.0},
                                    hardware=HardwareAdapter(), state_path=Path(temp.name) / "controller.json")
        runtime.hardware_writes_allowed = lambda: False
        runtime.configure({"fireplace_auto_source": "room:Brændeovn"})
        runtime.room_inputs({"source": "home_assistant", "valid_for_s": 180, "rooms": {
            "Living room": {"temperature": 21.0, "control": False},
            "Bedroom": {"temperature": 19.0, "co2": 700},
            "Bathroom": {"temperature": 26.0, "humidity": 80},
            "Brændeovn": {"temperature": 40.0, "control": False},
        }})
        runtime.refresh_measurements()
        self.assertEqual(runtime.engine.external["afterheat_room_temperature"], 20.0)
        self.assertEqual(runtime.snapshot()["afterheat_room_source_used"], "ha_average")

    def test_ha_average_room_temperature_excludes_sensor_rooms(self):
        runtime = self.make_runtime()
        runtime.configure({"afterheat_room_source": "ha_average", "fireplace_auto_source": "room:Brændeovn"})
        self.stove(runtime, 40.0)
        self.assertEqual(runtime.engine.external["afterheat_room_temperature"], 21.0)
        self.assertEqual(runtime.engine.external["stove_temperature"], 40.0)


if __name__ == "__main__":
    unittest.main()
