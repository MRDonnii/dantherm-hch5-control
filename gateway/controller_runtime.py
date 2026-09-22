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
        self.smart_requested_level = int(self.config.data["local_normal_level"])
        self.smart_controlling_room: str | None = None
        self.smart_controlling_metric: str | None = None

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

    def _smart_inputs_fresh(self, now: float | None = None) -> bool:
        if self.smart_inputs_received_at is None:
            return False
        now = time.time() if now is None else now
        return now - self.smart_inputs_received_at <= self.smart_inputs_valid_for

    def _expire_smart_lease(self, now: float | None = None) -> None:
        """Force Local Auto fallback as soon as the HA room lease expires."""
        if self.config.data.get("mode") != "smart_auto" or self._smart_inputs_fresh(now):
            return
        with self.config.lock:
            self.config.data["ha_last_seen"] = None

    def _rooms_with_unit_sensors(self) -> dict[str, dict[str, object]]:
        """Combine HA rooms with the unit's own local indoor sensors."""
        combined = {name: dict(values) for name, values in self.smart_rooms.items()}
        local: dict[str, object] = {
            "enabled": True,
            "control": True,
            "priority": "auto",
            "source": "unit",
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
            combined["HCH5 / lokale sensorer"] = local
        return combined

    @classmethod
    def _measurement(cls, values: dict, key: str, low: float, high: float):
        if key not in values or values[key] is None:
            return None
        number = cls._safe_number(values[key], low, high)
        if number is None:
            raise ControllerError(f"{key} skal være et tal mellem {low:g} og {high:g}")
        return number

    def room_inputs(self, payload: dict[str, object]) -> dict[str, object]:
        """Accept leased room measurements and metadata from Home Assistant."""
        rooms = payload.get("rooms")
        if not isinstance(rooms, dict):
            raise ControllerError("rooms skal være et objekt")
        if len(rooms) > 32:
            raise ControllerError("Højst 32 rum understøttes")
        source = payload.get("source", "home_assistant")
        if not isinstance(source, str) or not source.strip() or len(source) > 64:
            raise ControllerError("source skal være en kort tekst")
        try:
            valid_for = int(payload.get("valid_for_s", 180))
        except (TypeError, ValueError) as error:
            raise ControllerError("valid_for_s skal være et heltal") from error
        if not 30 <= valid_for <= 900:
            raise ControllerError("valid_for_s skal være 30..900 sekunder")

        now = time.time()
        sanitized: dict[str, dict[str, object]] = {}
        for raw_name, raw_values in rooms.items():
            if not isinstance(raw_values, dict):
                raise ControllerError(f"Rum {raw_name!s} skal være et objekt")
            name = str(raw_name).strip()[:64]
            if not name:
                raise ControllerError("Rumnavne må ikke være tomme")
            enabled = raw_values.get("enabled", True)
            control = raw_values.get("control", True)
            priority = raw_values.get("priority", "auto")
            if not isinstance(enabled, bool) or not isinstance(control, bool):
                raise ControllerError(f"enabled/control for {name} skal være boolean")
            if priority not in VALID_PRIORITIES:
                raise ControllerError(f"Ugyldig priority for {name}")
            values: dict[str, object] = {
                "enabled": enabled,
                "control": control,
                "priority": priority,
                "source": source.strip(),
            }
            temp = self._measurement(raw_values, "temperature", -30, 60)
            rh = self._measurement(raw_values, "humidity", 0, 100)
            co2 = self._measurement(raw_values, "co2", 250, 10000)
            if temp is not None:
                values["temperature"] = round(temp, 2)
            if rh is not None:
                values["humidity"] = round(rh, 2)
                history = self._room_rh_history[name]
                history.append((now, rh))
                while history and now - history[0][0] > 900:
                    history.popleft()
            if co2 is not None:
                values["co2"] = round(co2, 0)
            if not any(key in values for key in ("temperature", "humidity", "co2")):
                raise ControllerError(f"{name} har ingen gyldige målinger")
            sanitized[name] = values

        self.smart_rooms = sanitized
        self.smart_inputs_received_at = now
        self.smart_inputs_valid_for = valid_for
        decision = self._derive_smart_decision(now)
        self.smart_requested_level = decision[0]
        self.smart_demand = decision[1]
        self.smart_reason = decision[2]
        self.smart_controlling_room = decision[3]
        self.smart_controlling_metric = decision[4]
        self.config.heartbeat(
            self.smart_demand,
            requested_level=self.smart_requested_level,
            valid_for_s=valid_for,
            reason=self.smart_reason,
        )
        if self.config.data.get("mode") == "smart_auto" and self.hardware_writes_allowed():
            self.apply_once()
        return self.snapshot()

    @staticmethod
    def _priority_level(level: int, priority: str) -> int:
        """Adjust response speed without allowing mild rooms to hide severe ones."""
        if priority == "low" and level < 6:
            return max(1, level - 1)
        if priority == "high" and level < 6:
            return min(6, level + 1)
        if priority == "critical" and level < 6:
            return min(6, level + 2)
        return level

    @staticmethod
    def _metric_level(value: float, setpoint: float, step: float,
                      hysteresis: float, normal: int) -> int:
        if value > setpoint:
            return min(6, normal + max(1, int((value - setpoint + step - 0.0001) // step)))
        if value <= setpoint - hysteresis:
            distance = setpoint - hysteresis - value
            return max(1, normal - max(1, int((distance + step - 0.0001) // step)))
        return normal

    def _derive_smart_decision(
        self, now: float | None = None
    ) -> tuple[int, str, str, str | None, str | None]:
        now = time.time() if now is None else now
        d = self.config.data
        rooms = self._rooms_with_unit_sensors()
        normal = int(d["local_normal_level"])
        candidates: list[tuple[int, int, float, str, str, str]] = []
        for name, values in rooms.items():
            if not values.get("enabled", True) or not values.get("control", True):
                continue
            priority = str(values.get("priority", "auto"))
            for metric, setpoint, step, hysteresis, label in (
                ("co2", float(d["co2_setpoint"]), float(d["auto_step_co2"]), float(d["co2_hysteresis"]), "CO2"),
                ("humidity", float(d["rh_setpoint"]), float(d["auto_step_rh"]), float(d["rh_hysteresis"]), "RH"),
            ):
                value = values.get(metric)
                if not isinstance(value, (int, float)):
                    continue
                raw = self._metric_level(float(value), setpoint, step, hysteresis, normal)
                adjusted = self._priority_level(raw, priority)
                reason = f"{label} {name} {float(value):.1f} ({priority})"
                candidates.append((adjusted, raw, float(value), name, label.lower(), reason))

        for name, history in self._room_rh_history.items():
            values = rooms.get(name, {})
            if not values.get("enabled", True) or not values.get("control", True):
                continue
            fresh = [(ts, value) for ts, value in history if now - ts <= 600]
            if len(fresh) >= 2:
                rise = fresh[-1][1] - fresh[0][1]
                if rise >= 7.0:
                    # A shower-like rise is intentionally stronger than the
                    # same room's still-moderate absolute RH reading.
                    raw = min(6, normal + 3 + int((rise - 7.0) // 5.0))
                    priority = str(values.get("priority", "auto"))
                    candidates.append((
                        self._priority_level(raw, priority), raw, rise, name,
                        "rh_rise", f"RH rise {name} +{rise:.1f}%/10m ({priority})",
                    ))

        if not candidates:
            return normal, "normal", "No enabled control measurements", None, None
        adjusted, _raw, _value, room, metric, reason = max(candidates)
        adjusted = min(int(d["local_max_level"]), max(int(d["local_min_level"]), adjusted))
        demand = "low" if adjusted <= 2 else "normal" if adjusted == 3 else "high" if adjusted <= 5 else "boost"
        return adjusted, demand, reason, room, metric

    def _derive_smart_demand(self, now: float | None = None) -> tuple[str, str]:
        """Compatibility helper for older callers."""
        _level, demand, reason, _room, _metric = self._derive_smart_decision(now)
        return demand, reason

    def _recalculate_smart_demand(self, now: float | None = None) -> None:
        """Refresh a live Smart Auto lease from the latest room measurements."""
        decision = self._derive_smart_decision(now)
        self.smart_requested_level = decision[0]
        self.smart_demand = decision[1]
        self.smart_reason = decision[2]
        self.smart_controlling_room = decision[3]
        self.smart_controlling_metric = decision[4]
        self.config.heartbeat(
            self.smart_demand,
            requested_level=self.smart_requested_level,
            valid_for_s=self.smart_inputs_valid_for,
            reason=self.smart_reason,
        )

    def _smart_input_snapshot(self) -> dict[str, object]:
        now = time.time()
        age = None if self.smart_inputs_received_at is None else max(0.0, now - self.smart_inputs_received_at)
        fresh = self._smart_inputs_fresh(now)
        rooms = self._rooms_with_unit_sensors()
        max_co2 = max(
            ((v.get("co2"), n) for n, v in rooms.items()
             if v.get("enabled", True) and v.get("co2") is not None),
            default=(None, None),
        )
        max_rh = max(
            ((v.get("humidity"), n) for n, v in rooms.items()
             if v.get("enabled", True) and v.get("humidity") is not None),
            default=(None, None),
        )
        return {
            "smart_inputs_online": fresh,
            "smart_inputs_age_seconds": round(age, 1) if age is not None else None,
            "smart_inputs_valid_for_seconds": self.smart_inputs_valid_for,
            "smart_rooms": rooms,
            "smart_ha_rooms": self.smart_rooms,
            "smart_demand": self.smart_demand if fresh else "stale",
            "smart_requested_level": self.smart_requested_level if fresh else None,
            "smart_target_level": self.engine.current_auto_level if fresh else None,
            "smart_controlling_room": self.smart_controlling_room if fresh else None,
            "smart_controlling_metric": self.smart_controlling_metric if fresh else None,
            "smart_reason": self.smart_reason if fresh else "HA room data stale; Local Auto fallback",
            "smart_max_co2": max_co2[0],
            "smart_max_co2_room": max_co2[1],
            "smart_max_rh": max_rh[0],
            "smart_max_rh_room": max_rh[1],
        }

    def snapshot(self) -> dict[str, object]:
        self.refresh_measurements()
        self._expire_smart_lease()
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
            "actual_bypass_raw": self._first(self.gateway_state, "bypass_raw"),
            "actual_bypass_request": self._first(self.gateway_state, "bypass_request"),
            "actual_bypass_request_raw": self._first(self.gateway_state, "bypass_request_raw"),
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
            self._expire_smart_lease()
            if self.config.data.get("mode") == "smart_auto" and self._smart_inputs_fresh():
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
        self._expire_smart_lease()
        if self.config.data.get("mode") == "smart_auto" and self._smart_inputs_fresh():
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
