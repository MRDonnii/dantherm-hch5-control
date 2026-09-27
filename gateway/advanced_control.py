#!/usr/bin/env python3
"""Pure calculations behind the advanced controller features.

Nothing here talks to the bus. The controller core calls these helpers to
size the ventilation from the house, judge whether outdoor air actually dries
the house, and move the afterheat setpoint from the room temperature.
"""
from __future__ import annotations

import math

# Dantherm HCH 5 datasheet: maximum airflow 375 m3/h (320 m3/h recommended).
HCH5_MAX_AIRFLOW_M3H = 375
# BR18 §447: at least 0.3 l/s per m2 heated floor area in dwellings, plus
# minimum extract from wet rooms at the same time.
BR18_AREA_LS_PER_M2 = 0.3
BR18_KITCHEN_LS = 20.0
BR18_BATHROOM_LS = 15.0
BR18_UTILITY_LS = 10.0
LS_TO_M3H = 3.6
# HCH5 EC fans: speed follows the control percentage in a straight line with a
# large offset, measured on the reference unit (both fans alike): about 557 rpm
# at 0 % plus 24 rpm per %. By the fan laws airflow follows speed, not the
# percentage, so low levels move far more air than percent x maximum suggests.
# The controller learns the curve of the actual unit and replaces these.
DEFAULT_FAN_RPM_AT_0 = 557.0
DEFAULT_FAN_RPM_PER_PERCENT = 24.0


def fan_curve(data: dict) -> dict[str, object]:
    """The fan speed curve in use: learned from the unit, else the HCH5 default."""
    learned = data.get("fan_curve")
    if isinstance(learned, dict):
        try:
            at_0 = float(learned["rpm_at_0"])
            per_percent = float(learned["rpm_per_percent"])
        except (KeyError, TypeError, ValueError):
            pass
        else:
            if 0.0 <= at_0 <= 1500.0 and 5.0 <= per_percent <= 60.0:
                return {"rpm_at_0": at_0, "rpm_per_percent": per_percent, "learned": True,
                        "samples": int(learned.get("samples") or 0)}
    return {"rpm_at_0": DEFAULT_FAN_RPM_AT_0, "rpm_per_percent": DEFAULT_FAN_RPM_PER_PERCENT,
            "learned": False, "samples": 0}


def airflow_at_percent(percent: float, max_flow: float, curve: dict) -> float:
    """Airflow at a fan percentage: maximum airflow scaled by fan speed (fan law)."""
    at_0, per_percent = float(curve["rpm_at_0"]), float(curve["rpm_per_percent"])
    return max_flow * (at_0 + per_percent * percent) / (at_0 + per_percent * 100.0)


def fit_fan_curve(points: dict[int, float]) -> dict[str, float] | None:
    """Least-squares line rpm = a + b x percent through per-percent speeds."""
    if len(points) < 3 or max(points) - min(points) < 30:
        return None
    xs, ys = list(points), [points[x] for x in points]
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if not sxx:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / sxx
    intercept = mean_y - slope * mean_x
    if not (5.0 <= slope <= 60.0 and 0.0 <= intercept <= 1500.0):
        return None
    return {"rpm_at_0": round(intercept, 1), "rpm_per_percent": round(slope, 2)}

# "auto": average of the owner's Home Assistant rooms that have a temperature
# (bathrooms and stove/outdoor sensor rooms left out), else T3 extract air.
# T3 alone mixes in kitchen and bathroom air; T5 (HRC2 remote) is not live
# once the Pi replaces HCP4, so both are only options.
TEMPERATURE_SOURCE_FIXED = {"auto", "t3", "t5", "ha_average"}
ROOM_PREFIX = "room:"


def absolute_humidity(temperature: float | None, relative_humidity: float | None) -> float | None:
    """Water content of air in g/m3 (Magnus formula), or None without data."""
    if temperature is None or relative_humidity is None:
        return None
    if not -40.0 <= temperature <= 60.0 or not 0.0 <= relative_humidity <= 100.0:
        return None
    saturation_hpa = 6.112 * math.exp(17.67 * temperature / (temperature + 243.5))
    return saturation_hpa * relative_humidity * 2.1674 / (273.15 + temperature)


def valid_source(value: object, *, allow_fixed: bool) -> str:
    """Normalise a measurement source: '', 't5', 'ha_average' or 'room:<name>'."""
    text = str(value or "").strip()
    if not text:
        return ""
    if allow_fixed and text in TEMPERATURE_SOURCE_FIXED:
        return text
    if text.startswith(ROOM_PREFIX) and 0 < len(text[len(ROOM_PREFIX):].strip()) <= 64:
        return ROOM_PREFIX + text[len(ROOM_PREFIX):].strip()
    raise ValueError("ugyldig målekilde")


def source_room(value: object) -> str | None:
    text = str(value or "")
    return text[len(ROOM_PREFIX):] if text.startswith(ROOM_PREFIX) else None


