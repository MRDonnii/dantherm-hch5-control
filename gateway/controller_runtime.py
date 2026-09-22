#!/usr/bin/env python3
"""Runtime bridge between the live PassiveLink gateway and ControllerEngine.

The Pi controller is always enabled. Hardware writes are permitted only when
master arbitration has established Raspberry Pi as master; HCP4 always wins.
Home Assistant may provide leased room measurements, but the control decision
and all persistent configuration remain on the Pi.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from controller_core import ControllerEngine, ControllerError, ControllerState, HardwareAdapter
from master_arbitration import MasterArbitrator, RtuFrameStream

LOG = logging.getLogger("passivelink-controller")
VALID_PRIORITIES = {"auto", "low", "normal", "high", "critical"}
PRIORITY_LEVEL_BIAS = {"auto": 0, "low": -1, "normal": 0, "high": 1, "critical": 2}


class ControllerRuntime:
    def __init__(self, *, gateway_state: dict[str, object], hardware: HardwareAdapter,
                 state_path: str | Path | None = None, tick_seconds: float = 2.0,
                 master_config: dict | None = None) -> None:
        self.gateway_state = gateway_state
        self.config = ControllerState(state_path)
        # Controller enable is no longer a user option. The Pi is always ready
        # to take over when HCP4 is absent and the bus is healthy.
        if not self.config.data.get("enabled"):
            self.config.data["enabled"] = True
            self.config.save()
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

        self.smart_rooms: dict[str, dict[str, object]] = {}
        self.smart_inputs_received_at: float | None = None
        self.smart_inputs_valid_for = 180
        self._room_rh_history: dict[str, deque[tuple[float, float]]] = defaultdict(deque)
        self.smart_demand = "normal"
        self.smart_reason = "No Home Assistant room data"
        self.smart_requested_level: int | None = None
        self.smart_target_level: int | None = None
        self.smart_controlling_room: str | None = None
        self.smart_controlling_metric: str | None = None
        self.smart_room_diagnostics: dict[str, dict[str, object]] = {}
        self._smart_last_level_change = 0.0
        self._smart_boost_until = 0.0

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
        if not data:
            return
        previous = self.master.master
        for frame in self.master_stream.feed(data):
            self.master.observe_frame(frame)
        if self.master.master != previous:
            self._on_master_transition(previous, self.master.master)

    def note_own_frame(self, frame: bytes) -> None:
        self.master.note_own_frame(frame)

    def _bus_healthy(self) -> bool:
        if self.gateway_state.get("bus_traffic") is True:
            return True
        age = self.master.bus_age()
        return age is not None and age <= 10.0

    def _on_master_transition(self, old: str, new: str) -> None:
        self._last_master = new
        if new == MasterArbitrator.PI:
            self.engine.last_applied.clear()
            self.engine._failure_values.clear()
            self.engine._failure_counts.clear()
            self.engine._retry_at.clear()
            LOG.warning("Raspberry Pi became active master; desired state will be reapplied")
        elif old == MasterArbitrator.PI:
            self.engine._retry_at.clear()
            LOG.warning("Raspberry Pi released mastership to %s; controller writes paused", new)

    def _evaluate_master(self) -> None:
        before = self.master.master
        self.master.evaluate(bus_healthy=self._bus_healthy())
        if self.master.master != before:
            self._on_master_transition(before, self.master.master)

    def hardware_writes_allowed(self) -> bool:
        self._evaluate_master()
        return self.master.writes_allowed()

    def refresh_measurements(self) -> None:
        state = self.gateway_state
        self.engine.update_measurements(
            rh=self._first(state, "humidity", "relative_humidity"),
            co2=self._first(state, "co2"),
            outdoor=self._first(state, "outdoor_temp", "outdoor_temperature"),
            room=self._first(state, "room_temp", "hrc2_t5_temperature", "room_temperature", "extract_temp"),
        )

    @staticmethod
    def _safe_number(value, low: float, high: float):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if low <= number <= high else None

    @staticmethod
    def _bool(value, default: bool = True) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        return str(value).strip().lower() not in {"0", "false", "off", "no"}

    def _rooms_with_unit_sensors(self) -> dict[str, dict[str, object]]:
        """Combine HA rooms with the unit's own local indoor sensors."""
        combined = {name: dict(values) for name, values in self.smart_rooms.items()}
        local: dict[str, object] = {
            "source": "unit",
            "control": True,
            "priority": "auto",
        }
        co2 = self._safe_number(self._first(self.gateway_state, "co2"), 250, 10000)
        rh = self._safe_number(
            self._first(self.gateway_state, "humidity", "relative_humidity"), 0, 100
        )
        temp = self._safe_number(
            self._first(
                self.gateway_state,
                "room_temp",
                "hrc2_t5_temperature",
                "room_temperature",
                "extract_temp",
            ),
            -30,
            60,
        )
        if co2 is not None:
            local["co2"] = round(co2, 0)
        if rh is not None:
            local["humidity"] = round(rh, 2)
        if temp is not None:
            local["temperature"] = round(temp, 2)
        if any(key in local for key in ("co2", "humidity", "temperature")):
            combined["HCH5 / spisestue"] = local
        return combined

    def room_inputs(self, payload: dict[str, object]) -> dict[str, object]:
        """Accept leased room measurements and metadata from Home Assistant."""
        rooms = payload.get("rooms")
        if not isinstance(rooms, dict):
            raise ControllerError("rooms skal være et objekt")
        try:
            valid_for = int(payload.get("valid_for_s", 180))
        except (TypeError, ValueError) as error:
            raise ControllerError("valid_for_s skal være et heltal") from error
        if not 30 <= valid_for <= 900:
            raise ControllerError("valid_for_s skal være 30..900 sekunder")

        now = time.time()
        sanitized: dict[str, dict[str, object]] = {}
        for raw_name, raw_values in list(rooms.items())[:32]:
            if not isinstance(raw_values, dict):
                continue
            name = str(raw_name).strip()[:64]
            if not name:
                continue
            priority = str(raw_values.get("priority", "auto")).strip().lower()
            if priority not in VALID_PRIORITIES:
                priority = "auto"
            values: dict[str, object] = {
                "source": "home_assistant",
                "control": self._bool(raw_values.get("control"), True),
                "priority": priority,
            }
            measurement_count = 0
            temp = self._safe_number(raw_values.get("temperature"), -30, 60)
            rh = self._safe_number(raw_values.get("humidity"), 0, 100)
            co2 = self._safe_number(raw_values.get("co2"), 250, 10000)
            if temp is not None:
                values["temperature"] = round(temp, 2)
                measurement_count += 1
            if rh is not None:
                values["humidity"] = round(rh, 2)
                measurement_count += 1
                history = self._room_rh_history[name]
                history.append((now, rh))
                while history and now - history[0][0] > 900:
                    history.popleft()
            if co2 is not None:
                values["co2"] = round(co2, 0)
                measurement_count += 1
            if measurement_count:
                sanitized[name] = values

        self.smart_rooms = sanitized
        self.smart_inputs_received_at = now
        self.smart_inputs_valid_for = valid_for
        self._recalculate_smart_demand(now, heartbeat=True)
        if self.config.data.get("mode") == "smart_auto" and self.hardware_writes_allowed():
            self.apply_once()
        return self.snapshot()

    def _metric_target(self, *, value: float, setpoint: float, step: float,
                       normal: int, minimum: int, maximum: int, priority: str) -> tuple[int, float]:
        delta = value - setpoint
        if delta <= 0:
            return normal, 0.0
        severity = delta / max(step, 0.1)
        target = normal + max(1, math.ceil(severity)) + PRIORITY_LEVEL_BIAS.get(priority, 0)
        # Even a low-priority room above threshold must increase at least one step.
        target = max(normal + 1, target)
        return min(maximum, max(minimum, target)), severity

    def _derive_smart_target(self, now: float) -> tuple[int, str, str | None, str | None, dict[str, dict[str, object]]]:
        d = self.config.data
        normal = int(d["local_normal_level"])
        minimum = int(d["local_min_level"])
        maximum = int(d["local_max_level"])
        rooms = self._rooms_with_unit_sensors()
        diagnostics: dict[str, dict[str, object]] = {}
        candidates: list[tuple[int, float, str, str, str]] = []

        for name, values in rooms.items():
            priority = str(values.get("priority", "auto"))
            if priority not in VALID_PRIORITIES:
                priority = "auto"
            control = self._bool(values.get("control"), True)
            room_target = normal
            room_score = 0.0
            room_metric: str | None = None
            room_reason = "Below thresholds"

            co2 = values.get("co2")
            if control and isinstance(co2, (int, float)):
                target, severity = self._metric_target(
                    value=float(co2),
                    setpoint=float(d["co2_setpoint"]),
                    step=float(d["auto_step_co2"]),
                    normal=normal,
                    minimum=minimum,
                    maximum=maximum,
                    priority=priority,
                )
                if target > room_target or (target == room_target and severity > room_score):
                    room_target = target
                    room_score = severity
                    room_metric = "co2"
                    room_reason = f"CO2 {name} {float(co2):.0f} ppm"

            rh = values.get("humidity")
            if control and isinstance(rh, (int, float)):
                target, severity = self._metric_target(
                    value=float(rh),
                    setpoint=float(d["rh_setpoint"]),
                    step=float(d["auto_step_rh"]),
                    normal=normal,
                    minimum=minimum,
                    maximum=maximum,
                    priority=priority,
                )
                if target > room_target or (target == room_target and severity > room_score):
                    room_target = target
                    room_score = severity
                    room_metric = "humidity"
                    room_reason = f"RH {name} {float(rh):.1f}%"

                history = self._room_rh_history.get(name)
                if history:
                    fresh = [(ts, value) for ts, value in history if now - ts <= 600]
                    if len(fresh) >= 2:
                        rise = fresh[-1][1] - fresh[0][1]
                        if rise >= 7.0:
                            rise_target = min(
                                maximum,
                                max(normal + 2 + max(0, PRIORITY_LEVEL_BIAS.get(priority, 0)), normal + 1),
                            )
                            rise_score = 2.0 + rise / 7.0
                            if rise_target > room_target or (rise_target == room_target and rise_score > room_score):
                                room_target = rise_target
                                room_score = rise_score
                                room_metric = "humidity_rise"
                                room_reason = f"RH rise {name} +{rise:.1f}%/10m"

            diagnostics[name] = {
                **dict(values),
                "control": control,
                "priority": priority,
                "requested_level": room_target if control else None,
                "demand_metric": room_metric,
                "demand_score": round(room_score, 2),
                "reason": room_reason if control else "Monitor only",
            }
            if control and room_target > normal and room_metric:
                candidates.append((room_target, room_score, name, room_metric, room_reason))

        if not candidates:
            return normal, "All unit and HA rooms below configured thresholds", None, None, diagnostics
        target, _score, room, metric, reason = max(candidates, key=lambda item: (item[0], item[1]))
        return target, reason, room, metric, diagnostics

    def _apply_smart_hold(self, requested: int, reason: str, now: float) -> tuple[int, str]:
        d = self.config.data
        maximum = int(d["local_max_level"])
        current = self.smart_target_level
        if current is None:
            self.smart_target_level = requested
            self._smart_last_level_change = now
            if requested >= maximum:
                self._smart_boost_until = now + int(d["boost_hold_seconds"])
            return requested, reason

        if requested > current:
            current = requested
            self._smart_last_level_change = now
            if current >= maximum:
                self._smart_boost_until = now + int(d["boost_hold_seconds"])
        elif requested < current:
            if now < self._smart_boost_until:
                reason = f"Boost hold; {reason}"
            elif now - self._smart_last_level_change >= int(d["downshift_delay_seconds"]):
                current = requested
                self._smart_last_level_change = now
            else:
                remaining = max(0, int(d["downshift_delay_seconds"] - (now - self._smart_last_level_change)))
                reason = f"Downshift hold {remaining}s; {reason}"
        self.smart_target_level = current
        return current, reason

    def _recalculate_smart_demand(self, now: float | None = None, *, heartbeat: bool = False) -> None:
        now = time.time() if now is None else now
        requested, reason, room, metric, diagnostics = self._derive_smart_target(now)
        target, effective_reason = self._apply_smart_hold(requested, reason, now)
        normal = int(self.config.data["local_normal_level"])
        maximum = int(self.config.data["local_max_level"])
        if target >= maximum:
            demand = "boost"
        elif target > normal:
            demand = "high"
        elif target < normal:
            demand = "low"
        else:
            demand = "normal"

        self.smart_requested_level = requested
        self.smart_demand = demand
        self.smart_reason = effective_reason
        self.smart_controlling_room = room
        self.smart_controlling_metric = metric
        self.smart_room_diagnostics = diagnostics
        if heartbeat:
            self.config.heartbeat(demand, target_level=target, reason=effective_reason)
        else:
            with self.config.lock:
                self.config.data["ha_demand"] = demand
                self.config.data["ha_target_level"] = target
                self.config.data["ha_reason"] = effective_reason

    def _smart_input_snapshot(self) -> dict[str, object]:
        now = time.time()
        age = None if self.smart_inputs_received_at is None else max(0.0, now - self.smart_inputs_received_at)
        fresh = age is not None and age <= self.smart_inputs_valid_for
        rooms = self._rooms_with_unit_sensors()
        max_co2 = max(
            ((v.get("co2"), n) for n, v in rooms.items() if isinstance(v.get("co2"), (int, float))),
            default=(None, None),
        )
        max_rh = max(
            ((v.get("humidity"), n) for n, v in rooms.items() if isinstance(v.get("humidity"), (int, float))),
            default=(None, None),
        )
        return {
            "smart_inputs_online": fresh,
            "smart_inputs_age_seconds": round(age, 1) if age is not None else None,
            "smart_inputs_valid_for_seconds": self.smart_inputs_valid_for,
            "smart_rooms": rooms,
            "smart_ha_rooms": self.smart_rooms,
            "smart_room_diagnostics": self.smart_room_diagnostics,
            "smart_demand": self.smart_demand if fresh else "stale",
            "smart_reason": self.smart_reason if fresh else "HA room data stale; Local Auto fallback",
            "smart_requested_level": self.smart_requested_level,
            "smart_target_level": self.smart_target_level,
            "smart_controlling_room": self.smart_controlling_room,
            "smart_controlling_metric": self.smart_controlling_metric,
            "smart_max_co2": max_co2[0],
            "smart_max_co2_room": max_co2[1],
            "smart_max_rh": max_rh[0],
            "smart_max_rh_room": max_rh[1],
        }

    def snapshot(self) -> dict[str, object]:
        self.refresh_measurements()
        self._evaluate_master()
        result = self.engine.resolve()
        result["enabled"] = True  # compatibility only; not configurable
        result.update(self.master.snapshot())
        result.update(self._smart_input_snapshot())
        writes_allowed = self.master.writes_allowed()
        if self.master.master == MasterArbitrator.HCP4:
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
            "actual_supply_before_heater_temperature": self._first(self.gateway_state, "supply_temp"),
            "actual_supply_air_temperature": self._first(self.gateway_state, "heating_coil_after_temperature", "supply_temp"),
            "actual_supply_air_temperature_source": "hac1_t2ah" if self.gateway_state.get("heating_coil_after_temperature") is not None else "unit_t2",
            "actual_afterheat_frost_temperature": self._first(self.gateway_state, "heating_coil_frost_temperature"),
            "rs485_healthy": self._bus_healthy(),
            "last_tick_at": self.last_tick_at,
        })
        return result

    def configure(self, patch: dict[str, object], *, apply: bool = True) -> dict[str, object]:
        if "enabled" in patch:
            raise ControllerError("Pi-controlleren kan ikke slås fra; HCP4 master-detektion styrer automatisk overtagelse")
        self.config.configure(patch)
        self.config.data["enabled"] = True
        self._evaluate_master()
        if apply and self.hardware_writes_allowed():
            self.apply_once()
        return self.snapshot()

    def heartbeat(self, demand: str = "normal") -> dict[str, object]:
        # Kept for backwards compatibility with old HA beta clients. New HA
        # sends raw room observations through /api/controller/inputs.
        self.config.heartbeat(demand)
        self._evaluate_master()
        if self.config.data["mode"] == "smart_auto" and self.hardware_writes_allowed():
            self.apply_once()
        return self.snapshot()

    def apply_once(self) -> dict[str, object]:
        with self.apply_lock:
            self.refresh_measurements()
            if self.config.data.get("mode") == "smart_auto":
                age = None if self.smart_inputs_received_at is None else time.time() - self.smart_inputs_received_at
                if age is not None and age <= self.smart_inputs_valid_for:
                    self._recalculate_smart_demand()
            self._evaluate_master()
            if not self.master.writes_allowed():
                self.engine.resolve()
                self.last_tick_at = time.time()
                return self.snapshot()
            state = self.engine.apply()
            self.last_tick_at = time.time()
            return state

    def tick(self) -> None:
        self.refresh_measurements()
        if self.config.data.get("mode") == "smart_auto":
            age = None if self.smart_inputs_received_at is None else time.time() - self.smart_inputs_received_at
            if age is not None and age <= self.smart_inputs_valid_for:
                self._recalculate_smart_demand()
        self._evaluate_master()
        if not self.master.writes_allowed():
            self.engine.resolve()
            self.last_tick_at = time.time()
            return
        try:
            self.apply_once()
        except Exception as error:
            LOG.error("Controller write failed: %s", error)
            self.last_tick_at = time.time()

    def _run(self) -> None:
        LOG.info("Local HCH controller runtime started (automatic master=%s)", self.master.master)
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
