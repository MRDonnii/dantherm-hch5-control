import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway"))
from controller_core import ControllerEngine, ControllerError, ControllerState, HardwareAdapter  # noqa: E402


class Recorder:
    def __init__(self):
        self.calls = []

    def adapter(self):
        return HardwareAdapter(
            write_fan_pair=lambda e, s: self.calls.append(("fan_pair", (e, s))),
            set_bypass=lambda v: self.calls.append(("bypass", v)),
            set_fireplace=lambda v: self.calls.append(("fireplace", v)),
            set_afterheat_setpoint=lambda v: None,
            set_standby=lambda v: self.calls.append(("standby", v)),
        )


def _engine(tmp_path):
    state = ControllerState(tmp_path / "controller.json")
    state.configure({"mode": "manual", "manual_level": 3})
    recorder = Recorder()
    return state, ControllerEngine(state, recorder.adapter()), recorder


def test_standby_switches_the_unit_off_and_back_on(tmp_path):
    state, engine, hw = _engine(tmp_path)
    engine.apply()
    assert ("fan_pair", (64, 64)) in hw.calls
    hw.calls.clear()
    state.configure({"standby_minutes": -1})
    result = engine.apply()
    assert result["standby_active"] is True and result["effective_source"] == "standby"
    assert ("standby", True) in hw.calls
    assert not [c for c in hw.calls if c[0] == "fan_pair"]
    assert result["standby_remaining_seconds"] is None
    hw.calls.clear()
    state.configure({"standby_minutes": 0})
    engine.apply()
    assert hw.calls.index(("standby", False)) < hw.calls.index(("fan_pair", (64, 64)))


def test_timed_standby_ends_by_itself(tmp_path):
    state, engine, hw = _engine(tmp_path)
    state.configure({"standby_minutes": 60})
    assert engine.apply()["standby_active"] is True
    state.data["standby_until"] = time.time() - 1
    assert engine.apply()["standby_active"] is False
    assert ("standby", False) in hw.calls


def test_standby_blocks_boost_bonfire_and_fireplace(tmp_path):
    state, engine, hw = _engine(tmp_path)
    state.configure({"quick_boost_minutes": 15})
    state.configure({"standby_minutes": 240})
    assert state.data["quick_boost_until"] is None
    for patch in ({"quick_boost_minutes": 15}, {"bonfire_minutes": 60}, {"fireplace_minutes": 15}):
        with pytest.raises(ControllerError):
            state.configure(patch)
    with pytest.raises(ControllerError):
        state.configure({"standby_minutes": 5})


def test_bonfire_switches_the_unit_off_too(tmp_path):
    state, engine, hw = _engine(tmp_path)
    engine.apply()
    hw.calls.clear()
    state.configure({"bonfire_minutes": 60})
    result = engine.apply()
    assert result["bonfire_active"] is True and result["effective_source"] == "bonfire"
    assert ("standby", True) in hw.calls
    assert not [c for c in hw.calls if c[0] == "fan_pair"]
    hw.calls.clear()
    state.configure({"bonfire_minutes": 0})
    engine.apply()
    assert hw.calls.index(("standby", False)) < hw.calls.index(("fan_pair", (64, 64)))


def test_until_tomorrow_morning_is_the_next_seven_oclock():
    from datetime import datetime
    from controller_core import _next_morning
    evening = datetime(2026, 9, 27, 22, 30).astimezone().timestamp()
    night = datetime(2026, 9, 28, 1, 15).astimezone().timestamp()
    assert datetime.fromtimestamp(_next_morning(evening, 7)).strftime("%d %H:%M") == "28 07:00"
    assert datetime.fromtimestamp(_next_morning(night, 7)).strftime("%d %H:%M") == "28 07:00"


def test_until_tomorrow_standby_sets_an_end_time(tmp_path):
    state, engine, hw = _engine(tmp_path)
    state.configure({"standby_minutes": -2})
    result = engine.apply()
    assert result["standby_active"] is True
    assert 0 < result["standby_remaining_seconds"] <= 24 * 3600
