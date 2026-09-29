"""Validate leased HA weather and relate its humidity to measured HCH5 T1.

Forecast temperature is never a substitute for the unit's physical outdoor
sensor. Weather humidity is optional and ignored if the selected location does
not approximately agree with T1.
"""

from __future__ import annotations

import math


CONDITIONS = {
    "clear-night", "cloudy", "fog", "hail", "lightning", "lightning-rainy",
    "partlycloudy", "pouring", "rainy", "snowy", "snowy-rainy", "sunny",
    "windy", "windy-variant", "exceptional",
}


def _number(value: object, minimum: float, maximum: float) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and minimum <= number <= maximum else None


def validate_weather(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ValueError("weather skal være et objekt")
    source = str(raw.get("source") or "").strip()
    if not source.startswith("weather.") or len(source) > 128:
        raise ValueError("weather.source skal være en HA weather-entitet")
    condition = str(raw.get("condition") or "").strip().lower()
    if condition and condition not in CONDITIONS:
        raise ValueError("weather.condition er ugyldig")
    result: dict[str, object] = {"source": source, "condition": condition}
    for key, minimum, maximum in (
        ("temperature_c", -50, 60), ("humidity_pct", 0, 100),
        ("dew_point_c", -60, 45),
    ):
        if raw.get(key) is not None:
            value = _number(raw[key], minimum, maximum)
            if value is None:
                raise ValueError(f"weather.{key} er ugyldig")
            result[key] = round(value, 2)
    return result


def _saturation_hpa(temperature: float) -> float:
    return 6.112 * math.exp(17.67 * temperature / (temperature + 243.5))


def humidity_at_t1(weather: dict[str, object] | None, t1: object) -> tuple[float | None, str]:
    """Return equivalent RH at the physical T1, or a clear rejection reason."""
    if not weather:
        return None, "Vejrdata mangler eller er udløbet"
    outdoor = _number(t1, -50, 60)
    model = _number(weather.get("temperature_c"), -50, 60)
    if outdoor is None:
        return None, "T1 er ikke tilgængelig"
    if model is None:
        return None, "Vejrkildens temperatur mangler"
    if abs(model - outdoor) > 6:
        return None, "Vejrkildens temperatur afviger over 6 °C fra T1"
    dew = _number(weather.get("dew_point_c"), -60, 45)
    if dew is not None:
        if dew > model + 1:
            return None, "Ugyldigt dugpunkt fra vejrkilden"
        vapour = _saturation_hpa(dew)
    else:
        relative = _number(weather.get("humidity_pct"), 0, 100)
        if relative is None:
            return None, "Vejrkildens fugt mangler"
        vapour = _saturation_hpa(model) * relative / 100
    return round(min(100.0, max(0.0, 100 * vapour / _saturation_hpa(outdoor))), 1), "Dugpunkt" if dew is not None else "Temperatur og relativ fugt"