def airflow_plan(data: dict, profiles: dict) -> dict[str, object]:
    """Required airflow for the house and which fan levels deliver it.

    Levels without a measured airflow are estimated from the fan speed the
    percentage gives (see fan_curve) and the unit's maximum airflow. The
    estimate ignores duct pressure, so a measured value (from the
    commissioning report) wins.
    """
    area = float(data["house_area_m2"])
    height = float(data["ceiling_height_m"])
    bathrooms = int(data["house_bathrooms"])
    utility = int(data["house_utility_rooms"])
    max_flow = float(data["airflow_max_m3h"])
    reduced = float(data["sizing_reduced_percent"]) / 100.0
    measured = data.get("airflow_measured") or {}
    curve = fan_curve(data)

    volume = area * height
    area_ls = area * BR18_AREA_LS_PER_M2
    wet_ls = BR18_KITCHEN_LS + bathrooms * BR18_BATHROOM_LS + utility * BR18_UTILITY_LS
    supply_required = area_ls * LS_TO_M3H
    extract_required = max(area_ls, wet_ls) * LS_TO_M3H

    levels: dict[int, dict[str, object]] = {}
    base_level = None
    min_level = None
    for level in range(1, 7):
        profile = profiles[level]
        entry = measured.get(str(level)) or measured.get(level) or {}
        supply_measured = entry.get("supply") if isinstance(entry, dict) else None
        extract_measured = entry.get("extract") if isinstance(entry, dict) else None
        supply = float(supply_measured) if supply_measured else airflow_at_percent(int(profile["supply"]), max_flow, curve)
        extract = float(extract_measured) if extract_measured else airflow_at_percent(int(profile["extract"]), max_flow, curve)
        meets = supply >= supply_required and extract >= extract_required
        meets_reduced = supply >= supply_required * reduced and extract >= extract_required * reduced
        if meets and base_level is None:
            base_level = level
        if meets_reduced and min_level is None:
            min_level = level
        levels[level] = {
            "supply_m3h": round(supply),
            "extract_m3h": round(extract),
            "air_changes_per_hour": round(supply / volume, 2) if volume else None,
            "measured": bool(supply_measured or extract_measured),
            "meets_requirement": meets,
            "meets_reduced": meets_reduced,
        }
    reachable = base_level is not None
    base_level = base_level or 6
    min_level = min(min_level or base_level, base_level)
    return {
        "volume_m3": round(volume),
        "supply_required_m3h": round(supply_required),
        "extract_required_m3h": round(extract_required),
        "area_requirement_ls": round(area_ls, 1),
        "wet_room_requirement_ls": round(wet_ls, 1),
        "required_air_changes_per_hour": round(supply_required / volume, 2) if volume else None,
        "reduced_percent": round(reduced * 100),
        "base_level": base_level,
        "min_level": min_level,
        "reachable": reachable,
        "estimated": not all(values["measured"] for values in levels.values()),
        "fan_curve": curve,
        "levels": levels,
    }


def supply_after_core(outdoor: float | None, extract: float | None, recovery: float | None, bypass_open: bool) -> float | None:
    """Estimated supply air leaving the core (T2 before the afterheat coil)."""
    if outdoor is None:
        return None
    if bypass_open or extract is None or recovery is None:
        return outdoor
    return outdoor + min(100.0, max(0.0, recovery)) / 100.0 * (extract - outdoor)


def afterheat_room_target(data: dict, room_temperature: float | None) -> int | None:
    """Supply setpoint wanted for the current room temperature, or None."""
    if room_temperature is None:
        return None
    low = int(data["afterheat_room_min"])
    high = int(data["afterheat_room_max"])
    wanted = float(data["afterheat_setpoint"]) + float(data["afterheat_room_gain"]) * (
        float(data["afterheat_room_target"]) - room_temperature
    )
    return int(min(high, max(low, round(wanted))))


__all__ = [
    "HCH5_MAX_AIRFLOW_M3H",
    "absolute_humidity",
    "afterheat_room_target",
    "airflow_plan",
    "source_room",
    "valid_source",
]


# Volumetric heat capacity of air, J/(m3*K): 1.2 kg/m3 x 1005 J/(kg*K).
AIR_HEAT_CAPACITY = 1206.0


def supply_air_metrics(
    outdoor: float | None,
    extract: float | None,
    before_heater: float | None,
    after_heater: float | None,
    supply_m3h: float | None,
    bypass_open: bool,
) -> dict[str, float | None]:
    """What a measured T2 (before the afterheat coil) makes computable.

    - supply_recovery_percent: recovery seen on the supply side, (T2-T1)/(T3-T1).
      Needs at least 3 K between extract and outdoor air, else it is noise.
    - recovered_heat_w: heat the exchanger hands to the supply air.
    - afterheat_lift: temperature rise across the afterheat coil, T2AH-T2.
    - afterheat_power_w: heat the coil adds to the air (0 when it adds none).
    Airflow is the estimate for the running fan level, so the watts are too.
    """
    result: dict[str, float | None] = {
        "supply_recovery_percent": None,
        "recovered_heat_w": None,
        "afterheat_lift": None,
        "afterheat_power_w": None,
    }
    if before_heater is None:
        return result
    flow = supply_m3h / 3600.0 * AIR_HEAT_CAPACITY if supply_m3h else None
    if outdoor is not None and not bypass_open:
        if extract is not None and extract - outdoor >= 3:
            share = (before_heater - outdoor) / (extract - outdoor) * 100
            if -5 <= share <= 110:
                result["supply_recovery_percent"] = round(min(100.0, max(0.0, share)), 1)
        if flow is not None:
            result["recovered_heat_w"] = round(max(0.0, before_heater - outdoor) * flow)
    if after_heater is not None:
        lift = after_heater - before_heater
        result["afterheat_lift"] = round(lift, 2)
        if flow is not None:
            result["afterheat_power_w"] = round(max(0.0, lift) * flow)
    return result
