#!/usr/bin/env python3
"""Runtime bridge between the live PassiveLink gateway and ControllerEngine.

The controller always computes desired state, but hardware writes are permitted
only when automatic master arbitration has established Raspberry Pi as master.
HCP4 always wins if foreign FC06/FC16 traffic is detected.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from controller_core import ControllerEngine, ControllerError, ControllerState, HardwareAdapter
from master_arbitration import MasterArbitrator, RtuFrameStream

LOG = logging.getLogger("passivelink-controller")


class ControllerRuntime:
    def __init__(
        self,
        *,
        gateway_state: dict[str, object],
        hardware: HardwareAdapter,
        state_path: str | Path | None = None,
        tick_seconds: float = 2.0,
        master_config: dict | None = None,
    ) -> None:
        self.gateway_state = gateway_state
        self.config = ControllerState(state_path)
        self.engine = ControllerEngine(self.config, hardware)
        self.tick_seconds = max(1.0, float(tick_seconds))
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.apply_lock = threading.Lock()
        self.last_tick_at: float | None = None
        self.master = MasterArbitrator()
        self.master.configure(master_config)
        self.master_stream = RtuFrameStream()
        self._last_master = self.master.master

    @staticmethod
    def _first(state: dict[str, object], *keys: str):
        for key in keys:
            value = state.get(key)
            if value is not None:
                return value
        return None

    def configure_master(self, config: dict | None) -> None:
        self.master.configure(config)

    def observe_serial_bytes(self, data: bytes) -> None:
        """Feed every RX chunk into the fail-safe HCP4 detector immediately."""
        if not data:
            return
        previous = self.master.master
        for frame in self.master_stream.feed(data):
            self.master.observe_frame(frame)
        if self.master.master != previous:
            self._on_master_transition(previous, self.master.master)

    def note_own_frame(self, frame: bytes) -> None:
        """Register a Pi FC06/FC16 TX so its response is not mistaken for HCP4."""
        self.master.note_own_frame(frame)

    def _bus_healthy(self) -> bool:
        if self.gateway_state.get("bus_traffic") is True:
            return True
        age = self.master.bus_age()
        return age is not None and age <= 10.0

    def _on_master_transition(self, old: str, new: str) -> None:
        self._last_master = new
        # When Pi regains the bus, force every desired output through the
        # verified writer once. HCP4 may have changed values while it was master.
        if new == MasterArbitrator.PI:
            self.engine.last_applied.clear()
            self.engine._failure_values.clear()
            self.engine._failure_counts.clear()
            self.engine._retry_at.clear()
            LOG.warning("Raspberry Pi became active master; desired state will be reapplied")
        elif old == MasterArbitrator.PI:
            # Any queued/next write is blocked again by hardware_writes_allowed
            # and by the controller-aware gateway's CONTROL write guard.
            self.engine._retry_at.clear()
            LOG.warning("Raspberry Pi released mastership to %s; controller writes paused", new)

    def _evaluate_master(self) -> None:
        before = self.master.master
        self.master.evaluate(
            controller_enabled=bool(self.config.data.get("enabled")),
            bus_healthy=self._bus_healthy(),
        )
        if self.master.master != before:
            self._on_master_transition(before, self.master.master)

    def hardware_writes_allowed(self) -> bool:
        self._evaluate_master()
        return self.master.writes_allowed(bool(self.config.data.get("enabled")))

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
        self._evaluate_master()
        result = self.engine.resolve()
        result.update(self.master.snapshot())
        writes_allowed = self.master.writes_allowed(bool(self.config.data.get("enabled")))
        if not self.config.data.get("enabled"):
            control_state = "disabled"
        elif self.master.master == MasterArbitrator.HCP4:
            control_state = "paused_hcp4_master"
        elif self.master.master == MasterArbitrator.PI:
            control_state = "active_pi_master"
        else:
            control_state = "waiting_for_safe_master"
        result.update({
            "hardware_writes_allowed": writes_allowed,
            "hardware_control_state": control_state,
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
            "rs485_healthy": self._bus_healthy(),
            "last_tick_at": self.last_tick_at,
        })
        return result

    def configure(self, patch: dict[str, object], *, apply: bool = True) -> dict[str, object]:
        self.config.configure(patch)
        self._evaluate_master()
        if apply and self.hardware_writes_allowed():
            self.apply_once()
        return self.snapshot()

    def heartbeat(self, demand: str = "normal") -> dict[str, object]:
        self.config.heartbeat(demand)
        self._evaluate_master()
        if self.config.data["mode"] == "smart_auto" and self.hardware_writes_allowed():
            self.apply_once()
        return self.snapshot()

    def apply_once(self) -> dict[str, object]:
        """Apply changed desired state once, only while Pi is confirmed master."""
        with self.apply_lock:
            self.refresh_measurements()
            self._evaluate_master()
            if not self.master.writes_allowed(bool(self.config.data.get("enabled"))):
                self.engine.resolve()
                self.last_tick_at = time.time()
                return self.snapshot()
            state = self.engine.apply()
            self.last_tick_at = time.time()
            return state

    def tick(self) -> None:
        self.refresh_measurements()
        self._evaluate_master()
        if not self.master.writes_allowed(bool(self.config.data.get("enabled"))):
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
        LOG.info(
            "Local HCH controller runtime started (enabled=%s, master=%s)",
            self.config.data["enabled"], self.master.master,
        )
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
