#!/usr/bin/env python3
"""Fail-safe measurement freshness guard for HCH5 Control.

The base gateway keeps the last decoded values in memory, which is useful for
telemetry but dangerous for automation if the RS485 stream goes stale. This
wrapper clears control measurements whenever the local bus has not produced a
fresh frame, so Local Auto/free-cooling cannot make new decisions from old
sensor values. It does not add any Modbus write path.
"""
from __future__ import annotations

import time
from typing import Any


STALE_AFTER_SECONDS = 10.0


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class ControllerSafetyGuard:
    def __init__(self, runtime, *, stale_after: float = STALE_AFTER_SECONDS) -> None:
        self.runtime = runtime
        self.stale_after = max(2.0, float(stale_after))
        self.last_state = "unknown"
        self.last_transition_at = time.time()
        self.last_bus_age: float | None = None

    def _bus_age(self) -> float | None:
        gateway = self.runtime.gateway_state
        age = _number(gateway.get("bus_last_frame_age"))
        if age is not None:
            return max(0.0, age)
        master_age = self.runtime.master.bus_age()
        return max(0.0, float(master_age)) if master_age is not None else None

    def fresh(self) -> bool:
        age = self._bus_age()
        self.last_bus_age = age
        traffic = self.runtime.gateway_state.get("bus_traffic") is True
        return bool(traffic and age is not None and age <= self.stale_after)

    def refresh(self, original_refresh) -> None:
        original_refresh()
        now = time.time()
        state = "fresh" if self.fresh() else "stale"
        if state != self.last_state:
            self.last_state = state
            self.last_transition_at = now

        if state == "fresh":
            return

        engine = self.runtime.engine
        with engine.lock:
            for key in ("rh", "co2", "outdoor", "room"):
                engine.measurements[key] = None
            # Free cooling must never remain active from old temperature data.
            engine._stop_cooling(now, "sensor_stale")

    def augment(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        snapshot["local_sensor_failsafe"] = self.last_state
        snapshot["local_sensor_bus_age_seconds"] = (
            round(self.last_bus_age, 1) if self.last_bus_age is not None else None
        )
        snapshot["local_sensor_stale_after_seconds"] = self.stale_after
        snapshot["local_sensor_failsafe_since"] = self.last_transition_at
        return snapshot


def install_controller_safety(runtime, *, stale_after: float = STALE_AFTER_SECONDS) -> ControllerSafetyGuard:
    existing = getattr(runtime, "_hch_safety_guard", None)
    if existing is not None:
        return existing

    guard = ControllerSafetyGuard(runtime, stale_after=stale_after)
    original_refresh = runtime.refresh_measurements
    original_snapshot = runtime.snapshot

    def refresh_with_guard():
        guard.refresh(original_refresh)

    def snapshot_with_guard():
        return guard.augment(original_snapshot())

    runtime.refresh_measurements = refresh_with_guard
    runtime.snapshot = snapshot_with_guard
    runtime._hch_safety_guard = guard
    return guard


__all__ = ["ControllerSafetyGuard", "install_controller_safety", "STALE_AFTER_SECONDS"]
