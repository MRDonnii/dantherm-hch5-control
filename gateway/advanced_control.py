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


def rpm_at_percent(percent: float, curve: dict) -> float:
    return float(curve["rpm_at_0"]) + float(curve["rpm_per_percent"]) * percent


def percent_at_rpm(rpm: float, curve: dict) -> float:
    return (rpm - float(curve["rpm_at_0"])) / float(curve["rpm_per_percent"])


def airflow_at_percent(percent: float, max_flow: float, curve: dict) -> float:
    """Airflow at a fan percentage: maximum airflow scaled by fan speed (fan law)."""
    return max_flow * rpm_at_percent(percent, curve) / rpm_at_percent(100.0, curve)


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


# Air balance is kept in m3/h, not in percent: each level keeps its extract
# percentage (it covers kitchen and wet rooms) and the supply percentage is
# solved so extract airflow stays a chosen share above supply airflow. That
# slight underpressure is the Danish recommendation: moist indoor air is never
# pushed out into the walls and roof. A fixed gap in percent cannot do this,
# because fan speed has a large offset at 0 % (see fan_curve): 13/25 % is a
# very different balance than 88/100 %.
#
# Equal speeds do not give equal airflow either. Each side moves k m3/h per
# rpm, set by the ducts behind it, and extract ducts (small valves in wet
# rooms, the kitchen hood) often resist more than supply ducts. The duct
# ratio k_supply/k_extract comes from airflow measured at the valves, from
# the heat balance of the exchanger (air_balance.py) or from a fixed value.
BALANCE_EXCESS_DEFAULT = 5.0
BALANCE_RATIO_MODES = {"auto", "fixed"}
DUCT_RATIO_RANGE = (0.7, 1.5)
# Profile limits the balance must respect (validate_profile in controller_core).
SUPPLY_PERCENT_MIN = 10
MAX_PERCENT_GAP = 35


def _level_entry(mapping: object, level: object) -> dict:
    if not isinstance(mapping, dict):
        return {}
    try:
        key = int(level)
    except (TypeError, ValueError):
        return {}
    entry = mapping.get(key, mapping.get(str(key)))
    return entry if isinstance(entry, dict) else {}


def learned_duct_ratio(data: dict) -> float | None:
    """Duct ratio learned from the heat balance.

    The runtime only sets ratio_in_use once two nights agree, and it stays in
    use through summers without cold nights until new windows move it.
    """
    learned = data.get("balance_learned")
    if not isinstance(learned, dict):
        return None
    try:
        ratio = float(learned["ratio_in_use"])
    except (KeyError, TypeError, ValueError):
        return None
    low, high = DUCT_RATIO_RANGE
    return ratio if low <= ratio <= high else None


def duct_ratio(data: dict) -> tuple[float, str]:
    """k_supply/k_extract in use and where it comes from ("learned" or "fixed")."""
    if data.get("balance_ratio_mode", "auto") == "auto":
        learned = learned_duct_ratio(data)
        if learned is not None:
            return learned, "learned"
    try:
        fixed = float(data.get("balance_duct_ratio") or 1.0)
    except (TypeError, ValueError):
        fixed = 1.0
    low, high = DUCT_RATIO_RANGE
    return min(high, max(low, fixed)), "fixed"


def measured_points(data: dict) -> dict[str, list[tuple[float, float]]]:
    """(rpm, m3/h) per side from airflow measured at the valves.

    A value belongs to the fan percentage it was measured at; values entered
    before that was recorded belong to the stored level profile.
    """
    curve = fan_curve(data)
    stored = data.get("profiles") or {}
    points: dict[str, list[tuple[float, float]]] = {"supply": [], "extract": []}
    measured = data.get("airflow_measured") or {}
    for raw_level, entry in (measured.items() if isinstance(measured, dict) else ()):
        if not isinstance(entry, dict):
            continue
        profile = _level_entry(stored, raw_level)
        for side in points:
            flow, percent = entry.get(side), entry.get(f"{side}_percent", profile.get(side))
            try:
                if flow and percent is not None:
                    points[side].append((rpm_at_percent(float(percent), curve), float(flow)))
            except (TypeError, ValueError):
                continue
    return points


def _fit_through_origin(points: list[tuple[float, float]]) -> float | None:
    """Least-squares k in m3/h = k x rpm (fan law: airflow follows speed)."""
    square = sum(rpm * rpm for rpm, _ in points)
    return sum(rpm * flow for rpm, flow in points) / square if square else None


