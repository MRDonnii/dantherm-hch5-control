import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway"))
from controller_core import ControllerEngine, ControllerState, HardwareAdapter  # noqa: E402
from controller_runtime import ControllerRuntime  # noqa: E402


def _runtime(tmp_path, **config):
    state = ControllerState(tmp_path / "controller.json")
    state.configure({"mode": "smart_auto", "local_normal_level": 2, "bathroom_rh_setpoint": 65,
                     "bathroom_rh_hysteresis": 5, "bathroom_max_level": 4, **config})
    runtime = ControllerRuntime(gateway_state={"bus_traffic": False}, hardware=HardwareAdapter(),
                                state_path=tmp_path / "runtime.json")
    runtime.config = state
    runtime.engine = ControllerEngine(state, HardwareAdapter())
    runtime._room_air_dries = lambda values: True
    return runtime


def _level(runtime, humidity, now):
    import controller_runtime
    real = controller_runtime.time.time
    controller_runtime.time.time = lambda: now
    try:
        runtime.room_inputs({"source": "home_assistant", "valid_for_s": 180, "rooms": {
            "Badeværelse": {"humidity": humidity, "priority": "auto", "control": True, "enabled": True, "room_type": "bathroom"}}})
        return runtime._derive_smart_decision(now)[0]
    finally:
        controller_runtime.time.time = real


def test_starts_at_top_and_steps_down_as_rh_falls(tmp_path):
    runtime = _runtime(tmp_path)
    t = 1_000_000.0
    assert _level(runtime, 70, t) == 4          # over the limit: straight to step 4
    assert _level(runtime, 80, t + 60) == 4     # still rising: stays at the top
    assert _level(runtime, 70, t + 600) == 3    # halfway down from the 80 % peak
    assert _level(runtime, 62, t + 900) == 3    # nearly dry: one step above normal
    assert _level(runtime, 59, t + 1200) == 2   # below 60 % (65 - 5): episode over
    assert runtime._bathroom_episodes == {}


def test_shower_rise_starts_drying_before_the_limit(tmp_path):
    runtime = _runtime(tmp_path)
    t = 2_000_000.0
    assert _level(runtime, 55, t) == 2
    assert _level(runtime, 63, t + 300) == 4    # +8 %-points in 5 minutes
    assert _level(runtime, 57, t + 1500) == 2   # back near where the rise started


def test_drying_level_follows_the_setting(tmp_path):
    runtime = _runtime(tmp_path, bathroom_max_level=3)
    assert _level(runtime, 75, 3_000_000.0) == 3


def test_drying_is_allowed_at_night(tmp_path):
    runtime = _runtime(tmp_path, night_enabled=True, night_start="00:00", night_end="23:59",
                       night_level=1, night_air_quality_max_level=3)
    import time
    now = time.time()
    assert _level(runtime, 75, now) == 4
    resolved = runtime.engine.resolve()
    assert resolved["effective_level"] == 4
    assert resolved["night_active"] is True


def test_other_rooms_stay_capped_at_night(tmp_path):
    runtime = _runtime(tmp_path, night_enabled=True, night_start="00:00", night_end="23:59",
                       night_level=1, night_air_quality_max_level=3)
    runtime.config.heartbeat("boost", requested_level=4, reason="CO2 Soveværelse")
    assert runtime.engine.resolve()["effective_level"] <= 3
