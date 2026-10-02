import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

import fan_steps  # noqa: E402
from controller_core import ControllerEngine, ControllerError, ControllerState  # noqa: E402

# A six-step controller file as written by 1.3.x: balance on, running manual step 4.
SIX_STEP_FILE = {
    "mode": "manual", "manual_level": 4, "local_normal_level": 4, "local_min_level": 1, "local_max_level": 6,
    "night_level": 2, "night_air_quality_max_level": 4, "bathroom_max_level": 6, "vacation_level": 1,
    "quick_boost_level": 6, "cooling_level": 4, "dry_max_level": 2, "pm25_max_level": 5,
    "balance_enabled": True, "balance_ratio_mode": "fixed", "balance_duct_ratio": 1.14,
    "fan_curve": {"rpm_at_0": 560.7, "rpm_per_percent": 23.9, "samples": 5},
    "airflow_measured": {"3": {"supply": 150, "supply_percent": 42}},
    "schedule_periods": {str(day): [{"start": "07:00", "end": "22:00", "level": 3, "mode": "min", "label": ""}]
                         for day in range(7)},
    "profiles": {
        "1": {"extract": 25, "supply": 17, "name": "Lav"}, "2": {"extract": 40, "supply": 30, "name": "Lav+"},
        "3": {"extract": 55, "supply": 42, "name": "Normal"}, "4": {"extract": 70, "supply": 55, "name": "Høj"},
        "5": {"extract": 85, "supply": 67, "name": "Høj+"}, "6": {"extract": 100, "supply": 80, "name": "Boost"},
    },
}


