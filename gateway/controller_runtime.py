#!/usr/bin/env python3
"""Runtime bridge between the live PassiveLink gateway and ControllerEngine.

The deployer binds this module to the already verified physical write methods in
its monolithic Pi gateway. No register addresses are invented here.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from controller_core import ControllerEngine, ControllerError, ControllerState, HardwareAdapter

LOG = logging.getLogger("passivelink-controller")


class ControllerRuntime:
    def __init__(
        self,
        *,
        gateway_state: dict[str, object],
        hardware: HardwareAdapter,
        state_path: str | Path | None = None,
        tick_seconds: float = 2.0,
    ) -> None:
        self.gateway_state = gateway_state
        self.config = ControllerState(state_path)
        self.engine = ControllerEngine(self.config, hardware)
        self.tick_seconds = max(1.0, float(tick_seconds))
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.apply_lock = threading.Lock()
        self.last_tick_at: float | None = None

    @staticmethod
    def _first(state: dict[str, object], *keys: str):
        for key in keys:
            value = state.get(key)
            if value is not None:
                return value
        return None

    def refresh_measurements(self) -> None:
        """Feed only already decoded/local measurements to Local Auto."""
        state = self.gateway_state
        self.engine.update_measurements(
            rh=self._first(state, "humidity", "relative_humidity"),
            co2=self._first(state, "co2"),
            outdoor=self._first(state, "outdoor_temp", "outdoor_temperature"),
            room=self._first(state, "room_temp", "hrc2_t5_temperature", "room_temperature", "extract_temp"),
        )

    def snapshot(self) -> dict[str, object]:
        self.refresh_measurements()
        result = self.engine.resolve()
        result.update({
            "actual_fan_extract_percent": self._first(self.gateway_state, "fan_extract_percent", "extract_fan_percent"),
            "actual_fan_supply_percent": self._first(self.gateway_state, "fan_supply_percent", "supply_fan_percent"),
            "actual_fan_extract_rpm": self._first(self.gateway_state, "fan_extract_rpm", "extract_fan_rpm"),
            "actual_fan_supply_rpm": self._first(self.gateway_state, "fan_supply_rpm", "supply_fan_rpm"),
            "actual_bypass": self._first(self.gateway_state, "bypass_active"),
            "actual_fireplace": self._first(self.gateway_state, "fireplace"),
            "actual_afterheat": self._first(self.gateway_state, "afterheat_active"),
            "actual_afterheat_setpoint": self._first(self.gateway_state, "afterheat_setpoint"),
            "actual_supply_before_heater_temperature": self._first(
                self.gateway_state, "supply_temp"
            ),
            "actual_supply_air_temperature": self._first(
                self.gateway_state, "heating_coil_after_temperature", "supply_temp"
            ),
            "actual_supply_air_temperature_source": (
                "hac1_t2ah" if self.gateway_state.get("heating_coil_after_temperature") is not None
                else "unit_t2"
            ),
            "actual_afterheat_frost_temperature": self._first(
                self.gateway_state, "heating_coil_frost_temperature"
            ),
            "rs485_healthy": self.gateway_state.get("bus_traffic") is True,
            "last_tick_at": self.last_tick_at,
        })
        return result

    def configure(self, patch: dict[str, object], *, apply: bool = True) -> dict[str, object]:
        self.config.configure(patch)
        if apply and self.config.data["enabled"]:
            self.apply_once()
        return self.snapshot()

    def heartbeat(self, demand: str = "normal") -> dict[str, object]:
        self.config.heartbeat(demand)
        if self.config.data["enabled"] and self.config.data["mode"] == "smart_auto":
            self.apply_once()
        return self.snapshot()

    def apply_once(self) -> dict[str, object]:
        """Apply changed desired state once. Serialization prevents overlapping writes."""
        with self.apply_lock:
            self.refresh_measurements()
            state = self.engine.apply()
            self.last_tick_at = time.time()
            return state

    def tick(self) -> None:
        self.refresh_measurements()
        if not self.config.data["enabled"]:
            self.engine.resolve()
            self.last_tick_at = time.time()
            return
        try:
            self.apply_once()
        except Exception as error:
            # Engine records the detailed hardware error. Runtime stays alive and
            # retries only at the bounded tick interval; no tight write loop.
            LOG.error("Controller write failed: %s", error)
            self.last_tick_at = time.time()

    def _run(self) -> None:
        LOG.info("Local HCH controller runtime started (enabled=%s)", self.config.data["enabled"])
        while not self.stop_event.is_set():
            self.tick()
            self.stop_event.wait(self.tick_seconds)

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name="hch-controller", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=self.tick_seconds + 2)
            self.thread = None


__all__ = ["ControllerRuntime", "ControllerError", "HardwareAdapter"]
