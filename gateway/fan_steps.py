"""Fan steps: Dantherm's four steps from one commissioning, or six free steps.

The owner chooses the step control (fan_step_count). Four steps is the
default and follows Dantherm's HCP4/HRC2 exactly; six steps is the free
table of the first controller releases, kept so it can be chosen again.

Installation and service manual, "Setpunkter": the steps are fan gears
(motor commands 1..100), not measured airflow.

- Step 3 is the nominal airflow the house needs. Each fan is commissioned on
  its own at step 3, gear 46..91.
- Steps 2 and 1 lie one and two offsets ("OFSET") below step 3 on both fans.
  The offset is 25 gear from the factory and 10..30 gear on the HRC 2.
- Step 4 is maximum speed: gear 100, or on the HRC 2 anything from step 3 up
  to gear 100. Chosen by hand it runs for four hours and then returns.
- Supply airflow must never be higher than extract airflow.
"""
from __future__ import annotations

import copy

LEVELS = (1, 2, 3, 4)
MIN_LEVEL, NOMINAL_LEVEL, MAX_LEVEL = 1, 3, 4
LEVEL_NAMES = {1: "Lav", 2: "Reduceret", 3: "Nominel", 4: "Maksimum"}
GEAR_RANGE = (1, 100)
NOMINAL_RANGE = (46, 91)
OFFSET_RANGE = (10, 30)
OFFSET_DEFAULT = 25
# Step 4 chosen by hand returns to step 3 after this long (HCH 5 user manual).
MAX_LEVEL_HOURS = 4
SIDES = ("supply", "extract")
FAN_KEYS = ("supply", "extract", "offset", "max_supply", "max_extract")
DEFAULT_FAN_SETTINGS = {"supply": 64, "extract": 64, "offset": OFFSET_DEFAULT, "max_supply": 100, "max_extract": 100}
STEP_COUNTS = (4, 6)
# The free six-step table (extract/supply gear per step) of earlier releases.
SIX_DEFAULT_PROFILES = {
    1: {"extract": 25, "supply": 13, "name": "Lav"},
    2: {"extract": 40, "supply": 28, "name": "Lav+"},
    3: {"extract": 55, "supply": 43, "name": "Normal"},
    4: {"extract": 70, "supply": 58, "name": "Høj"},
    5: {"extract": 85, "supply": 73, "name": "Høj+"},
    6: {"extract": 100, "supply": 88, "name": "Boost"},
}


def clean_fan_settings(value: object, base: dict | None = None) -> dict[str, int]:
    """Validated commissioning; keys missing from value are taken from base."""
    if not isinstance(value, dict):
        raise ValueError("Indreguleringen skal være et objekt")
    unknown = set(value) - set(FAN_KEYS)
    if unknown:
        raise ValueError(f"Ukendt indreguleringsfelt: {sorted(unknown)[0]}")
    merged = {**DEFAULT_FAN_SETTINGS, **(base or {}), **value}
    result: dict[str, int] = {}
    for key in FAN_KEYS:
        raw = merged[key]
        if isinstance(raw, bool):
            raise ValueError("Ventilatorgear skal være hele tal")
        try:
            number = float(raw)
        except (TypeError, ValueError) as error:
            raise ValueError("Ventilatorgear skal være hele tal") from error
        if number != int(number):
            raise ValueError("Ventilatorgear skal være hele tal")
        result[key] = int(number)
    low, high = OFFSET_RANGE
    if not low <= result["offset"] <= high:
        raise ValueError(f"Gearafstanden skal være {low}..{high} gear")
    label = {"supply": "Indblæsning", "extract": "Udsugning"}
    for side in SIDES:
        low, high = NOMINAL_RANGE
        if not low <= result[side] <= high:
            raise ValueError(f"{label[side]} på trin 3 skal være gear {low}..{high}")
        if not result[side] <= result[f"max_{side}"] <= GEAR_RANGE[1]:
            raise ValueError(f"{label[side]} på trin 4 skal være fra trin 3 op til gear 100")
    return result


def ladder(settings: dict) -> dict[int, dict[str, object]]:
    """Gear per step for both fans, exactly as the HCP4 panel derives them."""
    result: dict[int, dict[str, object]] = {}
    for level in LEVELS:
        entry: dict[str, object] = {"name": LEVEL_NAMES[level]}
        for side in SIDES:
            if level == MAX_LEVEL:
                entry[side] = int(settings[f"max_{side}"])
            else:
                entry[side] = max(GEAR_RANGE[0], int(settings[side]) - (NOMINAL_LEVEL - level) * int(settings["offset"]))
        result[level] = entry
    return result


