import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from advanced_control import AIR_HEAT_CAPACITY, balanced_profiles, rpm_at_percent, side_constants  # noqa: E402
from air_balance import (  # noqa: E402
    FAN_HEAT_SHARE, HeatBalanceLearner, adopt, balance_from_temperatures, dew_point, fan_powers, summarize,
)
from controller_core import ControllerError, ControllerState, HardwareAdapter  # noqa: E402
from controller_runtime import ControllerRuntime  # noqa: E402
from diagnostics import Diagnostics  # noqa: E402

HOUSE = {"house_area_m2": 180, "ceiling_height_m": 2.3, "house_bathrooms": 1, "house_utility_rooms": 1}
CURVE = {"rpm_at_0": 557.0, "rpm_per_percent": 24.0, "samples": 6}
REFERENCE_FANS = {"extract": 70, "supply": 55, "offset": 25}


def exchanger(t1, t3, supply_m3h, extract_m3h, *, ntu=9.0, supply_fan_w=0.0, extract_fan_w=0.0):
    """Counter-flow core with the fan heat the balance takes out (half of each fan)."""
    c_supply = supply_m3h * AIR_HEAT_CAPACITY / 3600.0
    c_extract = extract_m3h * AIR_HEAT_CAPACITY / 3600.0
    c_min, c_max = min(c_supply, c_extract), max(c_supply, c_extract)
    ratio = c_min / c_max
    e = math.exp(-ntu * (1.0 - ratio))
    effectiveness = (1.0 - e) / (1.0 - ratio * e) if ratio < 1.0 else ntu / (1.0 + ntu)
    heat = effectiveness * c_min * (t3 - t1)
    t2 = t1 + heat / c_supply + FAN_HEAT_SHARE * supply_fan_w / c_supply
    t4 = t3 - heat / c_extract + FAN_HEAT_SHARE * extract_fan_w / c_extract
    return t2, t4