def side_constants(data: dict) -> dict[str, object]:
    """Airflow per rpm on each side (m3/h per rpm) and where the split comes from.

    Both sides measured: fitted from the measurements. One side measured: the
    other follows through the duct ratio. None: the unit's maximum airflow at
    full speed, split by the duct ratio so the mean stays the same.
    """
    curve = fan_curve(data)
    ratio, source = duct_ratio(data)
    fitted = {side: _fit_through_origin(points) for side, points in measured_points(data).items()}
    supply, extract = fitted["supply"], fitted["extract"]
    if supply and extract:
        return {"supply": supply, "extract": extract, "ratio": supply / extract, "source": "measured", "measured": ["supply", "extract"]}
    if extract:
        return {"supply": extract * ratio, "extract": extract, "ratio": ratio, "source": source, "measured": ["extract"]}
    if supply:
        return {"supply": supply, "extract": supply / ratio, "ratio": ratio, "source": source, "measured": ["supply"]}
    mean = float(data["airflow_max_m3h"]) / rpm_at_percent(100.0, curve)
    root = math.sqrt(ratio)
    return {"supply": mean * root, "extract": mean / root, "ratio": ratio, "source": source, "measured": []}


def balanced_profiles(data: dict, profiles: dict) -> dict[int, dict[str, object]]:
    """Supply percentage per level that puts extract airflow the wanted share above supply.

    Each level keeps its extract percentage. Supply is solved in m3/h through
    the fan curve and the side constants, then rounded to the whole percent
    whose balance is closest to the target, within the profile limits and
    rising from level to level.
    """
    curve = fan_curve(data)
    k = side_constants(data)
    k_supply, k_extract = float(k["supply"]), float(k["extract"])
    target = 1.0 + float(data.get("balance_extract_excess_percent", BALANCE_EXCESS_DEFAULT)) / 100.0
    result: dict[int, dict[str, object]] = {}
    previous = SUPPLY_PERCENT_MIN - 1
    for level in range(1, 7):
        profile = _level_entry(profiles, level)
        extract = int(profile["extract"])
        extract_flow = k_extract * rpm_at_percent(extract, curve)
        exact = percent_at_rpm(extract_flow / target / k_supply, curve)
        low = max(SUPPLY_PERCENT_MIN, extract - MAX_PERCENT_GAP, previous + 1)
        high = extract - 1

        def ratio_at(percent: int) -> float:
            return extract_flow / (k_supply * rpm_at_percent(percent, curve))

        candidates = {min(high, max(low, value)) for value in (math.floor(exact), math.ceil(exact))}
        supply = min(candidates, key=lambda percent: (abs(ratio_at(percent) - target), percent))
        previous = supply
        result[level] = {
            "extract": extract,
            "supply": supply,
            "supply_exact": round(exact, 1),
            "extract_m3h": round(extract_flow),
            "supply_m3h": round(k_supply * rpm_at_percent(supply, curve)),
            "excess_percent": round((ratio_at(supply) - 1.0) * 100.0, 1),
            "reached": low - 0.5 <= exact <= high + 0.5,
        }
    return result

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
    percentage gives (see fan_curve) times the airflow per rpm of each side
    (see side_constants). A value measured at the valves (from the
    commissioning report) wins while the level still runs the percentage it
    was measured at, and it calibrates the estimate for the other levels.
    """
    area = float(data["house_area_m2"])
    height = float(data["ceiling_height_m"])
    bathrooms = int(data["house_bathrooms"])
    utility = int(data["house_utility_rooms"])
    reduced = float(data["sizing_reduced_percent"]) / 100.0
    measured = data.get("airflow_measured") or {}
    stored = data.get("profiles") or profiles
    curve = fan_curve(data)
    k = side_constants(data)

    volume = area * height
    area_ls = area * BR18_AREA_LS_PER_M2
    wet_ls = BR18_KITCHEN_LS + bathrooms * BR18_BATHROOM_LS + utility * BR18_UTILITY_LS
    supply_required = area_ls * LS_TO_M3H
    extract_required = max(area_ls, wet_ls) * LS_TO_M3H

    levels: dict[int, dict[str, object]] = {}
    base_level = None
    min_level = None
    for level in range(1, 7):
        profile = _level_entry(profiles, level)
        entry = _level_entry(measured, level)
        base = _level_entry(stored, level)
        flows: dict[str, float] = {}
        estimates: dict[str, float] = {}
        used_measured = False
        for side in ("supply", "extract"):
            percent = int(profile[side])
            estimates[side] = float(k[side]) * rpm_at_percent(percent, curve)
            value, measured_at = entry.get(side), entry.get(f"{side}_percent", base.get(side))
            if value and measured_at is not None and int(measured_at) == percent:
                flows[side] = float(value)
                used_measured = True
            else:
                flows[side] = estimates[side]
        supply, extract = flows["supply"], flows["extract"]
        meets = supply >= supply_required and extract >= extract_required
        meets_reduced = supply >= supply_required * reduced and extract >= extract_required * reduced
        if meets and base_level is None:
            base_level = level
        if meets_reduced and min_level is None:
            min_level = level
        levels[level] = {
            "supply_m3h": round(supply),
            "extract_m3h": round(extract),
            "estimate_supply_m3h": round(estimates["supply"]),
            "estimate_extract_m3h": round(estimates["extract"]),
            "air_changes_per_hour": round(supply / volume, 2) if volume else None,
            "measured": used_measured,
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
        "duct_ratio": round(float(k["ratio"]), 3),
        "duct_ratio_source": k["source"],
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
    "balanced_profiles",
    "side_constants",
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