def validate_ladder(profiles: dict) -> None:
    """Four or six steps, gear 1..100, supply never above extract, never falling."""
    count = len(profiles)
    if count not in STEP_COUNTS or set(profiles) != set(range(1, count + 1)):
        raise ValueError("Der skal være trin 1..4 eller 1..6")
    low, high = GEAR_RANGE
    for level in range(1, count + 1):
        values = profiles[level]
        supply, extract = int(values["supply"]), int(values["extract"])
        if not (low <= supply <= high and low <= extract <= high):
            raise ValueError(f"Trin {level}: gear skal være {low}..{high}")
        if supply > extract:
            raise ValueError(f"Trin {level}: indblæsningen må ikke være højere end udsugningen")
        if level > MIN_LEVEL:
            below = profiles[level - 1]
            if supply < int(below["supply"]) or extract < int(below["extract"]):
                raise ValueError("Trinene må ikke falde fra trin til trin")


def closest_level(pair: dict, profiles: dict) -> int:
    """New step whose gear pair is nearest to an old (supply, extract) pair."""
    return min(sorted(profiles), key=lambda level: (
        sum((int(profiles[level][side]) - int(pair[side])) ** 2 for side in SIDES), level))


LEVEL_KEYS = (
    "manual_level", "local_normal_level", "local_min_level", "local_max_level",
    "ha_requested_level", "night_level", "night_air_quality_max_level",
    "bathroom_max_level", "vacation_level", "quick_boost_level", "cooling_level",
    "dry_max_level", "pm25_max_level", "effective_level",
)


def remap_levels(data: dict, old: dict, new: dict) -> dict:
    """Move every stored step choice from one step table to another.

    Each choice goes to the new step with the nearest gear pair, so the fans
    keep running as close as possible to what was chosen.
    """
    old = {int(key): value for key, value in old.items()}
    new = {int(key): value for key, value in new.items()}

    def move(value: object) -> int:
        try:
            pair = old.get(int(value))
        except (TypeError, ValueError):
            pair = None
        return closest_level(pair, new) if pair else min(NOMINAL_LEVEL, max(new))

    result = copy.deepcopy(data)
    for key in LEVEL_KEYS:
        if result.get(key) is not None:
            result[key] = move(result[key])
    for entry in (result.get("schedule") or {}).values():
        if isinstance(entry, dict) and "level" in entry:
            entry["level"] = move(entry["level"])
    for periods in (result.get("schedule_periods") or {}).values():
        for entry in periods if isinstance(periods, list) else ():
            if isinstance(entry, dict) and entry.get("level") is not None:
                entry["level"] = move(entry["level"])
    return result


def migrate_six_steps(saved: dict) -> tuple[dict, bool]:
    """Move a controller file from before the step choice to four steps.

    The pair the unit ran at becomes step 3 (manual level, else the normal
    level), so nothing changes on the upgrade. Every stored step choice moves
    to the new step with the nearest gear pair: old step 4 was an ordinary
    continuous step and becomes step 3, old step 6 becomes step 4. The six-step
    table is kept, so six steps can be chosen again exactly as they were.
    """
    raw = saved.get("profiles")
    if "fan_step_count" in saved or not isinstance(raw, dict) or set(map(str, raw)) != {"1", "2", "3", "4", "5", "6"}:
        return saved, False
    old = {int(key): value for key, value in raw.items()}
    try:
        source = int(saved.get("manual_level") if saved.get("mode") == "manual" else saved.get("local_normal_level") or 3)
    except (TypeError, ValueError):
        source = 3
    running = old.get(source) or old[3]
    low, high = NOMINAL_RANGE
    settings = {side: min(high, max(low, int(running[side]))) for side in SIDES}
    settings["supply"] = min(settings["supply"], settings["extract"])
    settings.update(offset=OFFSET_DEFAULT, max_supply=100, max_extract=100)
    settings = clean_fan_settings(settings)
    profiles = ladder(settings)
    result = remap_levels(saved, old, profiles)
    result["profiles"] = {str(level): values for level, values in profiles.items()}
    result["six_step_profiles"] = {str(level): dict(values) for level, values in old.items()}
    result["fan_settings"] = settings
    result["fan_step_count"] = 4
    # Measured airflow belongs to the step it was measured at.
    result["airflow_measured_6"] = copy.deepcopy(saved.get("airflow_measured") or {})
    result["airflow_measured"] = {}
    result["quick_boost_until"], result["quick_boost_minutes"] = None, 0
    result["fan_steps_migration"] = {"from_steps": 6, "running_level": source}
    return result, True
