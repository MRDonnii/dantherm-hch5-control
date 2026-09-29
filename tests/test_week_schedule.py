import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

import week_schedule
from controller_core import ControllerEngine, ControllerError, ControllerState, HardwareAdapter

# 2026-09-28 is a Monday.


def at(day, hour, minute=0):
    return (datetime(2026, 9, 28, hour, minute) + timedelta(days=day)).astimezone()


WORKDAY = {"0": [
    {"start": "08:00", "end": "16:00", "level": 1, "mode": "set", "label": "Ude"},
    {"start": "17:00", "end": "19:00", "level": 4, "mode": "min", "label": "Madlavning"},
], "4": [{"start": "22:00", "end": "02:00", "level": 5, "mode": "set", "label": "Fest"}]}


class WeekScheduleTests(unittest.TestCase):
    def test_normalize_sorts_and_rejects_bad_periods(self):
        periods = week_schedule.normalize({"0": list(reversed(WORKDAY["0"]))})
        self.assertEqual([p["start"] for p in periods["0"]], ["08:00", "17:00"])
        self.assertEqual(periods["6"], [])
        for bad in ({"7": []}, {"0": [{"start": "25:00", "end": "26:00", "level": 2}]},
                    {"0": [{"start": "08:00", "end": "08:00", "level": 2}]},
                    {"0": [{"start": "08:00", "end": "09:00", "level": 9}]}):
            with self.assertRaises(week_schedule.ScheduleError):
                week_schedule.normalize(bad)

    def test_active_period_and_midnight_wrap(self):
        periods = week_schedule.normalize(WORKDAY)
        self.assertEqual(week_schedule.effect(periods, at(0, 9))["set_level"], 1)
        self.assertEqual(week_schedule.effect(periods, at(0, 18))["min_level"], 4)
        self.assertIsNone(week_schedule.effect(periods, at(0, 16, 30)))
        self.assertEqual(week_schedule.effect(periods, at(5, 1))["period"]["label"], "Fest")  # Saturday 01:00
        self.assertIsNone(week_schedule.effect(periods, at(5, 2)))

    def test_next_change(self):
        periods = week_schedule.normalize(WORKDAY)
        change = week_schedule.next_change(periods, at(0, 9))
        self.assertEqual(datetime.fromtimestamp(change["at"]).hour, 16)
        self.assertIsNone(change["level"])
        change = week_schedule.next_change(periods, at(0, 16, 30))
        self.assertEqual((datetime.fromtimestamp(change["at"]).hour, change["level"]), (17, 4))

    def test_legacy_window_becomes_min_period(self):
        legacy = {str(d): {"enabled": d == 2, "start": "07:00", "end": "22:00", "level": 3} for d in range(7)}
        periods = week_schedule.from_legacy(legacy)
        self.assertEqual(periods["2"], [{"start": "07:00", "end": "22:00", "level": 3, "mode": "min", "label": ""}])
        self.assertEqual(periods["0"], [])


class EngineScheduleTests(unittest.TestCase):
    def make_engine(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return ControllerEngine(ControllerState(Path(temp.name) / "controller.json"), HardwareAdapter())

    def all_day(self, level, mode):
        return {str(d): [{"start": "00:00", "end": "23:59", "level": level, "mode": mode}] for d in range(7)}

    def test_set_period_lowers_base_level_but_air_quality_still_lifts(self):
        engine = self.make_engine()
        engine.config.configure({"schedule_enabled": True, "schedule_periods": self.all_day(1, "set"), "local_normal_level": 3})
        engine.update_measurements(rh=40, co2=600)
        result = engine.resolve(now=time.time())
        self.assertTrue(result["schedule_active"])
        self.assertEqual(result["effective_level"], 1)
        engine.update_measurements(rh=40, co2=1400)
        self.assertGreater(engine.resolve(now=time.time())["effective_level"], 1)

    def test_min_period_raises(self):
        engine = self.make_engine()
        engine.config.configure({"schedule_enabled": True, "schedule_periods": self.all_day(5, "min")})
        engine.update_measurements(rh=40, co2=600)
        self.assertEqual(engine.resolve(now=time.time())["effective_level"], 5)

    def test_snapshot_exposes_now_and_invalid_periods_are_rejected(self):
        engine = self.make_engine()
        engine.config.configure({"schedule_enabled": True, "schedule_periods": self.all_day(2, "set")})
        snapshot = engine.config.snapshot()
        self.assertEqual(snapshot["schedule_source"], "periods")
        self.assertEqual(snapshot["schedule_now"]["level"], 2)
        with self.assertRaises(ControllerError):
            engine.config.configure({"schedule_periods": {"0": [{"start": "x", "end": "09:00", "level": 2}]}})

    def test_planned_vacation_waits_for_its_start(self):
        engine = self.make_engine()
        start = time.time() + 3600
        engine.config.configure({"vacation_enabled": True, "vacation_level": 1,
                                 "vacation_from": str(start), "vacation_until": str(start + 86400)})
        engine.update_measurements(rh=40, co2=600)
        result = engine.resolve(now=time.time())
        self.assertFalse(result["vacation_active"])
        self.assertTrue(engine.config.snapshot()["vacation_pending"])
        self.assertTrue(engine.resolve(now=start + 60)["vacation_active"])
        with self.assertRaises(ControllerError):
            engine.config.configure({"vacation_from": str(start + 90000)})


if __name__ == "__main__":
    unittest.main()
