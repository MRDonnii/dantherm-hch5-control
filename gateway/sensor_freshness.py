"""Freshness checks for live HCH5/HAC1 temperature readings."""
from __future__ import annotations

import time

SENSOR_FRESHNESS_SECONDS = 45.0

SENSOR_SAMPLE_TIMESTAMPS = {
    "supply_temp": ("supply_temperature_sample_monotonic",),
    "supply_temperature": ("supply_temperature_sample_monotonic",),
    "heating_coil_after_temperature": ("heating_coil_after_temperature_sample_monotonic",),
    "heating_coil_frost_temperature": ("heating_coil_frost_temperature_sample_monotonic",),
    "hrc2_t5_temperature": ("hrc2_t5_temperature_sample_monotonic",),
    "room_temperature": ("hrc2_t5_temperature_sample_monotonic",),
    "room_temp": ("hrc2_t5_temperature_sample_monotonic",),
}


def sensor_sample_age(
    state: dict[str, object], field: str, *, now: float | None = None
) -> float | None:
    now = time.monotonic() if now is None else now
    for timestamp_key in SENSOR_SAMPLE_TIMESTAMPS.get(field, ()):
        sampled_at = state.get(timestamp_key)
        if isinstance(sampled_at, (int, float)) and not isinstance(sampled_at, bool):
            age = now - float(sampled_at)
            return age if age >= 0 else None
    return None


def fresh_sensor_value(
    state: dict[str, object], field: str, *, now: float | None = None
) -> object | None:
    value = state.get(field)
    age = sensor_sample_age(state, field, now=now)
    return value if value is not None and age is not None and age <= SENSOR_FRESHNESS_SECONDS else None


def hide_stale_sensor_values(
    state: dict[str, object], *, now: float | None = None
) -> dict[str, object]:
    result = dict(state)
    for field in SENSOR_SAMPLE_TIMESTAMPS:
        if fresh_sensor_value(state, field, now=now) is None:
            result[field] = None
    return result
