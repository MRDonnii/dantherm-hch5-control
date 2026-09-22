#!/usr/bin/env python3
"""Local controller for HCH5/HAC1 with modern automation and HCP4 arbitration."""
from __future__ import annotations

import json
import math
import os
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

VALID_MODES = {"local_auto", "smart_auto", "manual"}
VALID_DEMANDS = {"low", "normal", "high", "boost"}
VALID_BYPASS = {"off", "on"}
VALID_QUICK_BOOST_MINUTES = {0, 15, 30, 60}

DEFAULT_PROFILES = {
    1: {"extract": 25, "supply": 13, "name": "Lav"},
    2: {"extract": 40, "supply": 28, "name": "Lav+"},
    3: {"extract": 55, "supply": 43, "name": "Normal"},
    4: {"extract": 70, "supply": 58, "name": "Høj"},
    5: {"extract": 85, "supply": 73, "name": "Høj+"},
    6: {"extract": 100, "supply": 88, "name": "Boost"},
}

DEFAULT_SCHEDULE = {
    str(day): {"enabled": True, "start": "07:00", "end": "22:00", "level": 3}
    for day in range(7)
}
DEFAULT_SCHEDULE["5"] = {"enabled": True, "start": "08:00", "end": "23:00", "level": 3}
DEFAULT_SCHEDULE["6"] = {"enabled": True, "start": "08:00", "end": "22:00", "level": 3}


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


def _copy_schedule(schedule: dict | None = None) -> dict[str, dict[str, object]]:
    source = schedule or DEFAULT_SCHEDULE
    result: dict[str, dict[str, object]] = {}
    for day in range(7):
        values = source.get(str(day), source.get(day, DEFAULT_SCHEDULE[str(day)]))
        result[str(day)] = {
            "enabled": bool(values.get("enabled", True)),
            "start": str(values.get("start", "07:00")),
            "end": str(values.get("end", "22:00")),
            "level": int(values.get("level", 3)),
        }
    return result


def validate_profile(extract: int, supply: int) -> None:
    if not 10 <= supply <= 99:
        raise ControllerError("Indblæsning skal være 10..99 %")
    if not 11 <= extract <= 100:
        raise ControllerError("Udsugning skal være 11..100 %")
    if extract <= supply:
        raise ControllerError("Udsugning skal være højere end indblæsning")
    if extract - supply > 35:
        raise ControllerError("Forskellen mellem udsugning og indblæsning er for stor")


def _validate_time(value: object, label: str) -> str:
    text = str(value or "")
    try:
        parsed = datetime.strptime(text, "%H:%M")
    except ValueError as error:
        raise ControllerError(f"{label} skal være HH:MM") from error
    return parsed.strftime("%H:%M")


def _parse_until(value: object, label: str) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if not math.isfinite(timestamp):
            raise ControllerError(f"{label} er ugyldig")
        return timestamp
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError as error:
        raise ControllerError(f"{label} skal være en gyldig dato/tid") from error


def _minutes(value: str) -> int:
    hour, minute = (int(part) for part in value.split(":", 1))
    return hour * 60 + minute


