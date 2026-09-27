import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway"))
from controller_core import BONFIRE_PROFILE, ControllerEngine, ControllerError, ControllerState, HardwareAdapter  # noqa: E402


def _engine(tmp_path, **config):
    state = ControllerState(tmp_path / "controller.json")
    state.configure({"mode": "manual", "manual_level": 4, **config})
    return state, ControllerEngine(state, HardwareAdapter())


def test_bonfire_runs_both_fans_at_minimum_for_the_chosen_time(tmp_path):
    state, engine = _engine(tmp_path, bypass="on")
    state.configure({"bonfire_minutes": 90})
    resolved = engine.resolve()
    assert resolved["bonfire_active"] is True
    assert resolved["effective_source"] == "bonfire"
    assert resolved["effective_profile"]["extract"] == BONFIRE_PROFILE["extract"]
    assert resolved["effective_profile"]["supply"] == BONFIRE_PROFILE["supply"]
    assert resolved["effective_bypass"] == "off"
    assert 89 * 60 <= resolved["bonfire_remaining_seconds"] <= 90 * 60


def test_bonfire_stops_by_itself(tmp_path):
    state, engine = _engine(tmp_path)
    state.configure({"bonfire_minutes": 30})
    state.data["bonfire_until"] = time.time() - 1
    resolved = engine.resolve()
    assert resolved["bonfire_active"] is False
    assert resolved["effective_level"] == 4
    assert resolved["effective_profile"]["extract"] > BONFIRE_PROFILE["extract"]


def test_bonfire_can_be_stopped_and_limits_are_checked(tmp_path):
    state, engine = _engine(tmp_path)
    state.configure({"bonfire_minutes": 60})
    state.configure({"bonfire_minutes": 0})
    assert engine.resolve()["bonfire_active"] is False
    with pytest.raises(ControllerError):
        state.configure({"bonfire_minutes": 5})
    with pytest.raises(ControllerError):
        state.configure({"bonfire_minutes": 600})


def test_fireplace_has_priority_and_boost_cancels_bonfire(tmp_path):
    state, engine = _engine(tmp_path)
    state.configure({"fireplace_minutes": 15})
    with pytest.raises(ControllerError):
        state.configure({"bonfire_minutes": 60})
    state.configure({"fireplace_minutes": 0})
    state.configure({"bonfire_minutes": 60})
    state.configure({"quick_boost_minutes": 15})
    assert engine.resolve()["bonfire_active"] is False
    state.configure({"bonfire_minutes": 60})
    assert state.data["quick_boost_until"] is None