class BalancedProfileTests(unittest.TestCase):
    def make_state(self, **patch):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        state = ControllerState(Path(temp.name) / "controller.json")
        state.configure({**HOUSE, **patch})
        return state

    def test_equal_ducts_keep_extract_five_percent_above_supply_on_every_level(self):
        state = self.make_state()
        levels = balanced_profiles(state.data, state.data["profiles"])
        previous = 0
        for level, values in levels.items():
            self.assertEqual(values["extract"], state.data["profiles"][level]["extract"])
            self.assertLessEqual(abs(values["excess_percent"] - 5.0), 1.5, (level, values))
            self.assertGreater(values["supply"], previous)
            self.assertTrue(values["reached"])
            previous = values["supply"]
        # Equal gears on equal ducts give no underpressure at all.
        default = state.balance_status()["levels"]
        self.assertEqual(default[1]["current_excess_percent"], 0.0)
        self.assertEqual(default[4]["current_excess_percent"], 0.0)

    def test_stronger_supply_ducts_get_a_lower_supply_percentage(self):
        state = self.make_state()
        equal = balanced_profiles(state.data, state.data["profiles"])
        state.configure({"balance_ratio_mode": "fixed", "balance_duct_ratio": 1.14})
        stronger = balanced_profiles(state.data, state.data["profiles"])
        for level in range(1, 5):
            self.assertLess(stronger[level]["supply"], equal[level]["supply"])
            self.assertLessEqual(abs(stronger[level]["excess_percent"] - 5.0), 1.5)

    def test_reference_house_ladder(self):
        state = self.make_state()
        state.set_fan_curve(CURVE)
        snapshot = state.configure({"balance_enabled": True, "balance_ratio_mode": "fixed",
                                    "balance_duct_ratio": 1.14, "fan_settings": REFERENCE_FANS})
        pairs = {level: (values["supply"], values["extract"]) for level, values in snapshot["profiles"].items()}
        # Extract follows the Dantherm ladder 70 - 25 - 25 and 100; supply is balanced.
        self.assertEqual(pairs, {1: (13, 20), 2: (34, 45), 3: (55, 70), 4: (80, 100)})
        self.assertEqual(snapshot["airflow_plan"]["base_level"], 3)
        self.assertEqual(snapshot["balance"]["duct_ratio_source"], "fixed")

    def test_balance_owns_supply_while_on_and_leaves_it_when_off(self):
        state = self.make_state()
        state.configure({"balance_enabled": True})
        balanced = {level: values["supply"] for level, values in state.data["profiles"].items()}
        # A form resending every current value is fine.
        state.configure({"profiles": {str(level): {"extract": values["extract"], "supply": values["supply"]}
                                      for level, values in state.data["profiles"].items()}})
        with self.assertRaises(ControllerError):
            state.configure({"profiles": {"3": {"supply": balanced[3] - 3}}})
        # Changing extract moves supply with it.
        state.configure({"fan_settings": {"extract": 70}})
        self.assertGreater(state.data["profiles"][3]["supply"], balanced[3])
        # Off: the supply fan runs its own commissioned gears again.
        state.configure({"balance_enabled": False, "fan_settings": {"supply": 60}})
        self.assertEqual({level: values["supply"] for level, values in state.data["profiles"].items()},
                         {1: 10, 2: 35, 3: 60, 4: 100})

    def test_step_3_must_stay_in_the_dantherm_range(self):
        state = self.make_state(balance_enabled=True)
        before = dict(state.data["profiles"])
        with self.assertRaises(ControllerError):
            state.configure({"fan_settings": {"extract": 30}})
        self.assertEqual(state.data["profiles"], before)

    def test_a_rejected_patch_changes_nothing(self):
        state = self.make_state()
        with self.assertRaises(ControllerError):
            state.configure({"balance_enabled": True, "balance_extract_excess_percent": 40})
        self.assertFalse(state.data["balance_enabled"])
        self.assertEqual(state.data["balance_extract_excess_percent"], 5.0)

    def test_measured_airflow_on_both_sides_sets_the_duct_ratio(self):
        state = self.make_state()
        # Installer measured level 3 (gear 55/64): supply 230, extract 205 m3/h.
        state.configure({"fan_settings": {"supply": 55}})
        state.configure({"airflow_measured": {"3": {"supply": 230, "extract": 205}}})
        measured = state.data["airflow_measured"]["3"]
        self.assertEqual((measured["supply_percent"], measured["extract_percent"]), (55, 64))
        k = side_constants(state.data)
        self.assertEqual(k["source"], "measured")
        curve = {"rpm_at_0": 557.0, "rpm_per_percent": 24.0}
        expected = (230 / rpm_at_percent(55, curve)) / (205 / rpm_at_percent(64, curve))
        self.assertAlmostEqual(k["ratio"], expected, places=3)
        state.configure({"balance_enabled": True})
        plan = state.airflow_plan()
        # The measured value no longer matches the new supply percentage, so
        # level 3 supply is the fitted estimate; extract stays measured.
        self.assertNotEqual(state.data["profiles"][3]["supply"], 55)
        self.assertEqual(plan["levels"][3]["extract_m3h"], 205)
        self.assertEqual(state.balance_status()["duct_ratio_source"], "measured")
        for values in state.balance_status()["levels"].values():
            self.assertLessEqual(abs(values["excess_percent"] - 5.0), 1.5)

    def test_measurements_keep_the_percentage_they_were_taken_at(self):
        state = self.make_state()
        state.configure({"fan_settings": {"supply": 60}})
        state.configure({"airflow_measured": {"2": {"supply": 150}}})
        state.configure({"fan_settings": {"supply": 62}})
        # Saving the form again with the same value keeps the old percentage.
        state.configure({"airflow_measured": {"2": {"supply": 150}}})
        self.assertEqual(state.data["airflow_measured"]["2"]["supply_percent"], 35)
        self.assertFalse(state.airflow_plan()["levels"][2]["measured"])
        state.configure({"airflow_measured": {"2": {"supply": 158, "supply_percent": 37}}})
        self.assertTrue(state.airflow_plan()["levels"][2]["measured"])
        with self.assertRaises(ControllerError):
            state.configure({"airflow_measured": {"2": {"supply": 158, "supply_percent": 130}}})

    def test_learned_ratio_is_used_only_when_trusted_and_in_auto(self):
        state = self.make_state(balance_enabled=True, balance_duct_ratio=1.0)
        equal = dict(state.data["profiles"])
        # Windows so far, but not yet two nights that agree: no ratio in use.
        changed = state.set_balance_learned({"windows": [], "ratio": 1.15, "ratio_in_use": None, "confidence": "low"})
        self.assertFalse(changed)
        self.assertEqual(state.balance_status()["duct_ratio_source"], "fixed")
        changed = state.set_balance_learned({"windows": [], "ratio": 1.15, "ratio_in_use": 1.15, "confidence": "ok"})
        self.assertTrue(changed)
        # Old windows ageing out over the summer keep the trusted ratio in use.
        self.assertFalse(state.set_balance_learned({"windows": [], "ratio": None, "ratio_in_use": 1.15, "confidence": "none"}))
        self.assertEqual(state.balance_status()["duct_ratio_source"], "learned")
        self.assertEqual(state.balance_status()["duct_ratio_source"], "learned")
        self.assertLess(state.data["profiles"][4]["supply"], equal[4]["supply"])
        state.configure({"balance_ratio_mode": "fixed"})
        self.assertEqual(state.data["profiles"], equal)
        state.configure({"balance_ratio_mode": "auto", "balance_learning_reset": True})
        self.assertEqual(state.data["balance_learned"]["windows"], [])
        self.assertEqual(state.data["profiles"], equal)

    def test_balance_settings_are_validated(self):
        state = self.make_state()
        for patch in ({"balance_enabled": "yes"}, {"balance_ratio_mode": "magic"}, {"balance_duct_ratio": 3},
                      {"balance_extract_excess_percent": -1}, {"balance_learning_reset": "now"}):
            with self.subTest(patch=patch), self.assertRaises(ControllerError):
                state.configure(patch)

    def test_balance_survives_a_restart(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "controller.json"
        state = ControllerState(path)
        state.configure({**HOUSE, "balance_enabled": True, "balance_ratio_mode": "fixed", "balance_duct_ratio": 1.2})
        again = ControllerState(path)
        self.assertEqual(again.data["profiles"], state.data["profiles"])
        self.assertTrue(again.balance_status()["enabled"])


class HeatBalanceTests(unittest.TestCase):
    def test_recovers_the_airflow_ratio_of_a_counterflow_core(self):
        for ratio in (0.85, 1.0, 1.15):
            supply_rpm, extract_rpm = 2300.0, 2600.0
            supply_m3h, extract_m3h = 0.12 * ratio * supply_rpm, 0.12 * extract_rpm
            fans = fan_powers(supply_rpm, extract_rpm, None)
            t2, t4 = exchanger(7.0, 18.0, supply_m3h, extract_m3h,
                               supply_fan_w=float(fans["supply"]), extract_fan_w=float(fans["extract"]))
            result = balance_from_temperatures(7.0, t2, 18.0, t4, supply_rpm=supply_rpm, extract_rpm=extract_rpm,
                                               supply_m3h=supply_m3h, extract_m3h=extract_m3h)
            self.assertAlmostEqual(result["airflow_ratio"], supply_m3h / extract_m3h, places=3)
            self.assertAlmostEqual(result["duct_ratio"], ratio, places=3)

    def test_meter_power_is_split_by_speed(self):
        split = fan_powers(1200, 1500, 20.0, idle_w=2.0)
        self.assertAlmostEqual(float(split["supply"]) + float(split["extract"]), 18.0)
        self.assertLess(float(split["supply"]), float(split["extract"]))
        self.assertEqual(split["source"], "meter")

    def test_dew_point(self):
        self.assertAlmostEqual(dew_point(20.0, 50.0), 9.3, delta=0.1)
        self.assertIsNone(dew_point(20.0, 0.0))

    def feed(self, learner, start, seconds, *, t1=7.0, t3=18.0, ratio=1.15, rh=40.0, pair=(40, 55), step=2.0, **extra):
        curve = {"rpm_at_0": 557.0, "rpm_per_percent": 24.0}
        supply_rpm, extract_rpm = rpm_at_percent(pair[0], curve), rpm_at_percent(pair[1], curve)
        supply_m3h, extract_m3h = 0.12 * ratio * supply_rpm, 0.12 * extract_rpm
        fans = fan_powers(supply_rpm, extract_rpm, None)
        t2, t4 = exchanger(t1, t3, supply_m3h, extract_m3h,
                           supply_fan_w=float(fans["supply"]), extract_fan_w=float(fans["extract"]))
        verdicts = []
        now = start
        while now < start + seconds:
            sample = {"t1": t1, "t2": t2, "t3": t3, "t4": t4, "rh": rh, "supply_percent": pair[0],
                      "extract_percent": pair[1], "supply_rpm": supply_rpm, "extract_rpm": extract_rpm,
                      "supply_m3h": supply_m3h, "extract_m3h": extract_m3h, "power_w": None, "bypass": False,
                      "blocked": None, **extra}
            verdict = learner.observe(sample, now)
            if verdict:
                verdicts.append(verdict)
            now += step
        return verdicts, now

    def test_learner_waits_for_steady_air_then_measures_windows(self):
        learner = HeatBalanceLearner()
        verdicts, now = self.feed(learner, 0.0, 1799)
        self.assertEqual(verdicts, [])
        self.assertEqual(learner.status["state"], "settling")
        verdicts, now = self.feed(learner, now, 2 * 900 + 10)
        self.assertEqual(len(verdicts), 2)
        self.assertTrue(all(v["accepted"] for v in verdicts))
        self.assertAlmostEqual(verdicts[0]["duct_ratio"], 1.15, delta=0.005)

    def test_learner_rejects_small_differences_condensation_and_changes(self):
        verdicts, _ = self.feed(HeatBalanceLearner(), 0.0, 3000, t1=14.0, t3=20.0)
        self.assertFalse(verdicts[0]["accepted"])
        self.assertIn("For lille forskel", verdicts[0]["reason"])
        verdicts, _ = self.feed(HeatBalanceLearner(), 0.0, 3000, rh=70.0)
        self.assertFalse(verdicts[0]["accepted"])
        self.assertIn("Kondens", verdicts[0]["reason"])
        learner = HeatBalanceLearner()
        _, now = self.feed(learner, 0.0, 2500)
        _, now = self.feed(learner, now, 600, pair=(55, 70))  # a new level starts the wait over
        self.assertEqual(learner.status["state"], "settling")
        self.feed(learner, now, 10, bypass=True)
        self.assertEqual(learner.status["reason"], "Bypass er åben")
        self.feed(learner, now, 10, t2=None)
        self.assertEqual(learner.status["state"], "off")

    def test_learner_learns_the_standby_draw(self):
        learner = HeatBalanceLearner()
        for second in range(0, 400, 2):
            learner.observe({"supply_rpm": 0, "extract_rpm": 0, "power_w": 1.3, "blocked": "Anlægget er slukket"}, second)
        self.assertAlmostEqual(learner.idle_power_w, 1.3, places=2)

    def test_summary_needs_two_nights_that_agree(self):
        night = 22 * 3600.0  # 22:00 on day 0 (UTC offsets move it within the same night)
        windows = [{"t": night + i * 900, "duct_ratio": 1.14 + (i % 3) * 0.01, "delta_t": 10.0} for i in range(10)]
        self.assertEqual(summarize(windows, night + 20000)["confidence"], "low")
        windows += [{"t": night + 86400 + i * 900, "duct_ratio": 1.15, "delta_t": 10.0} for i in range(4)]
        summary = summarize(windows, night + 86400 + 10000)
        self.assertEqual(summary["confidence"], "ok")
        self.assertAlmostEqual(summary["ratio"], 1.15, delta=0.011)
        noisy = [{"t": night + i * 43200, "duct_ratio": 1.0 + (i % 2) * 0.3, "delta_t": 10.0} for i in range(10)]
        self.assertNotEqual(summarize(noisy, night + 10 * 43200)["confidence"], "ok")

    def test_adopt_moves_in_steps_and_ignores_wobble(self):
        self.assertEqual(adopt(None, 1.14), 1.14)
        self.assertEqual(adopt(1.14, 1.15), 1.14)
        self.assertEqual(adopt(1.0, 1.3), 1.05)
        self.assertEqual(adopt(1.2, 2.0), 1.25)


class RuntimeBalanceTests(unittest.TestCase):
    def test_runtime_learns_the_duct_ratio_and_rebalances(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        gateway = {"bus_traffic": False}
        runtime = ControllerRuntime(gateway_state=gateway, hardware=HardwareAdapter(),
                                    state_path=Path(temp.name) / "controller.json")
        runtime.change_log_path = Path(temp.name) / "change-log.jsonl"
        runtime.configure({**HOUSE, "balance_enabled": True}, apply=False)
        equal = {level: values["supply"] for level, values in runtime.config.data["profiles"].items()}
        level = runtime.config.data["profiles"][3]
        curve = {"rpm_at_0": 557.0, "rpm_per_percent": 24.0}
        supply_rpm, extract_rpm = rpm_at_percent(level["supply"], curve), rpm_at_percent(level["extract"], curve)
        k = side_constants(runtime.config.data)
        # The real ducts: supply moves 15 % more air per rpm than extract.
        supply_m3h = float(k["supply"]) * supply_rpm
        extract_m3h = supply_m3h / 1.15 * extract_rpm / supply_rpm
        fans = fan_powers(supply_rpm, extract_rpm, None)
        t2, t4 = exchanger(7.0, 18.0, supply_m3h, extract_m3h,
                           supply_fan_w=float(fans["supply"]), extract_fan_w=float(fans["extract"]))
        gateway.update(outdoor_temp=7.0, extract_temp=18.0, exhaust_temp=t4, humidity=40.0,
                       fan_supply_percent=level["supply"], fan_extract_percent=level["extract"],
                       fan_supply_rpm=supply_rpm, fan_extract_rpm=extract_rpm, bypass_active=False)
        runtime.onewire.by_role = lambda role: t2 if role == "t2" else None
        runtime.refresh_measurements()
        start = 1_790_460_000.0  # 23:00 local time
        for night in range(2):
            now = start + night * 86400
            for step in range(0, 4 * 3600, 5):
                runtime._observe_balance(now + step)
        learned = runtime.config.data["balance_learned"]
        self.assertEqual(learned["confidence"], "ok")
        self.assertAlmostEqual(learned["ratio"], 1.15, delta=0.03)
        self.assertIsNotNone(learned["ratio_in_use"])
        self.assertEqual(runtime.config.balance_status()["duct_ratio_source"], "learned")
        self.assertLess(runtime.config.data["profiles"][3]["supply"], equal[3])
        self.assertTrue(any(event["source"] == "luftbalance" for event in runtime.change_log))
        snapshot = runtime.snapshot()
        self.assertIn(snapshot["balance_live"]["state"], ("settling", "measuring", "measured"))
        self.assertIsNotNone(snapshot["balance_running_excess_percent"])
        self.assertNotIn("windows", snapshot["balance_learned"])


class OverpressureAlarmTests(unittest.TestCase):
    def test_overpressure_is_reported_after_an_hour(self):
        diagnostics = Diagnostics(None)
        feed = {"balance_running_excess_percent": -6.0, "rs485_healthy": True}
        diagnostics.update(feed, 0.0)
        self.assertEqual(diagnostics.update(feed, 1800.0)["diagnostics_alarm_count"], 0)
        result = diagnostics.update(feed, 3700.0)
        self.assertIn("balance_overpressure", [alarm["code"] for alarm in result["diagnostics_alarms"]])
        cleared = diagnostics.update({**feed, "fireplace": True}, 3800.0)
        self.assertEqual(cleared["diagnostics_alarm_count"], 0)


if __name__ == "__main__":
    unittest.main()