def _time_window_active(now: datetime, start: str, end: str) -> bool:
    current = now.hour * 60 + now.minute
    first, last = _minutes(start), _minutes(end)
    if first == last:
        return True
    if first < last:
        return first <= current < last
    return current >= first or current < last


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
        "enabled": True,
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
        "ha_requested_level": 3,
        "ha_reason": "No Home Assistant room data",
        "ha_last_seen": None,
        "ha_valid_for_seconds": 180,
        "ha_timeout_seconds": 300,
        "bypass": "off",
        "fireplace": False,
        "fireplace_until": None,
        "fireplace_duration_minutes": 0,
        "afterheat_setpoint": 20,
        "schedule_enabled": False,
        "night_enabled": False,
        "night_start": "22:00",
        "night_end": "06:00",
        "night_level": 2,
        "night_air_quality_max_level": 4,
        "bathroom_rh_setpoint": 65.0,
        "bathroom_rh_hysteresis": 5.0,
        "bathroom_max_level": 4,
        "vacation_enabled": False,
        "vacation_level": 1,
        "vacation_until": None,
        "quick_boost_until": None,
        "quick_boost_level": 6,
        "quick_boost_minutes": 0,
        "cooling_enabled": False,
        "cooling_room_setpoint": 23.0,
        "cooling_hysteresis": 0.5,
        "cooling_outdoor_min": 12.0,
        "cooling_min_delta": 1.5,
        "cooling_level": 4,
        "cooling_start_delay_seconds": 180,
        "cooling_min_on_seconds": 600,
        "cooling_min_off_seconds": 300,
        "cooling_transition_timeout_seconds": 90,
        "effective_source": "local_auto",
        "effective_level": 3,
        "effective_reason": "Controller starting",
        "updated_at": 0.0,
    }

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or os.getenv("DANTHERM_CONTROLLER_STATE", "/var/lib/dantherm-hch5-ha/controller.json"))
        self.lock = threading.RLock()
        self.data = dict(self.DEFAULTS)
        self.data["profiles"] = _copy_profiles()
        self.data["schedule"] = _copy_schedule()
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
                    for values in profiles.values():
                        validate_profile(int(values["extract"]), int(values["supply"]))
                    self.data["profiles"] = profiles
            except (ControllerError, KeyError, TypeError, ValueError):
                pass
        if isinstance(saved.get("schedule"), dict):
            try:
                self.data["schedule"] = _copy_schedule(saved["schedule"])
            except (TypeError, ValueError):
                pass
        self._sanitize()

    def _sanitize(self) -> None:
        if self.data["mode"] not in VALID_MODES:
            self.data["mode"] = "local_auto"
        for key, default in (
            ("manual_level", 3), ("local_normal_level", 3),
            ("local_min_level", 1), ("local_max_level", 6),
            ("ha_requested_level", 3), ("night_level", 2),
            ("night_air_quality_max_level", 4), ("bathroom_max_level", 4),
            ("vacation_level", 1), ("quick_boost_level", 6), ("cooling_level", 4),
        ):
            try:
                value = int(self.data[key])
            except (TypeError, ValueError):
                value = default
            self.data[key] = min(6, max(1, value))
        if self.data["local_min_level"] > self.data["local_max_level"]:
            self.data["local_min_level"], self.data["local_max_level"] = 1, 6
        self.data["local_normal_level"] = min(self.data["local_max_level"], max(self.data["local_min_level"], self.data["local_normal_level"]))
        self.data["ha_requested_level"] = min(self.data["local_max_level"], max(self.data["local_min_level"], self.data["ha_requested_level"]))
        if self.data["bypass"] not in VALID_BYPASS:
            self.data["bypass"] = "off"
        if self.data["fireplace"] and self.data["bypass"] == "on":
            self.data["bypass"] = "off"
        try:
            fireplace_until = float(self.data["fireplace_until"]) if self.data.get("fireplace_until") else None
        except (TypeError, ValueError):
            fireplace_until = None
        if fireplace_until is None or fireplace_until <= time.time():
            self.data["fireplace"] = False
            self.data["fireplace_until"] = None
            self.data["fireplace_duration_minutes"] = 0
        else:
            self.data["fireplace"] = True
            self.data["fireplace_until"] = fireplace_until
            if self.data.get("fireplace_duration_minutes") not in (15, 30):
                self.data["fireplace_duration_minutes"] = 15
        if self.data["ha_demand"] not in VALID_DEMANDS:
            self.data["ha_demand"] = "normal"
        self.data["enabled"] = True
        try:
            self.data["ha_valid_for_seconds"] = min(900, max(30, int(self.data.get("ha_valid_for_seconds", 180))))
        except (TypeError, ValueError):
            self.data["ha_valid_for_seconds"] = 180
        self.data["ha_reason"] = str(self.data.get("ha_reason") or "No Home Assistant room data")[:160]
        try:
            self.data["afterheat_setpoint"] = min(30, max(18, int(self.data.get("afterheat_setpoint", 20))))
        except (TypeError, ValueError):
            self.data["afterheat_setpoint"] = 20
        for key in ("schedule_enabled", "night_enabled", "vacation_enabled", "cooling_enabled"):
            self.data[key] = bool(self.data.get(key, False))
        try:
            self.data["night_start"] = _validate_time(self.data.get("night_start"), "Nat start")
            self.data["night_end"] = _validate_time(self.data.get("night_end"), "Nat slut")
        except ControllerError:
            self.data["night_start"], self.data["night_end"] = "22:00", "06:00"
        try:
            _parse_until(self.data.get("vacation_until"), "Ferie slut")
        except ControllerError:
            self.data["vacation_until"] = None
        try:
            quick_boost_until = _parse_until(self.data.get("quick_boost_until"), "Quick Boost slut")
        except ControllerError:
            quick_boost_until = None
        try:
            quick_boost_minutes = int(self.data.get("quick_boost_minutes", 0))
        except (TypeError, ValueError):
            quick_boost_minutes = 0
        if quick_boost_minutes not in VALID_QUICK_BOOST_MINUTES or not quick_boost_until or quick_boost_until <= time.time():
            self.data["quick_boost_until"] = None
            self.data["quick_boost_minutes"] = 0
        else:
            self.data["quick_boost_until"] = quick_boost_until
            self.data["quick_boost_minutes"] = quick_boost_minutes
        for key, default, low, high in (
            ("bathroom_rh_setpoint", 65.0, 35.0, 90.0),
            ("bathroom_rh_hysteresis", 5.0, 1.0, 20.0),
            ("cooling_room_setpoint", 23.0, 18.0, 30.0),
            ("cooling_hysteresis", 0.5, 0.2, 3.0),
            ("cooling_outdoor_min", 12.0, -10.0, 25.0),
            ("cooling_min_delta", 1.5, 0.5, 10.0),
        ):
            try:
                self.data[key] = min(high, max(low, float(self.data.get(key, default))))
            except (TypeError, ValueError):
                self.data[key] = default
        for key, default, low, high in (
            ("cooling_start_delay_seconds", 180, 0, 1800),
            ("cooling_min_on_seconds", 600, 0, 3600),
            ("cooling_min_off_seconds", 300, 0, 3600),
            ("cooling_transition_timeout_seconds", 90, 30, 300),
        ):
            try:
                self.data[key] = min(high, max(low, int(self.data.get(key, default))))
            except (TypeError, ValueError):
                self.data[key] = default
        schedule = _copy_schedule(self.data.get("schedule"))
        for values in schedule.values():
            try:
                values["start"] = _validate_time(values["start"], "Tidsplan start")
                values["end"] = _validate_time(values["end"], "Tidsplan slut")
                values["level"] = min(6, max(1, int(values["level"])))
                values["enabled"] = bool(values["enabled"])
            except (ControllerError, TypeError, ValueError):
                values.update(enabled=True, start="07:00", end="22:00", level=3)
        self.data["schedule"] = schedule

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".controller-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.data, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def configure(self, patch: dict[str, object]) -> dict[str, object]:
        with self.lock:
            allowed = {
                "mode", "manual_level", "local_normal_level", "local_min_level", "local_max_level",
                "rh_setpoint", "rh_hysteresis", "co2_setpoint", "co2_hysteresis",
                "auto_step_rh", "auto_step_co2", "downshift_delay_seconds",
                "boost_hold_seconds", "ha_timeout_seconds", "bypass", "fireplace",
                "fireplace_minutes", "afterheat_setpoint", "profiles", "schedule_enabled",
                "schedule", "night_enabled", "night_start", "night_end", "night_level",
                "night_air_quality_max_level", "bathroom_rh_setpoint",
                "bathroom_rh_hysteresis", "bathroom_max_level",
                "vacation_enabled", "vacation_level", "vacation_until",
                "quick_boost_minutes", "quick_boost_level", "cooling_enabled",
                "cooling_room_setpoint", "cooling_hysteresis", "cooling_outdoor_min",
                "cooling_min_delta", "cooling_level", "cooling_start_delay_seconds",
                "cooling_min_on_seconds", "cooling_min_off_seconds", "cooling_transition_timeout_seconds",
            }
            unknown = set(patch) - allowed
            if unknown:
                raise ControllerError(f"Ukendt controller-felt: {sorted(unknown)[0]}")
            if "mode" in patch:
                if patch["mode"] not in VALID_MODES:
                    raise ControllerError("Ugyldig controller-mode")
                self.data["mode"] = patch["mode"]
            for key in ("manual_level", "local_normal_level", "local_min_level", "local_max_level", "night_level", "night_air_quality_max_level", "bathroom_max_level", "vacation_level", "quick_boost_level", "cooling_level"):
                if key in patch:
                    value = int(patch[key])
                    if not 1 <= value <= 6:
                        raise ControllerError(f"{key} skal være 1..6")
                    self.data[key] = value
            for key, low, high in (
                ("rh_setpoint", 25.0, 80.0), ("rh_hysteresis", 1.0, 10.0),
                ("bathroom_rh_setpoint", 35.0, 90.0), ("bathroom_rh_hysteresis", 1.0, 20.0),
                ("auto_step_rh", 2.0, 20.0), ("cooling_room_setpoint", 18.0, 30.0),
                ("cooling_hysteresis", 0.2, 3.0), ("cooling_outdoor_min", -10.0, 25.0),
                ("cooling_min_delta", 0.5, 10.0),
            ):
                if key in patch:
                    value = float(patch[key])
                    if not low <= value <= high:
                        raise ControllerError(f"{key} udenfor gyldigt område")
                    self.data[key] = value
            for key, low, high in (
                ("co2_setpoint", 500, 2000), ("co2_hysteresis", 25, 500),
                ("auto_step_co2", 50, 1000), ("ha_timeout_seconds", 60, 3600),
                ("downshift_delay_seconds", 30, 3600), ("boost_hold_seconds", 60, 3600),
                ("cooling_start_delay_seconds", 0, 1800), ("cooling_min_on_seconds", 0, 3600),
                ("cooling_min_off_seconds", 0, 3600), ("cooling_transition_timeout_seconds", 30, 300),
            ):
                if key in patch:
                    value = int(patch[key])
                    if not low <= value <= high:
                        raise ControllerError(f"{key} udenfor gyldigt område")
                    self.data[key] = value
            for key in ("schedule_enabled", "night_enabled", "vacation_enabled", "cooling_enabled"):
                if key in patch:
                    if not isinstance(patch[key], bool):
                        raise ControllerError(f"{key} skal være boolean")
                    self.data[key] = patch[key]
            for key, label in (("night_start", "Nat start"), ("night_end", "Nat slut")):
                if key in patch:
                    self.data[key] = _validate_time(patch[key], label)
            if "vacation_until" in patch:
                value = patch["vacation_until"]
                _parse_until(value, "Ferie slut")
                self.data["vacation_until"] = str(value)[:40] if value else None
            if "quick_boost_minutes" in patch:
                minutes = int(patch["quick_boost_minutes"])
                if minutes not in VALID_QUICK_BOOST_MINUTES:
                    raise ControllerError("Quick Boost skal være 0, 15, 30 eller 60 minutter")
                if minutes and self.data.get("fireplace"):
                    raise ControllerError("Quick Boost kan ikke startes under pejsefunktion")
                self.data["quick_boost_minutes"] = minutes
                self.data["quick_boost_until"] = time.time() + minutes * 60 if minutes else None
            if "schedule" in patch:
                incoming = patch["schedule"]
                if not isinstance(incoming, dict):
                    raise ControllerError("schedule skal være et objekt")
                schedule = _copy_schedule(self.data["schedule"])
                for raw_day, values in incoming.items():
                    day = str(int(raw_day))
                    if day not in schedule or not isinstance(values, dict):
                        raise ControllerError("Tidsplan understøtter ugedag 0..6")
                    if "enabled" in values:
                        schedule[day]["enabled"] = bool(values["enabled"])
                    if "start" in values:
                        schedule[day]["start"] = _validate_time(values["start"], "Tidsplan start")
                    if "end" in values:
                        schedule[day]["end"] = _validate_time(values["end"], "Tidsplan slut")
                    if "level" in values:
                        level = int(values["level"])
                        if not 1 <= level <= 6:
                            raise ControllerError("Tidsplan-niveau skal være 1..6")
                        schedule[day]["level"] = level
                self.data["schedule"] = schedule
            if "bypass" in patch:
                if patch["bypass"] not in VALID_BYPASS:
                    raise ControllerError("Bypass skal være off eller on")
                if patch["bypass"] == "on" and bool(patch.get("fireplace", self.data["fireplace"])):
                    raise ControllerError("Bypass kan ikke aktiveres under pejsefunktion")
                self.data["bypass"] = patch["bypass"]
            if "fireplace" in patch:
                if not isinstance(patch["fireplace"], bool):
                    raise ControllerError("fireplace skal være boolean")
                minutes = 15 if patch["fireplace"] else 0
                if minutes and self.data["bypass"] == "on":
                    raise ControllerError("Pejsefunktion kan ikke aktiveres mens bypass er tændt")
                self.data["fireplace"] = minutes > 0
                self.data["fireplace_until"] = time.time() + minutes * 60 if minutes else None
                self.data["fireplace_duration_minutes"] = minutes
                if minutes:
                    self.data["quick_boost_until"] = None
                    self.data["quick_boost_minutes"] = 0
            if "fireplace_minutes" in patch:
                minutes = int(patch["fireplace_minutes"])
                if minutes not in (0, 15, 30):
                    raise ControllerError("Pejsetid skal være 0, 15 eller 30 minutter")
                if minutes and self.data["bypass"] == "on":
                    raise ControllerError("Pejsefunktion kan ikke aktiveres mens bypass er tændt")
                self.data["fireplace"] = minutes > 0
                self.data["fireplace_until"] = time.time() + minutes * 60 if minutes else None
                self.data["fireplace_duration_minutes"] = minutes
                if minutes:
                    self.data["quick_boost_until"] = None
                    self.data["quick_boost_minutes"] = 0
            if "afterheat_setpoint" in patch:
                value = int(patch["afterheat_setpoint"])
                if not 18 <= value <= 30:
                    raise ControllerError("Eftervarme-setpunkt skal være 18..30 °C")
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
                        name = str(values["name"]).strip()
                        if not name or len(name) > 24:
                            raise ControllerError("Profilnavn skal være 1..24 tegn")
                        profiles[level]["name"] = name
                for level in range(2, 7):
                    if profiles[level]["extract"] <= profiles[level - 1]["extract"] or profiles[level]["supply"] <= profiles[level - 1]["supply"]:
                        raise ControllerError("Niveauerne skal stige i både udsugning og indblæsning")
                self.data["profiles"] = profiles
            self._sanitize()
            self.data["updated_at"] = time.time()
            self.save()
            return self.snapshot()

    def heartbeat(self, demand: str = "normal", *, requested_level: int | None = None, valid_for_s: int | None = None, reason: str | None = None) -> dict[str, object]:
        if demand not in VALID_DEMANDS:
            raise ControllerError("Ugyldigt HA-demand")
        if requested_level is not None and not 1 <= int(requested_level) <= 6:
            raise ControllerError("HA requested level skal være 1..6")
        if valid_for_s is not None and not 30 <= int(valid_for_s) <= 900:
            raise ControllerError("HA lease skal være 30..900 sekunder")
        with self.lock:
            self.data["ha_last_seen"] = time.time()
            self.data["ha_demand"] = demand
            if requested_level is not None:
                self.data["ha_requested_level"] = int(requested_level)
            if valid_for_s is not None:
                self.data["ha_valid_for_seconds"] = int(valid_for_s)
            if reason is not None:
                self.data["ha_reason"] = str(reason)[:256]
            return self.snapshot()

    def _expire_fireplace(self, now: float | None = None) -> None:
        now = now or time.time()
        until = self.data.get("fireplace_until")
        if self.data.get("fireplace") and (until is None or float(until) <= now):
            self.data["fireplace"] = False
            self.data["fireplace_until"] = None
            self.data["fireplace_duration_minutes"] = 0
            self.data["updated_at"] = now
            self.save()

    def _expire_vacation(self, now: float | None = None) -> None:
        now = now or time.time()
        if not self.data.get("vacation_enabled") or not self.data.get("vacation_until"):
            return
        try:
            until = _parse_until(self.data.get("vacation_until"), "Ferie slut")
        except ControllerError:
            until = None
        if until is not None and until <= now:
            self.data["vacation_enabled"] = False
            self.data["vacation_until"] = None
            self.data["updated_at"] = now
            self.save()

    def _expire_quick_boost(self, now: float | None = None) -> None:
        now = now or time.time()
        until = self.data.get("quick_boost_until")
        if until is None:
            return
        try:
            active_until = float(until)
        except (TypeError, ValueError):
            active_until = 0.0
        if active_until <= now:
            self.data["quick_boost_until"] = None
            self.data["quick_boost_minutes"] = 0
            self.data["updated_at"] = now
            self.save()

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            now = time.time()
            self._expire_fireplace(now)
            self._expire_vacation(now)
            self._expire_quick_boost(now)
            result = dict(self.data)
            result["profiles"] = _copy_profiles(self.data["profiles"])
            result["schedule"] = _copy_schedule(self.data["schedule"])
            seen = result.get("ha_last_seen")
            lease = min(int(result["ha_timeout_seconds"]), int(result.get("ha_valid_for_seconds", result["ha_timeout_seconds"])))
            result["ha_online"] = bool(seen and now - float(seen) <= lease)
            result["ha_age_seconds"] = round(now - float(seen), 1) if seen else None
            until = result.get("fireplace_until")
            result["fireplace_remaining_seconds"] = max(0, int(float(until) - now)) if until else 0
            boost_until = result.get("quick_boost_until")
            result["quick_boost_remaining_seconds"] = max(0, int(float(boost_until) - now)) if boost_until else 0
            vacation_until = _parse_until(result.get("vacation_until"), "Ferie slut") if result.get("vacation_until") else None
            result["vacation_remaining_seconds"] = max(0, int(vacation_until - now)) if vacation_until else None
            level = result.get("effective_level")
            result["effective_profile"] = result["profiles"].get(int(level)) if level else None
            return result


