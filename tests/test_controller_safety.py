import threading

from controller_safety import ControllerSafetyGuard, install_controller_safety


class FakeMaster:
    def __init__(self, age=1.0):
        self.age = age

    def bus_age(self):
        return self.age


class FakeEngine:
    def __init__(self):
        self.lock = threading.RLock()
        self.measurements = {"rh": 55.0, "co2": 900.0, "outdoor": 10.0, "room": 23.0}
        self.cooling_reason = "active"

    def _stop_cooling(self, _now, reason):
        self.cooling_reason = reason


class FakeRuntime:
    def __init__(self):
        self.gateway_state = {"bus_traffic": True, "bus_last_frame_age": 1.0}
        self.master = FakeMaster()
        self.engine = FakeEngine()
        self.refresh_calls = 0

    def _bus_healthy(self):
        return True

    def refresh_measurements(self):
        self.refresh_calls += 1

    def snapshot(self):
        return {"effective_level": 3}


def test_guard_keeps_fresh_measurements():
    runtime = FakeRuntime()
    guard = ControllerSafetyGuard(runtime)
    guard.refresh(runtime.refresh_measurements)
    assert runtime.refresh_calls == 1
    assert guard.last_state == "fresh"
    assert runtime.engine.measurements["room"] == 23.0
    assert runtime.engine.cooling_reason == "active"


def test_guard_clears_measurements_and_stops_cooling_when_stale():
    runtime = FakeRuntime()
    runtime.gateway_state["bus_last_frame_age"] = 14.0
    guard = ControllerSafetyGuard(runtime)
    guard.refresh(runtime.refresh_measurements)
    assert guard.last_state == "stale"
    assert all(value is None for value in runtime.engine.measurements.values())
    assert runtime.engine.cooling_reason == "sensor_stale"


def test_install_makes_bus_health_age_aware_and_exposes_status():
    runtime = FakeRuntime()
    guard = install_controller_safety(runtime)
    assert runtime._bus_healthy() is True
    runtime.gateway_state["bus_last_frame_age"] = 20.0
    assert runtime._bus_healthy() is False
    runtime.refresh_measurements()
    snapshot = runtime.snapshot()
    assert snapshot["local_sensor_failsafe"] == "stale"
    assert snapshot["local_sensor_bus_age_seconds"] == 20.0
    assert guard is runtime._hch_safety_guard
