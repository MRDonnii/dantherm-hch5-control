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

from advanced_control import absolute_humidity, source_room
from controller_core import ControllerEngine, ControllerError, ControllerState, HardwareAdapter
from master_arbitration import MasterArbitrator, RtuFrameStream
from sensor_freshness import fresh_sensor_value, sensor_sample_age

LOG = logging.getLogger("passivelink-controller")
VALID_PRIORITIES = {"auto", "low", "normal", "high", "critical"}
# HAC1 firmware lockout, confirmed by the owner 2026-09-23: the water
# afterheat never switches on while outdoor temperature (T1, register 180)
# is 15 C or higher, whatever the setpoint (even 35 C) and whoever is master.
# Register 209 staying 0 above this limit is correct HAC1 behaviour, not a
# Pi/RS485 fault - do not debug it. It is not configurable over RS485.
AFTERHEAT_OUTDOOR_CUTOFF_C = 15.0
# The HCH5 runs its bypass damper for about three minutes either way
# (180 s measured on the live unit 2026-09-23) and reports no position.
BYPASS_TRAVEL_SECONDS = 180


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

        # External fireplace switch (leased) and the automatic fireplace hold.
        self.fireplace_signal: bool | None = None
        self.fireplace_signal_until: float | None = None
        self.fireplace_auto_active = False
        self.fireplace_auto_by_temperature = False
        self.fireplace_auto_started_at: float | None = None
        self.fireplace_auto_blocked = False
        self.fireplace_auto_reason = "disabled"
        self.afterheat_room_source_used: str | None = None

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
        room = self._first(
            {
                "room_temp": fresh_sensor_value(state, "room_temp"),
                "hrc2_t5_temperature": fresh_sensor_value(state, "hrc2_t5_temperature"),
                "room_temperature": fresh_sensor_value(state, "room_temperature"),
            },
            "room_temp",
            "hrc2_t5_temperature",
            "room_temperature",
        )
        self.engine.update_measurements(
            rh=self._first(state, "humidity", "relative_humidity"),
            co2=self._first(state, "co2"),
            outdoor=self._first(state, "outdoor_temp", "outdoor_temperature"),
            room=room,
        )
        extract_temp = self._safe_number(
            self._first(state, "extract_temp", "extract_temperature"), -30, 60
        )
        room_temperature, room_source = self._afterheat_room_temperature(room, extract_temp)
        self.afterheat_room_source_used = room_source if room_temperature is not None else None
        self.engine.set_external({
            "extract_temp": extract_temp,
            "outdoor_rh": self._source_value(self.config.data.get("outdoor_humidity_source"), "humidity"),
            "afterheat_room_temperature": room_temperature,
            "stove_temperature": self._source_value(self.config.data.get("fireplace_auto_source"), "temperature"),
            "max_room_co2": self._max_room_co2(),
        })

    def _fresh_ha_rooms(self) -> dict[str, dict[str, object]]:
        return self.smart_rooms if self._smart_inputs_fresh() else {}

    def _source_room_names(self) -> set[str]:
        """HA rooms used as stove/outdoor sensors, never as indoor air quality."""
        names = set()
        for key in ("fireplace_auto_source", "outdoor_humidity_source"):
            name = source_room(self.config.data.get(key))
            if name:
                names.add(name)
        return names

    def _source_value(self, source: object, kind: str) -> float | None:
        name = source_room(source)
        if not name:
            return None
        value = self._fresh_ha_rooms().get(name, {}).get(kind)
        return float(value) if isinstance(value, (int, float)) else None

    def _ha_room_average_temperature(self) -> float | None:
        """Average of the enabled HA rooms with a temperature.

        Bathrooms are left out (showers skew them) and so are rooms chosen
        as stove or outdoor sensors. Works with whatever rooms the owner of
        the installation has added in the Home Assistant integration.
        """
        excluded = self._source_room_names()
        temperatures = [
            float(values["temperature"])
            for name, values in self._fresh_ha_rooms().items()
            if name not in excluded and values.get("enabled", True)
            and not self._is_bathroom(name, values)
            and isinstance(values.get("temperature"), (int, float))
        ]
        return round(sum(temperatures) / len(temperatures), 2) if temperatures else None

    def _afterheat_room_temperature(self, t5: object, t3: float | None) -> tuple[float | None, str | None]:
        """Room temperature for the afterheat and the source it came from."""
        source = str(self.config.data.get("afterheat_room_source") or "auto")
        if source == "auto":
            average = self._ha_room_average_temperature()
            return (average, "ha_average") if average is not None else (t3, "t3" if t3 is not None else None)
        if source == "t3":
            return t3, "t3"
        if source == "t5":
            return self._safe_number(t5, -30, 60), "t5"
        if source == "ha_average":
            return self._ha_room_average_temperature(), "ha_average"
        return self._source_value(source, "temperature"), source

    def _max_room_co2(self) -> float | None:
        excluded = self._source_room_names()
        values = [
            float(values["co2"])
            for name, values in self._fresh_ha_rooms().items()
            if name not in excluded and values.get("enabled", True) and values.get("control", True)
            and isinstance(values.get("co2"), (int, float))
        ]
        return max(values) if values else None

    def external_signals(self, payload: dict[str, object]) -> dict[str, object]:
        """Leased external switches from Home Assistant (e.g. fireplace)."""
        try:
            valid_for = int(payload.get("valid_for_s", 300))
        except (TypeError, ValueError) as error:
            raise ControllerError("valid_for_s skal være et heltal") from error
        if not 30 <= valid_for <= 900:
            raise ControllerError("valid_for_s skal være 30..900 sekunder")
        if "fireplace" in payload:
            if not isinstance(payload["fireplace"], bool):
                raise ControllerError("fireplace skal være boolean")
            self.fireplace_signal = payload["fireplace"]
            self.fireplace_signal_until = time.time() + valid_for
        self._update_fireplace_auto()
        if self.hardware_writes_allowed():
            self.apply_once()
        return self.snapshot()

    def _fireplace_signal_active(self, now: float) -> bool:
        if self.fireplace_signal_until is None or now > self.fireplace_signal_until:
            self.fireplace_signal = None
            self.fireplace_signal_until = None
            return False
        return self.fireplace_signal is True

    def _update_fireplace_auto(self, now: float | None = None) -> None:
        """Hold the unit's fireplace mode while the stove is hot or the switch is on."""
        now = time.time() if now is None else now
        d = self.config.data
        if not d.get("fireplace_auto_enabled"):
            if self.fireplace_auto_active:
                self._release_fireplace_auto(now)
            self.fireplace_auto_reason = "disabled"
            self.fireplace_auto_blocked = False
            self.fireplace_auto_by_temperature = False
            return
        stove = self.engine.external.get("stove_temperature")
        if stove is None:
            self.fireplace_auto_by_temperature = False
        elif self.fireplace_auto_by_temperature:
            self.fireplace_auto_by_temperature = stove > float(d["fireplace_auto_off_temp"])
        else:
            self.fireplace_auto_by_temperature = stove >= float(d["fireplace_auto_on_temp"])
        signal = self._fireplace_signal_active(now)
        demand = signal or self.fireplace_auto_by_temperature
        if not demand:
            if self.fireplace_auto_active:
                self._release_fireplace_auto(now)
            self.fireplace_auto_blocked = False
            self.fireplace_auto_reason = "waiting" if stove is not None or d.get("fireplace_auto_source") == "" else "no_stove_temperature"
            return
        if self.fireplace_auto_blocked:
            self.fireplace_auto_reason = "blocked_until_clear"
            return
        if not self.fireplace_auto_active:
            self.fireplace_auto_active = True
            self.fireplace_auto_started_at = now
        if now - (self.fireplace_auto_started_at or now) >= int(d["fireplace_max_hours"]) * 3600:
            self.fireplace_auto_blocked = True
            self.fireplace_auto_active = False
            self.fireplace_auto_reason = "max_duration"
            return
        afterrun = max(60, int(d["fireplace_afterrun_minutes"]) * 60)
        with self.config.lock:
            if d.get("bypass") == "on":
                d["bypass"] = "off"
            started = not d.get("fireplace")
            d["fireplace"] = True
            d["fireplace_until"] = now + afterrun
            d["fireplace_duration_minutes"] = 15
            d["quick_boost_until"] = None
            d["quick_boost_minutes"] = 0
            if started:
                self.config.save()
        self.fireplace_auto_reason = "switch" if signal else "stove_temperature"

    def _release_fireplace_auto(self, now: float) -> None:
        """Demand gone: the afterrun already set in fireplace_until runs out by itself."""
        self.fireplace_auto_active = False
        self.fireplace_auto_started_at = None

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
            room_type = str(raw_values.get("room_type", "auto")).strip().lower()
            if room_type not in {"auto", "normal", "bathroom"}:
                raise ControllerError(f"Ugyldig room_type for {name}")
            values: dict[str, object] = {
                "enabled": enabled,
                "control": control,
                "priority": priority,
                "source": source.strip(),
                "room_type": room_type,
            }
            if "rh_setpoint" in raw_values and raw_values.get("rh_setpoint") is not None:
                values["rh_setpoint"] = self._measurement(raw_values, "rh_setpoint", 35, 90)
            if "rh_hysteresis" in raw_values and raw_values.get("rh_hysteresis") is not None:
                values["rh_hysteresis"] = self._measurement(raw_values, "rh_hysteresis", 1, 20)
            if "max_level" in raw_values and raw_values.get("max_level") is not None:
                try:
                    max_level = int(raw_values["max_level"])
                except (TypeError, ValueError) as error:
                    raise ControllerError(f"max_level for {name} skal være 1..6") from error
                if not 1 <= max_level <= 6:
                    raise ControllerError(f"max_level for {name} skal være 1..6")
                values["max_level"] = max_level
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

    @staticmethod
    def _is_bathroom(name: str, values: dict[str, object]) -> bool:
        room_type = str(values.get("room_type", "auto")).lower()
        if room_type == "bathroom":
            return True
        if room_type == "normal":
            return False
        folded = name.casefold()
        return any(marker in folded for marker in ("bad", "bath", "shower", "brus"))

    def _derive_smart_decision(
        self, now: float | None = None
    ) -> tuple[int, str, str, str | None, str | None]:
        now = time.time() if now is None else now
        d = self.config.data
        excluded = self._source_room_names()
        rooms = {n: v for n, v in self._rooms_with_unit_sensors().items() if n not in excluded}
        normal = self.config.normal_level()
        candidates: list[tuple[int, int, float, str, str, str]] = []
        dry_rooms: set[str] = set()
        for name, values in rooms.items():
            if not values.get("enabled", True) or not values.get("control", True):
                continue
            if not self._room_air_dries(values):
                dry_rooms.add(name)
            priority = str(values.get("priority", "auto"))
            bathroom = self._is_bathroom(name, values)

            co2 = values.get("co2")
            if isinstance(co2, (int, float)):
                raw = self._metric_level(
                    float(co2), float(d["co2_setpoint"]), float(d["auto_step_co2"]),
                    float(d["co2_hysteresis"]), normal,
                )
                adjusted = self._priority_level(raw, priority)
                candidates.append((adjusted, raw, float(co2), name, "co2", f"CO2 {name} {float(co2):.0f} ({priority})"))

            humidity = values.get("humidity")
            if isinstance(humidity, (int, float)) and name not in dry_rooms:
                rh_setpoint = float(values.get("rh_setpoint") or (d["bathroom_rh_setpoint"] if bathroom else d["rh_setpoint"]))
                rh_hysteresis = float(values.get("rh_hysteresis") or (d["bathroom_rh_hysteresis"] if bathroom else d["rh_hysteresis"]))
                raw = self._metric_level(
                    float(humidity), rh_setpoint, float(d["auto_step_rh"]), rh_hysteresis, normal,
                )
                adjusted = self._priority_level(raw, priority)
                if bathroom:
                    adjusted = min(adjusted, int(values.get("max_level") or d["bathroom_max_level"]))
                label = "Badeværelse RH" if bathroom else "RH"
                candidates.append((adjusted, raw, float(humidity), name, "humidity", f"{label} {name} {float(humidity):.1f}% / {rh_setpoint:.0f}% ({priority})"))

        for name, history in self._room_rh_history.items():
            if name not in rooms or name in dry_rooms:
                continue
            values = rooms[name]
            if not values.get("enabled", True) or not values.get("control", True):
                continue
            fresh = [(ts, value) for ts, value in history if now - ts <= 600]
            if len(fresh) >= 2:
                rise = fresh[-1][1] - fresh[0][1]
                if rise >= 7.0:
                    raw = min(6, normal + 3 + int((rise - 7.0) // 5.0))
                    priority = str(values.get("priority", "auto"))
                    adjusted = self._priority_level(raw, priority)
                    if self._is_bathroom(name, values):
                        adjusted = min(adjusted, int(values.get("max_level") or d["bathroom_max_level"]))
                    candidates.append((
                        adjusted, raw, rise, name, "rh_rise",
                        f"RH rise {name} +{rise:.1f}%/10m ({priority})",
                    ))

        if not candidates:
            return normal, "normal", "No enabled control measurements", None, None
        adjusted, _raw, _value, room, metric, reason = max(candidates)
        adjusted = min(int(d["local_max_level"]), max(int(d["local_min_level"]), adjusted))
        demand = "low" if adjusted <= 2 else "normal" if adjusted == 3 else "high" if adjusted <= 5 else "boost"
        return adjusted, demand, reason, room, metric

    def _room_air_dries(self, values: dict[str, object]) -> bool:
        temperature = values.get("temperature")
        if not isinstance(temperature, (int, float)):
            temperature = self.engine.external.get("extract_temp")
        humidity = values.get("humidity")
        return self.engine.humidity_dries(absolute_humidity(
            temperature if isinstance(temperature, (int, float)) else None,
            humidity if isinstance(humidity, (int, float)) else None,
        ))

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
        excluded = self._source_room_names()
        rooms = {n: v for n, v in self._rooms_with_unit_sensors().items() if n not in excluded}
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
            "bathroom_policy": {
                "rh_setpoint": self.config.data.get("bathroom_rh_setpoint"),
                "rh_hysteresis": self.config.data.get("bathroom_rh_hysteresis"),
                "max_level": self.config.data.get("bathroom_max_level"),
                "night_air_quality_max_level": self.config.data.get("night_air_quality_max_level"),
            },
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
        sample_age = sensor_sample_age(self.gateway_state, "supply_temperature")
        before_heater = self._first(
            {
                "supply_temperature": fresh_sensor_value(self.gateway_state, "supply_temperature"),
                "supply_temp": fresh_sensor_value(self.gateway_state, "supply_temp"),
            },
            "supply_temperature",
            "supply_temp",
        )
        before_source = (
            str(self.gateway_state.get("temperature_source") or "canonical_t2")
            if before_heater is not None and self.gateway_state.get("supply_temperature") is not None
            else "unit_t2_legacy" if before_heater is not None
            else None
        )
        after_heater = fresh_sensor_value(self.gateway_state, "heating_coil_after_temperature")
        frost_temperature = fresh_sensor_value(self.gateway_state, "heating_coil_frost_temperature")
        outdoor = self._safe_number(
            self._first(self.gateway_state, "outdoor_temp", "outdoor_temperature"), -50, 60
        )
        travel_started = self.gateway_state.get("bypass_travel_started_monotonic")
        travel_seconds = (
            round(max(0.0, time.monotonic() - float(travel_started)), 1)
            if isinstance(travel_started, (int, float))
            else None
        )
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
            "actual_bypass_travel_direction": self._first(self.gateway_state, "bypass_travel_direction"),
            "actual_bypass_travel_seconds": travel_seconds,
            "bypass_travel_expected_seconds": BYPASS_TRAVEL_SECONDS,
            "actual_fireplace": self._first(self.gateway_state, "fireplace"),
            "actual_afterheat": self._first(self.gateway_state, "afterheat_active"),
            "actual_afterheat_setpoint": self._first(self.gateway_state, "afterheat_setpoint"),
            "actual_afterheat_selection": self._first(self.gateway_state, "afterheat_selection"),
            "actual_supply_before_heater_temperature": before_heater,
            "actual_supply_before_heater_temperature_source": before_source,
            "actual_supply_before_heater_age_seconds": round(sample_age, 1) if sample_age is not None else None,
            "actual_supply_air_temperature": after_heater,
            "actual_supply_air_temperature_source": "hac1_t2ah" if after_heater is not None else None,
            "actual_afterheat_frost_temperature": frost_temperature,
            "actual_afterheat_outdoor_lockout": (
                None if outdoor is None else outdoor >= AFTERHEAT_OUTDOOR_CUTOFF_C
            ),
            "afterheat_outdoor_cutoff": AFTERHEAT_OUTDOOR_CUTOFF_C,
            "rs485_healthy": self._bus_healthy(),
            "last_tick_at": self.last_tick_at,
            "fireplace_auto_active": self.fireplace_auto_active,
            "fireplace_auto_reason": self.fireplace_auto_reason,
            "fireplace_signal": self.fireplace_signal if self._fireplace_signal_active(time.time()) else None,
            "stove_temperature": self.engine.external.get("stove_temperature"),
            "measurement_rooms": sorted(self.smart_rooms),
            "afterheat_room_source_used": self.afterheat_room_source_used,
        })
        return result

    def configure(self, patch: dict[str, object], *, apply: bool = True) -> dict[str, object]:
        if "enabled" in patch:
            raise ControllerError("Pi-controlleren kan ikke slås fra; HCP4 master-detektion styrer automatisk overtagelse")
        self.config.configure(patch)
        self.config.data["enabled"] = True
        fireplace_off = patch.get("fireplace") is False or patch.get("fireplace_minutes") in (0, "0")
        if fireplace_off and self.fireplace_auto_active:
            self.fireplace_auto_active = False
            self.fireplace_auto_blocked = True
            self.fireplace_auto_reason = "blocked_until_clear"
        self._evaluate_master()
        # T3/T5 are stored locally and the coil type only changes the drawing.
        hardware_patch = set(patch) - {"t3_setpoint", "t5_setpoint", "afterheat_coil"}
        if apply and hardware_patch and self.hardware_writes_allowed():
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
            self._update_fireplace_auto()
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
        self._update_fireplace_auto()
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
