"""Week planner: several periods per weekday.

Each period belongs to a weekday (0 = Monday) and has a start, an end, a
level and a mode:

* ``set`` – the period's level replaces the normal base level. Air-quality
  demand (CO₂/humidity) may still lift it, so "away at work · level 1" can
  lower the ventilation without ignoring a humid bathroom.
* ``min`` – the level is a floor; automation can only go higher. This is what
  the old single-window schedule did.

A period whose end is earlier than its start runs past midnight into the next
day (for example Friday 22:00–02:00 ends Saturday at 02:00).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

MAX_PERIODS_PER_DAY = 8
MODES = ("set", "min")
_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class ScheduleError(ValueError):
    pass


def _minutes(value: str) -> int:
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)


def _time(value: object, label: str) -> str:
    text = str(value or "").strip()
    if text == "24:00":
        text = "00:00"
    if not _TIME.match(text):
        raise ScheduleError(f"{label} skal være HH:MM")
    return text


def normalize(raw: object) -> dict[str, list[dict[str, object]]]:
    """Validate and sort periods; raises ScheduleError on bad input."""
    if not isinstance(raw, dict):
        raise ScheduleError("Ugeplanen skal være et objekt med ugedage 0..6")
    result: dict[str, list[dict[str, object]]] = {str(day): [] for day in range(7)}
    for raw_day, periods in raw.items():
        try:
            day = int(raw_day)
        except (TypeError, ValueError) as error:
            raise ScheduleError("Ugeplanen understøtter ugedag 0..6") from error
        if not 0 <= day <= 6:
            raise ScheduleError("Ugeplanen understøtter ugedag 0..6")
        if not isinstance(periods, list):
            raise ScheduleError("Hver ugedag skal være en liste af perioder")
        if len(periods) > MAX_PERIODS_PER_DAY:
            raise ScheduleError(f"Højst {MAX_PERIODS_PER_DAY} perioder pr. dag")
        clean = []
        for period in periods:
            if not isinstance(period, dict):
                raise ScheduleError("En periode skal være et objekt")
            start = _time(period.get("start"), "Periodens start")
            end = _time(period.get("end"), "Periodens slut")
            if start == end:
                raise ScheduleError("En periode skal have forskellig start og slut")
            try:
                level = int(period.get("level"))
            except (TypeError, ValueError) as error:
                raise ScheduleError("Periodens trin skal være 1..6") from error
            if not 1 <= level <= 6:
                raise ScheduleError("Periodens trin skal være 1..6")
            mode = period.get("mode", "set")
            if mode not in MODES:
                raise ScheduleError("Periodens type skal være set eller min")
            label = str(period.get("label") or "").replace("\n", " ").strip()[:40]
            clean.append({"start": start, "end": end, "level": level, "mode": mode, "label": label})
        clean.sort(key=lambda item: _minutes(str(item["start"])))
        result[str(day)] = clean
    return result


def from_legacy(schedule: dict | None) -> dict[str, list[dict[str, object]]]:
    """The old single window per day, as ``min`` periods."""
    result: dict[str, list[dict[str, object]]] = {str(day): [] for day in range(7)}
    for day, entry in (schedule or {}).items():
        if isinstance(entry, dict) and entry.get("enabled") and str(day) in result:
            start, end = str(entry.get("start", "07:00")), str(entry.get("end", "22:00"))
            if start == end:
                start, end = "00:00", "23:59"
            result[str(day)].append({"start": start, "end": end, "level": int(entry.get("level", 3)),
                                     "mode": "min", "label": ""})
    return result


def active(periods: dict, now: datetime) -> list[dict[str, object]]:
    """Periods running at ``now`` (with ``day`` added)."""
    current = now.hour * 60 + now.minute
    today = now.weekday()
    yesterday = (today - 1) % 7
    found = []
    for day in (today, yesterday):
        for period in periods.get(str(day), []):
            start, end = _minutes(str(period["start"])), _minutes(str(period["end"]))
            if start < end:
                running = day == today and start <= current < end
            else:  # past midnight
                running = (day == today and current >= start) or (day == yesterday and current < end)
            if running:
                found.append({**period, "day": day})
    return found


def effect(periods: dict, now: datetime) -> dict[str, object] | None:
    """Combined effect of the running periods, or None when nothing runs."""
    running = active(periods, now)
    if not running:
        return None
    sets = [p for p in running if p["mode"] == "set"]
    mins = [p for p in running if p["mode"] == "min"]
    main = max(sets or mins, key=lambda p: int(p["level"]))
    return {
        "set_level": max((int(p["level"]) for p in sets), default=None),
        "min_level": max((int(p["level"]) for p in mins), default=None),
        "period": main,
    }


def _signature(value: dict[str, object] | None) -> tuple:
    return (None, None) if value is None else (value["set_level"], value["min_level"])


def next_change(periods: dict, now: datetime) -> dict[str, object] | None:
    """When the schedule's effect next changes, and what it changes to."""
    base = now.replace(second=0, microsecond=0)
    candidates = set()
    for offset in range(-1, 8):
        date = (base + timedelta(days=offset)).date()
        for period in periods.get(str(date.weekday()), []):
            for key in ("start", "end"):
                hour, minute = (int(part) for part in str(period[key]).split(":"))
                moment = datetime.combine(date, datetime.min.time(), tzinfo=base.tzinfo).replace(hour=hour, minute=minute)
                if key == "end" and _minutes(str(period["end"])) < _minutes(str(period["start"])):
                    moment += timedelta(days=1)
                if moment > base:
                    candidates.add(moment)
    current = _signature(effect(periods, base))
    for moment in sorted(candidates):
        after = effect(periods, moment)
        if _signature(after) != current:
            return {
                "at": moment.timestamp(),
                "level": None if after is None else (after["set_level"] or after["min_level"]),
                "mode": None if after is None else after["period"]["mode"],
                "label": None if after is None else after["period"]["label"],
            }
    return None