class FanStepTests(unittest.TestCase):
    def state(self, saved=None):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "controller.json"
        if saved is not None:
            path.write_text(json.dumps(saved))
        return ControllerState(path)

    def pairs(self, state):
        return {level: (p["extract"], p["supply"]) for level, p in state.data["profiles"].items()}

    def test_upgrade_keeps_the_running_pair_as_step_3(self):
        state = self.state(SIX_STEP_FILE)
        self.assertEqual(state.data["fan_step_count"], 4)
        self.assertEqual(state.data["fan_settings"],
                         {"supply": 55, "extract": 70, "offset": 25, "max_supply": 100, "max_extract": 100})
        # Balance on: extract 20/45/70/100 as on the HCP4, supply balanced (same 55 at step 3).
        self.assertEqual(self.pairs(state), {1: (20, 13), 2: (45, 34), 3: (70, 55), 4: (100, 80)})
        # Old step 4 was an ordinary step: the unit keeps running exactly as before.
        self.assertEqual((state.data["mode"], state.data["manual_level"]), ("manual", 3))
        moved = {key: state.data[key] for key in ("local_normal_level", "night_level", "night_air_quality_max_level",
                                                   "bathroom_max_level", "vacation_level", "quick_boost_level",
                                                   "cooling_level", "dry_max_level", "pm25_max_level", "local_max_level")}
        self.assertEqual(moved, {"local_normal_level": 3, "night_level": 2, "night_air_quality_max_level": 3,
                                 "bathroom_max_level": 4, "vacation_level": 1, "quick_boost_level": 4,
                                 "cooling_level": 3, "dry_max_level": 2, "pm25_max_level": 3, "local_max_level": 4})
        # Old step 3 (55/42) is nearest to new step 2 (45/34).
        self.assertEqual(state.data["schedule_periods"]["0"][0]["level"], 2)
        self.assertEqual(state.data["airflow_measured"], {})
        self.assertEqual(state.data["airflow_measured_6"], SIX_STEP_FILE["airflow_measured"])
        self.assertTrue(state.path.with_name("controller.json.six-steps.bak").exists())
        # The upgrade is written once; loading again changes nothing.
        again = ControllerState(state.path)
        self.assertEqual(self.pairs(again), self.pairs(state))
        self.assertEqual(again.data["manual_level"], 3)

    def test_six_steps_can_be_chosen_again_exactly_as_before(self):
        state = self.state(SIX_STEP_FILE)
        state.configure({"fan_step_count": 6})
        self.assertEqual(self.pairs(state), {1: (25, 17), 2: (40, 30), 3: (55, 42), 4: (70, 55), 5: (85, 67), 6: (100, 80)})
        self.assertEqual(state.data["manual_level"], 4)
        self.assertEqual(state.data["bathroom_max_level"], 6)
        self.assertEqual(state.data["local_max_level"], 6)
        self.assertEqual(state.data["airflow_measured"], SIX_STEP_FILE["airflow_measured"])
        self.assertIsNone(state.data["max_level_until"])
        snapshot = state.snapshot()
        self.assertEqual((snapshot["max_level"], snapshot["fan_levels"]), (6, [1, 2, 3, 4, 5, 6]))
        # Six steps are edited per step as before; four-step settings are kept.
        state.configure({"profiles": {"5": {"extract": 88}}})
        self.assertEqual(state.data["profiles"][5]["extract"], 88)
        self.assertEqual(state.data["fan_settings"]["extract"], 70)
        state.configure({"fan_step_count": 4})
        self.assertEqual(self.pairs(state)[3], (70, 55))
        self.assertEqual(state.data["manual_level"], 3)
        self.assertEqual(state.data["six_step_profiles"][5]["extract"], 88)

    def test_manual_step_4_runs_four_hours_only_with_dantherm_steps(self):
        state = self.state()
        engine = ControllerEngine(state)
        state.configure({"mode": "manual", "manual_level": 4})
        result = engine.resolve()
        self.assertIn("tilbage til trin 3", result["effective_reason"])
        self.assertGreater(state.snapshot()["max_level_remaining_seconds"], 4 * 3600 - 10)
        state.configure({"fan_step_count": 6, "manual_level": 4})
        self.assertIsNone(state.data["max_level_until"])
        self.assertEqual(engine.resolve(now=time.time() + 5 * 3600)["effective_level"], 4)

    def test_vacation_may_go_below_the_auto_minimum(self):
        state = self.state()
        engine = ControllerEngine(state)
        state.configure({"mode": "smart_auto", "local_min_level": 2, "vacation_level": 1})
        state.heartbeat("low", requested_level=1, reason="CO2 lav")
        self.assertEqual(engine.resolve()["effective_level"], 2)
        state.configure({"vacation_enabled": True})
        result = engine.resolve()
        self.assertEqual((result["effective_level"], result["effective_source"]), (1, "vacation"))
        state.configure({"vacation_enabled": False})
        self.assertEqual(engine.resolve()["effective_level"], 2)

    def test_manual_steps_ignore_the_auto_limits(self):
        state = self.state()
        engine = ControllerEngine(state)
        state.configure({"local_min_level": 2, "local_max_level": 3, "mode": "manual", "manual_level": 1})
        self.assertEqual(engine.resolve()["effective_level"], 1)
        state.configure({"manual_level": 4})
        self.assertEqual(engine.resolve()["effective_level"], 4)
        # Automatic control still keeps within the Auto limits.
        state.configure({"mode": "local_auto"})
        self.assertLessEqual(engine.resolve()["effective_level"], 3)

    def test_step_choice_is_validated(self):
        state = self.state()
        for bad in (5, "x", None):
            with self.subTest(bad=bad), self.assertRaises(ControllerError):
                state.configure({"fan_step_count": bad})
        with self.assertRaises(ControllerError):
            state.configure({"manual_level": 5})

    def test_ladder_matches_the_service_manual(self):
        # Factory offset 25: step 3 at gear 46 gives step 1 at the lowest gear.
        steps = fan_steps.ladder({"supply": 46, "extract": 91, "offset": 25, "max_supply": 90, "max_extract": 100})
        self.assertEqual({level: (p["supply"], p["extract"]) for level, p in steps.items()},
                         {1: (1, 41), 2: (21, 66), 3: (46, 91), 4: (90, 100)})


if __name__ == "__main__":
    unittest.main()