class ControllerEngine:
    """Decision engine, automation overlays, write deduplication and HA fallback."""

    def __init__(self, config: ControllerState, hardware: HardwareAdapter | None = None) -> None:
        self.config = config
        self.hardware = hardware or HardwareAdapter()
        self.lock = threading.RLock()
        self.measurements: dict[str, float | bool | None] = {"rh": None, "co2": None, "outdoor": None, "room": None}
        self.current_auto_level: int | None = None
        self.last_level_change = 0.0
        self.boost_until = 0.0
        self.cooling_active = False
        self.cooling_qualifying_since: float | None = None
        self.cooling_last_on_at: float | None = None
        self.cooling_last_off_at: float | None = None
        self.cooling_reason = "disabled"
        self.last_applied: dict[str, object] = {}
        self.last_write_at: float | None = None
        self.last_error: str | None = None
        self.write_failures = 0
        self.started_at = time.time()
        self.retry_limit = 3
        self.retry_base_seconds = 5.0
        self._failure_values: dict[str, object] = {}
        self._failure_counts: dict[str, int] = {}
        self._retry_at: dict[str, float] = {}

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
                wanted = max(wanted, normal + max(1, math.ceil(delta / max(1.0, float(d["auto_step_rh"])))))
                reasons.append(f"RH {rh:.1f}% > {float(d['rh_setpoint']):.1f}%")
        if isinstance(co2, (int, float)):
            delta = co2 - int(d["co2_setpoint"])
            if delta > 0:
                wanted = max(wanted, normal + max(1, math.ceil(delta / max(1, int(d["auto_step_co2"])))))
                reasons.append(f"CO2 {co2:.0f} ppm > {int(d['co2_setpoint'])} ppm")
        wanted = min(int(d["local_max_level"]), max(int(d["local_min_level"]), wanted))
        rh_clear = not isinstance(rh, (int, float)) or rh <= float(d["rh_setpoint"]) - float(d["rh_hysteresis"])
        co2_clear = not isinstance(co2, (int, float)) or co2 <= int(d["co2_setpoint"]) - int(d["co2_hysteresis"])
        current, held = self._stabilize_auto_level(wanted, now, allow_downshift=rh_clear and co2_clear)
        if held:
            reasons.append(held)
        return current, ", ".join(reasons) if reasons else "RH/CO2 normal"

    def _stabilize_auto_level(self, wanted: int, now: float, *, allow_downshift: bool = True) -> tuple[int, str | None]:
        d = self.config.data
        wanted = min(6, max(1, int(wanted)))
        current = self.current_auto_level if self.current_auto_level is not None else int(d["local_normal_level"])
        held = None
        if wanted > current:
            current = wanted
            self.last_level_change = now
            if current == 6:
                self.boost_until = now + int(d["boost_hold_seconds"])
        elif wanted < current:
            if now < self.boost_until:
                held = "Boost hold"
            elif not allow_downshift:
                held = "Hysteresis"
            elif now - self.last_level_change >= int(d["downshift_delay_seconds"]):
                current = wanted
                self.last_level_change = now
            else:
                held = "Downshift delay"
        self.current_auto_level = current
        return current, held

    def _stop_cooling(self, now_ts: float, reason: str) -> None:
        if self.cooling_active:
            self.cooling_last_off_at = now_ts
        self.cooling_active = False
        self.cooling_qualifying_since = None
        self.cooling_reason = reason

    def _automation_overlay(self, level: int, source: str, reason: str, now_ts: float) -> tuple[int, str, str, str, dict[str, bool]]:
        d = self.config.data
        now = datetime.fromtimestamp(now_ts).astimezone()
        flags = {"schedule_active": False, "night_active": False, "vacation_active": False, "quick_boost_active": False, "cooling_active": False}
        effective_bypass = "on" if d["bypass"] == "on" else "off"

        if d.get("vacation_enabled"):
            flags["vacation_active"] = True
            level = int(d["vacation_level"])
            source = "vacation"
            reason = f"Ferie mode · trin {level}"
            self._stop_cooling(now_ts, "vacation")
        elif d["mode"] != "manual":
            if d.get("schedule_enabled"):
                entry = d["schedule"].get(str(now.weekday()))
                if entry and entry.get("enabled") and _time_window_active(now, str(entry["start"]), str(entry["end"])):
                    flags["schedule_active"] = True
                    scheduled = int(entry["level"])
                    if level < scheduled:
                        level = scheduled
                    reason = f"{reason}; ugeskema {entry['start']}–{entry['end']}"
            if d.get("night_enabled") and _time_window_active(now, str(d["night_start"]), str(d["night_end"])):
                flags["night_active"] = True
                rh, co2 = self.measurements.get("rh"), self.measurements.get("co2")
                local_urgent = (
                    isinstance(rh, (int, float)) and rh > float(d["rh_setpoint"]) + float(d["rh_hysteresis"]) or
                    isinstance(co2, (int, float)) and co2 > int(d["co2_setpoint"]) + int(d["co2_hysteresis"])
                )
                # Night mode is a final policy layer, not a competing writer. HA Smart
                # demand may lift the night level for air quality, but only to a
                # configurable ceiling. This prevents a humid bathroom from repeatedly
                # forcing full boost while night mode simultaneously tries to reduce it.
                ha_urgent = source == "ha_smart" and level > int(d["night_level"])
                if local_urgent or ha_urgent:
                    night_cap = max(int(d["night_level"]), int(d["night_air_quality_max_level"]))
                    if level > night_cap:
                        level = night_cap
                    source = "night_air_quality"
                    reason = f"{reason}; nat: luftkvalitet begrænset til trin {night_cap}"
                else:
                    level = min(level, int(d["night_level"]))
                    source = "night"
                    reason = f"Natsænkning {d['night_start']}–{d['night_end']}"

            room = self.measurements.get("room")
            outdoor = self.measurements.get("outdoor")
            if d.get("cooling_enabled") and isinstance(room, (int, float)) and isinstance(outdoor, (int, float)):
                setpoint = float(d["cooling_room_setpoint"])
                hysteresis = float(d["cooling_hysteresis"])
                minimum = float(d["cooling_outdoor_min"])
                delta_min = float(d["cooling_min_delta"])
                delta = room - outdoor
                start_ok = room >= setpoint + hysteresis and outdoor >= minimum and delta >= delta_min
                keep_ok = room > setpoint - hysteresis and outdoor >= minimum and delta >= max(0.2, delta_min - hysteresis)
                min_on = int(d["cooling_min_on_seconds"])
                min_off = int(d["cooling_min_off_seconds"])
                start_delay = int(d["cooling_start_delay_seconds"])

                if self.cooling_active:
                    on_age = now_ts - (self.cooling_last_on_at or now_ts)
                    if keep_ok:
                        self.cooling_reason = "active"
                    elif on_age < min_on:
                        self.cooling_reason = "minimum_on_hold"
                    else:
                        if outdoor < minimum:
                            stop_reason = "outdoor_too_cold"
                        elif delta < max(0.2, delta_min - hysteresis):
                            stop_reason = "not_cooler_outside"
                        else:
                            stop_reason = "room_satisfied"
                        self._stop_cooling(now_ts, stop_reason)
                else:
                    if not start_ok:
                        self.cooling_qualifying_since = None
                        if outdoor < minimum:
                            self.cooling_reason = "outdoor_too_cold"
                        elif delta < delta_min:
                            self.cooling_reason = "not_cooler_outside"
                        elif room < setpoint + hysteresis:
                            self.cooling_reason = "room_below_start"
                        else:
                            self.cooling_reason = "standby"
                    elif self.cooling_last_off_at is not None and now_ts - self.cooling_last_off_at < min_off:
                        self.cooling_qualifying_since = None
                        self.cooling_reason = "minimum_off_hold"
                    else:
                        if self.cooling_qualifying_since is None:
                            self.cooling_qualifying_since = now_ts
                        if now_ts - self.cooling_qualifying_since >= start_delay:
                            self.cooling_active = True
                            self.cooling_last_on_at = now_ts
                            self.cooling_qualifying_since = None
                            self.cooling_reason = "opening"
                        else:
                            self.cooling_reason = "qualifying"

                if self.cooling_active:
                    flags["cooling_active"] = True
                    effective_bypass = "on"
                    level = max(level, int(d["cooling_level"]))
                    source = "free_cooling"
                    reason = f"Frikøling ({self.cooling_reason}): inde {room:.1f}°C / ude {outdoor:.1f}°C"
            else:
                if d.get("cooling_enabled"):
                    self._stop_cooling(now_ts, "sensor_missing")
                else:
                    self._stop_cooling(now_ts, "disabled")
        else:
            self._stop_cooling(now_ts, "manual_mode")

        boost_until = d.get("quick_boost_until")
        if not d.get("fireplace") and boost_until and float(boost_until) > now_ts:
            flags["quick_boost_active"] = True
            level = max(level, int(d["quick_boost_level"]))
            source = "quick_boost"
            remaining = max(1, math.ceil((float(boost_until) - now_ts) / 60))
            reason = f"Quick Boost · trin {int(d['quick_boost_level'])} · ca. {remaining} min tilbage"

        if d.get("fireplace"):
            effective_bypass = "off"
        level = min(int(d["local_max_level"]), max(int(d["local_min_level"]), int(level)))
        return level, source, reason, effective_bypass, flags

    def resolve(self, now: float | None = None) -> dict[str, object]:
        now = now or time.time()
        with self.config.lock, self.lock:
            self.config._expire_fireplace(now)
            self.config._expire_vacation(now)
            self.config._expire_quick_boost(now)
            d = self.config.data
            if d["mode"] == "manual":
                source, level, reason = "manual", int(d["manual_level"]), "Manuelt valgt niveau"
            elif d["mode"] == "smart_auto":
                seen = d.get("ha_last_seen")
                lease = min(int(d["ha_timeout_seconds"]), int(d.get("ha_valid_for_seconds", d["ha_timeout_seconds"])))
                if seen and now - float(seen) <= lease:
                    wanted = int(d["ha_requested_level"])
                    level, held = self._stabilize_auto_level(wanted, now)
                    source = "ha_smart"
                    reason = str(d.get("ha_reason") or f"HA demand: {d['ha_demand']}")
                    if held:
                        reason = f"{reason}; {held}"
                else:
                    level, reason = self._local_auto_level(now)
                    source = "local_fallback"
                    reason = f"HA offline; {reason}"
            else:
                level, reason = self._local_auto_level(now)
                source = "local_auto"

            level, source, reason, effective_bypass, flags = self._automation_overlay(level, source, reason, now)
            d["effective_source"] = source
            d["effective_level"] = level
            d["effective_reason"] = reason
            d["updated_at"] = now
            profile = d["profiles"].get(level) if level else None
            start_delay = int(d["cooling_start_delay_seconds"])
            qualifying_remaining = None
            if self.cooling_reason == "qualifying" and self.cooling_qualifying_since is not None:
                qualifying_remaining = max(0, math.ceil(start_delay - (now - self.cooling_qualifying_since)))
            min_on_remaining = 0
            if self.cooling_active and self.cooling_last_on_at is not None:
                min_on_remaining = max(0, math.ceil(int(d["cooling_min_on_seconds"]) - (now - self.cooling_last_on_at)))
            min_off_remaining = 0
            if not self.cooling_active and self.cooling_last_off_at is not None:
                min_off_remaining = max(0, math.ceil(int(d["cooling_min_off_seconds"]) - (now - self.cooling_last_off_at)))
            result = {
                **self.config.snapshot(),
                "measurements": dict(self.measurements),
                "effective_profile": dict(profile) if profile else None,
                "effective_bypass": effective_bypass,
                **flags,
                "cooling_state": self.cooling_reason,
                "cooling_qualification_remaining_seconds": qualifying_remaining,
                "cooling_min_on_remaining_seconds": min_on_remaining,
                "cooling_min_off_remaining_seconds": min_off_remaining,
                "last_write_at": self.last_write_at,
                "last_error": self.last_error,
                "write_failures": self.write_failures,
                "retry_limit": self.retry_limit,
                "next_retry_at": min(self._retry_at.values(), default=None),
                "controller_uptime_seconds": round(now - self.started_at, 1),
            }
            return result

    def _call(self, key: str, value: object, fn: Callable | None, *args) -> None:
        if self.last_applied.get(key) == value:
            return
        if self._failure_values.get(key) != value:
            self._failure_values[key] = value
            self._failure_counts[key] = 0
            self._retry_at[key] = 0.0
        now = time.time()
        if self._failure_counts.get(key, 0) >= self.retry_limit or now < self._retry_at.get(key, 0.0):
            return
        if fn is None:
            error = RuntimeError(f"Hardware binding mangler: {key}")
            self.last_error = str(error)
            self.write_failures += 1
            self._failure_counts[key] = self._failure_counts.get(key, 0) + 1
            self._retry_at[key] = now + self.retry_base_seconds * 2 ** (self._failure_counts[key] - 1)
            raise error
        try:
            fn(*args)
        except Exception as error:
            self.last_error = f"{key}: {error}"
            self.write_failures += 1
            self._failure_counts[key] = self._failure_counts.get(key, 0) + 1
            self._retry_at[key] = now + self.retry_base_seconds * 2 ** (self._failure_counts[key] - 1)
            raise
        else:
            self.last_applied[key] = value
            self.last_write_at = time.time()
            self.last_error = None
            self._failure_counts[key] = 0
            self._retry_at.pop(key, None)

    def apply(self) -> dict[str, object]:
        """Apply only changed desired values; arbitration is enforced below this layer."""
        snapshot = self.resolve()
        fireplace = bool(snapshot["fireplace"])
        previous_fireplace = self.last_applied.get("fireplace")
        self._call("fireplace", fireplace, self.hardware.set_fireplace, fireplace)
        if previous_fireplace is True and not fireplace:
            self.last_applied.pop("fan_pair", None)
        bypass = str(snapshot.get("effective_bypass", snapshot["bypass"]))
        if self.hardware.set_bypass is not None:
            self._call("bypass", bypass, self.hardware.set_bypass, bypass)
        profile = snapshot.get("effective_profile")
        if profile:
            pair = (int(profile["extract"]), int(profile["supply"]))
            self._call("fan_pair", pair, self.hardware.write_fan_pair, *pair)
        setpoint = int(snapshot["afterheat_setpoint"])
        self._call("afterheat_setpoint", setpoint, self.hardware.set_afterheat_setpoint, setpoint)
        return self.resolve()
