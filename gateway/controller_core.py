#!/usr/bin/env python3
"""Local controller for an HCH5/HAC1 with HCP4 physically disconnected.

WebUI and Home Assistant submit high-level intent. Only this controller may
translate desired state to the already hardware-verified RS485 write layer.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

VALID_MODES = {"local_auto", "smart_auto", "manual"}
VALID_DEMANDS = {"low", "normal", "high", "boost"}
VALID_BYPASS = {"auto", "open", "closed"}

# Six editable profiles. The original observed HCP4 values are retained as
# anchors (25/13, 55/43, 85/73, 100/88); levels 2 and 4 are conservative
# intermediate defaults and may be calibrated from WebUI.
DEFAULT_PROFILES = {
    1: {"extract": 25, "supply": 13, "name": "Lav"},
    2: {"extract": 40, "supply": 28, "name": "Lav+"},
    3: {"extract": 55, "supply": 43, "name": "Normal"},
    4: {"extract": 70, "supply": 58, "name": "Høj"},
    5: {"extract": 85, "supply": 73, "name": "Høj+"},
    6: {"extract": 100, "supply": 88, "name": "Boost"},
}


class ControllerError(ValueError):
    pass


def _copy_profiles(profiles: dict | None = None) -> dict[int, dict[str, object]]:
    source = profiles or DEFAULT_PROFILES
    return {
        int(level): {
            "extract": int(values["extract"]),
            "supply": int(values["supply"]),
            "name": str(values.get("name") or f"Niveau {level}"),
        }
        for level, values in source.items()
    }


def validate_profile(extract: int, supply: int) -> None:
    if not 10 <= supply <= 99:
        raise ControllerError("Indblæsning skal være 10..99 %")
    if not 11 <= extract <= 100:
        raise ControllerError("Udsugning skal være 11..100 %")
    if extract <= supply:
        raise ControllerError("Udsugning skal være højere end indblæsning")
    if extract - supply > 35:
        raise ControllerError("Forskellen mellem udsugning og indblæsning er for stor")


class HardwareAdapter:
    """Bindings to functions already verified on the physical installation."""

    def __init__(
        self,
        *,
        write_fan_pair: Callable[[int, int], object] | None = None,
        set_bypass: Callable[[str], object] | None = None,
        set_fireplace: Callable[[bool], object] | None = None,
        set_afterheat_setpoint: Callable[[int], object] | None = None,
    ) -> None:
        self.write_fan_pair = write_fan_pair
        self.set_bypass = set_bypass
        self.set_fireplace = set_fireplace
        self.set_afterheat_setpoint = set_afterheat_setpoint


class ControllerState:
    """Persistent controller configuration and desired state."""

    DEFAULTS = {
        "enabled": False,
        "mode": "local_auto",
        "manual_level": 3,
        "local_normal_level": 3,
        "local_min_level": 1,
        "local_max_level": 6,
        "rh_setpoint": 50.0,
        "rh_hysteresis": 3.0,
        "co2_setpoint": 800,
        "co2_hysteresis": 100,
        "auto_step_rh": 5.0,
        "auto_step_co2": 200,
        "downshift_delay_seconds": 300,
        "boost_hold_seconds": 600,
        "ha_demand": "normal",
        "ha_last_seen": None,
        "ha_timeout_seconds": 300,
        "bypass": "auto",
        "fireplace": False,
        # None = preserve the unit/HAC1's current supply-air setpoint.
        "afterheat_setpoint": None,
        "effective_source": "disabled",
        "effective_level": None,
        "effective_reason": "Controller disabled",
        "updated_at": 0.0,
    }

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or os.getenv(
            "DANTHERM_CONTROLLER_STATE", "/var/lib/dantherm-hch5-ha/controller.json"
        ))
        self.lock = threading.RLock()
        self.data = dict(self.DEFAULTS)
        self.data["profiles"] = _copy_profiles()
        self.data["updated_at"] = time.time()
        self.load()

    def load(self) -> None:
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(saved, dict):
            return
        for key in self.DEFAULTS:
            if key in saved:
                self.data[key] = saved[key]
        if isinstance(saved.get("profiles"), dict):
            try:
                profiles = _copy_profiles(saved["profiles"])
                if set(profiles) == set(range(1, 7)):
                    for p in profiles.values():
                        validate_profile(int(p["extract"]), int(p["supply"]))
                    self.data["profiles"] = profiles
            except (ControllerError, KeyError, TypeError, ValueError):
                pass
        self._sanitize()

    def _sanitize(self) -> None:
        if self.data["mode"] not in VALID_MODES:
            self.data["mode"] = "local_auto"
        for key, default in (("manual_level", 3), ("local_normal_level", 3),
                             ("local_min_level", 1), ("local_max_level", 6)):
            try:
                value = int(self.data[key])
            except (TypeError, ValueError):
                value = default
            self.data[key] = min(6, max(1, value))
        if self.data["local_min_level"] > self.data["local_max_level"]:
            self.data["local_min_level"], self.data["local_max_level"] = 1, 6
        self.data["local_normal_level"] = min(
            self.data["local_max_level"],
            max(self.data["local_min_level"], self.data["local_normal_level"]),
        )
        if self.data["bypass"] not in VALID_BYPASS:
            self.data["bypass"] = "auto"
        if self.data["ha_demand"] not in VALID_DEMANDS:
            self.data["ha_demand"] = "normal"
        sp = self.data.get("afterheat_setpoint")
        if sp is not None:
            try:
                sp = int(sp)
            except (TypeError, ValueError):
                sp = None
            if sp is not None and not 5 <= sp <= 40:
                sp = None
            self.data["afterheat_setpoint"] = sp

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".controller-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.data, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def configure(self, patch: dict[str, object]) -> dict[str, object]:
        with self.lock:
            if "enabled" in patch:
                self.data["enabled"] = bool(patch["enabled"])
            if "mode" in patch:
                if patch["mode"] not in VALID_MODES:
                    raise ControllerError("Ugyldig controller-mode")
                self.data["mode"] = patch["mode"]
            for key in ("manual_level", "local_normal_level", "local_min_level", "local_max_level"):
                if key in patch:
                    value = int(patch[key])
                    if not 1 <= value <= 6:
                        raise ControllerError(f"{key} skal være 1..6")
                    self.data[key] = value
            for key, low, high in (
                ("rh_setpoint", 25.0, 80.0),
                ("rh_hysteresis", 1.0, 10.0),
                ("auto_step_rh", 2.0, 20.0),
            ):
                if key in patch:
                    value = float(patch[key])
                    if not low <= value <= high:
                        raise ControllerError(f"{key} udenfor gyldigt område")
                    self.data[key] = value
            for key, low, high in (
                ("co2_setpoint", 500, 2000),
                ("co2_hysteresis", 25, 500),
                ("auto_step_co2", 50, 1000),
                ("ha_timeout_seconds", 60, 3600),
                ("downshift_delay_seconds", 30, 3600),
                ("boost_hold_seconds", 60, 3600),
            ):
                if key in patch:
                    value = int(patch[key])
                    if not low <= value <= high:
                        raise ControllerError(f"{key} udenfor gyldigt område")
                    self.data[key] = value
            if "bypass" in patch:
                if patch["bypass"] not in VALID_BYPASS:
                    raise ControllerError("Ugyldig bypass-mode")
                self.data["bypass"] = patch["bypass"]
            if "fireplace" in patch:
                self.data["fireplace"] = bool(patch["fireplace"])
            if "afterheat_setpoint" in patch:
                value = patch["afterheat_setpoint"]
                if value in (None, "", "auto"):
                    self.data["afterheat_setpoint"] = None
                else:
                    value = int(value)
                    if not 5 <= value <= 40:
                        raise ControllerError("Eftervarme-setpunkt skal være 5..40 °C")
                    self.data["afterheat_setpoint"] = value
            if "profiles" in patch:
                incoming = patch["profiles"]
                if not isinstance(incoming, dict):
                    raise ControllerError("profiles skal være et objekt")
                profiles = _copy_profiles(self.data["profiles"])
                for raw_level, values in incoming.items():
                    level = int(raw_level)
                    if level not in range(1, 7) or not isinstance(values, dict):
                        raise ControllerError("Kun niveau 1..6 understøttes")
                    extract = int(values.get("extract", profiles[level]["extract"]))
                    supply = int(values.get("supply", profiles[level]["supply"]))
                    validate_profile(extract, supply)
                    profiles[level].update(extract=extract, supply=supply)
                    if "name" in values:
                        profiles[level]["name"] = str(values["name"])[:24]
                # Keep profiles monotonic so a higher level never slows a fan.
                for level in range(2, 7):
                    if profiles[level]["extract"] <= profiles[level - 1]["extract"] or \
                            profiles[level]["supply"] <= profiles[level - 1]["supply"]:
                        raise ControllerError("Niveauerne skal stige i både udsugning og indblæsning")
                self.data["profiles"] = profiles
            self._sanitize()
            self.data["updated_at"] = time.time()
            self.save()
            return self.snapshot()

    def heartbeat(self, demand: str = "normal") -> dict[str, object]:
        if demand not in VALID_DEMANDS:
            raise ControllerError("Ugyldigt HA-demand")
        with self.lock:
            self.data["ha_last_seen"] = time.time()
            self.data["ha_demand"] = demand
            return self.snapshot()

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            result = dict(self.data)
            result["profiles"] = _copy_profiles(self.data["profiles"])
            seen = result.get("ha_last_seen")
            now = time.time()
            result["ha_online"] = bool(seen and now - float(seen) <= result["ha_timeout_seconds"])
            result["ha_age_seconds"] = round(now - float(seen), 1) if seen else None
            level = result.get("effective_level")
            result["effective_profile"] = result["profiles"].get(int(level)) if level else None
            return result


class ControllerEngine:
    """Decision engine, write deduplication and fail-safe HA fallback."""

    def __init__(self, config: ControllerState, hardware: HardwareAdapter | None = None) -> None:
        self.config = config
        self.hardware = hardware or HardwareAdapter()
        self.lock = threading.RLock()
        self.measurements: dict[str, float | bool | None] = {
            "rh": None, "co2": None, "outdoor": None, "room": None,
        }
        self.current_auto_level: int | None = None
        self.last_level_change = 0.0
        self.boost_until = 0.0
        self.last_applied: dict[str, object] = {}
        self.last_write_at: float | None = None
        self.last_error: str | None = None
        self.write_failures = 0
        self.started_at = time.time()

    def update_measurements(self, *, rh=None, co2=None, outdoor=None, room=None) -> None:
        with self.lock:
            for key, value in (("rh", rh), ("co2", co2), ("outdoor", outdoor), ("room", room)):
                if value is not None:
                    try:
                        self.measurements[key] = float(value)
                    except (TypeError, ValueError):
                        pass

    def _local_auto_level(self, now: float) -> tuple[int, str]:
        d = self.config.data
        normal = int(d["local_normal_level"])
        wanted = normal
        reasons: list[str] = []
        rh = self.measurements.get("rh")
        co2 = self.measurements.get("co2")

        if isinstance(rh, (int, float)):
            delta = rh - float(d["rh_setpoint"])
            if delta > 0:
                step = max(1.0, float(d["auto_step_rh"]))
                level = normal + max(1, math.ceil(delta / step))
                wanted = max(wanted, level)
                reasons.append(f"RH {rh:.1f}% > {float(d['rh_setpoint']):.1f}%")
        if isinstance(co2, (int, float)):
            delta = co2 - int(d["co2_setpoint"])
            if delta > 0:
                step = max(1, int(d["auto_step_co2"]))
                level = normal + max(1, math.ceil(delta / step))
                wanted = max(wanted, level)
                reasons.append(f"CO2 {co2:.0f} ppm > {int(d['co2_setpoint'])} ppm")

        wanted = min(int(d["local_max_level"]), max(int(d["local_min_level"]), wanted))
        current = self.current_auto_level or normal

        # Raising ventilation is immediate. Falling back requires both a dwell
        # time and that the demand is actually below release hysteresis.
        if wanted > current:
            current = wanted
            self.last_level_change = now
            if current == 6:
                self.boost_until = now + int(d["boost_hold_seconds"])
        elif wanted < current:
            if now < self.boost_until:
                reasons.append("Boost hold")
            else:
                rh_clear = not isinstance(rh, (int, float)) or rh <= float(d["rh_setpoint"]) - float(d["rh_hysteresis"])
                co2_clear = not isinstance(co2, (int, float)) or co2 <= int(d["co2_setpoint"]) - int(d["co2_hysteresis"])
                if rh_clear and co2_clear and now - self.last_level_change >= int(d["downshift_delay_seconds"]):
                    current = wanted
                    self.last_level_change = now
        self.current_auto_level = current
        return current, ", ".join(reasons) if reasons else "RH/CO2 normal"

    def resolve(self, now: float | None = None) -> dict[str, object]:
        now = now or time.time()
        with self.config.lock, self.lock:
            d = self.config.data
            if not d["enabled"]:
                source, level, reason = "disabled", None, "Controller disabled"
            elif d["mode"] == "manual":
                source, level, reason = "manual", int(d["manual_level"]), "Manual WebUI/HA selection"
            elif d["mode"] == "smart_auto":
                seen = d.get("ha_last_seen")
                if seen and now - float(seen) <= int(d["ha_timeout_seconds"]):
                    mapping = {"low": 1, "normal": 3, "high": 5, "boost": 6}
                    source, level = "ha_smart", mapping[d["ha_demand"]]
                    reason = f"HA demand: {d['ha_demand']}"
                else:
                    level, reason = self._local_auto_level(now)
                    source = "local_fallback"
                    reason = f"HA offline; {reason}"
            else:
                level, reason = self._local_auto_level(now)
                source = "local_auto"
            d["effective_source"] = source
            d["effective_level"] = level
            d["effective_reason"] = reason
            d["updated_at"] = now
            profile = d["profiles"].get(level) if level else None
            return {
                **self.config.snapshot(),
                "measurements": dict(self.measurements),
                "effective_profile": dict(profile) if profile else None,
                "last_write_at": self.last_write_at,
                "last_error": self.last_error,
                "write_failures": self.write_failures,
                "controller_uptime_seconds": round(now - self.started_at, 1),
            }

    def _call(self, key: str, value: object, fn: Callable | None, *args) -> None:
        if self.last_applied.get(key) == value:
            return
        if fn is None:
            raise RuntimeError(f"Hardware binding mangler: {key}")
        try:
            fn(*args)
        except Exception as error:  # Hardware boundary: preserve service and report.
            self.last_error = f"{key}: {error}"
            self.write_failures += 1
            raise
        else:
            self.last_applied[key] = value
            self.last_write_at = time.time()
            self.last_error = None

    def apply(self) -> dict[str, object]:
        """Apply only changed desired values; never create an aggressive write loop."""
        snapshot = self.resolve()
        if not snapshot["enabled"]:
            return snapshot
        profile = snapshot.get("effective_profile")
        if profile:
            pair = (int(profile["extract"]), int(profile["supply"]))
            self._call("fan_pair", pair, self.hardware.write_fan_pair, *pair)
        # 'auto' means do not force bypass in this test controller; the native
        # unit state is retained unless the user explicitly requests open/closed.
        bypass = snapshot["bypass"]
        if bypass in ("open", "closed"):
            self._call("bypass", bypass, self.hardware.set_bypass, bypass)
        self._call("fireplace", bool(snapshot["fireplace"]), self.hardware.set_fireplace, bool(snapshot["fireplace"]))
        setpoint = snapshot.get("afterheat_setpoint")
        if setpoint is not None:
            self._call("afterheat_setpoint", int(setpoint), self.hardware.set_afterheat_setpoint, int(setpoint))
        return self.resolve()
