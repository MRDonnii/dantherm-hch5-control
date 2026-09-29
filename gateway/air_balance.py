#!/usr/bin/env python3
"""Heat balance of the exchanger: how the two airflows really compare.

The sensible heat the extract air gives off is the heat the supply air takes up:

    supply m3/h x (T2 - T1) = extract m3/h x (T3 - T4)

so the ratio of the two temperature changes is the ratio of the airflows,
without an airflow meter. Divided by the ratio of the fan speeds it gives the
duct ratio k_supply/k_extract that the air balance needs (advanced_control).
T2 must be measured between the core and the afterheat coil (a 1-Wire sensor
with the role "t2"); the unit's own T2 register only repeats T2AH.

What spoils the balance, and what is done about it:
- Fan heat. Both HCH5 fans sit at the cold end, and their electrical power
  ends up as heat in the air. Where the unit's T1 and T4 sensors sit relative
  to the fans is not known, so half the power is taken out of each side and
  the other half counts as uncertainty. The power comes from the owner's
  meter in Home Assistant, else from the fan speed (reference unit).
- Condensation. Water condensing in the core releases heat the temperatures
  do not show. Periods where the cold end of the core is below the dew point
  of the extract air are left out.
- Thermal mass and small differences. Only steady periods count: the same fan
  pair for 30 minutes, then 15-minute windows with at least 8 K between
  extract and outdoor air and temperatures that hold still.
- Bypass, fireplace mode, stopped fans and frost are left out.

One window is noisy. The duct ratio the balance uses is the weighted median
of the recent windows, and only once at least two nights agree.
"""
from __future__ import annotations

import math
from datetime import datetime

from advanced_control import AIR_HEAT_CAPACITY, DUCT_RATIO_RANGE

SETTLE_SECONDS = 1800.0
WINDOW_SECONDS = 900.0
MIN_WINDOW_SAMPLES = 60
# A reading may be missing this long before the steady period starts over.
MAX_GAP_SECONDS = 120.0
MIN_DELTA_T = 8.0
# Largest change (max - min) within a window before it counts as unsteady.
MAX_RANGE = {"t1": 0.8, "t2": 0.8, "t3": 0.5, "t4": 0.8}
MIN_EXHAUST_C = 1.0
CONDENSATION_MARGIN = 0.5
MIN_FAN_RPM = 300.0
FAN_HEAT_SHARE = 0.5
# Fan power on the reference HCH5 (both fans alike): P = c x rpm^2.42, fitted
# from its power meter at levels 2 to 6 with 1.3 W standby draw.
FAN_POWER_COEFFICIENT = 2.5e-7
FAN_POWER_EXPONENT = 2.42
IDLE_POWER_DEFAULT_W = 1.5
WINDOWS_KEPT = 60
MAX_AGE_SECONDS = 45 * 86400
CONFIDENT_WINDOWS = 8
CONFIDENT_NIGHTS = 2
CONFIDENT_SPREAD = 0.06
# The ratio in use follows the estimate in steps, and not for small wobbles.
ADOPT_DEADBAND = 0.015
ADOPT_STEP = 0.05


def dew_point(temperature: float, relative_humidity: float) -> float | None:
    """Dew point in C (Magnus formula), or None for impossible input."""
    if not -40.0 <= temperature <= 60.0 or not 0.0 < relative_humidity <= 100.0:
        return None
    gamma = math.log(relative_humidity / 100.0) + 17.67 * temperature / (243.5 + temperature)
    return 243.5 * gamma / (17.67 - gamma)


def fan_powers(supply_rpm: float, extract_rpm: float, power_w: float | None,
               idle_w: float | None = None) -> dict[str, object]:
    """Electrical power of each fan: the unit's meter split by speed, else the model."""
    model_supply = FAN_POWER_COEFFICIENT * max(0.0, supply_rpm) ** FAN_POWER_EXPONENT
    model_extract = FAN_POWER_COEFFICIENT * max(0.0, extract_rpm) ** FAN_POWER_EXPONENT
    if power_w is None or model_supply + model_extract <= 0:
        return {"supply": model_supply, "extract": model_extract, "source": "model"}
    fans = max(0.0, power_w - (IDLE_POWER_DEFAULT_W if idle_w is None else idle_w))
    share = model_supply / (model_supply + model_extract)
    return {"supply": fans * share, "extract": fans * (1.0 - share), "source": "meter"}


def balance_from_temperatures(
    t1: float, t2: float, t3: float, t4: float, *,
    supply_rpm: float, extract_rpm: float, supply_m3h: float, extract_m3h: float,
    power_w: float | None = None, idle_w: float | None = None,
) -> dict[str, object] | None:
    """Airflow ratio (supply/extract) and duct ratio from one set of temperatures.

    supply_m3h/extract_m3h only size the fan-heat correction, so an estimate
    is good enough.
    """
    supply_rise, extract_drop = t2 - t1, t3 - t4
    if supply_rise <= 0.5 or extract_drop <= 0.5 or supply_rpm <= 0 or extract_rpm <= 0:
        return None
    if supply_m3h <= 0 or extract_m3h <= 0:
        return None
    fans = fan_powers(supply_rpm, extract_rpm, power_w, idle_w)
    heat_supply = FAN_HEAT_SHARE * float(fans["supply"]) / (supply_m3h * AIR_HEAT_CAPACITY / 3600.0)
    heat_extract = FAN_HEAT_SHARE * float(fans["extract"]) / (extract_m3h * AIR_HEAT_CAPACITY / 3600.0)
    if supply_rise - heat_supply <= 0.5:
        return None
    ratio = (extract_drop + heat_extract) / (supply_rise - heat_supply)
    return {
        "airflow_ratio": ratio,
        "duct_ratio": ratio * extract_rpm / supply_rpm,
        # Relative: the other half of the fan heat, on each side.
        "uncertainty": heat_supply / (supply_rise - heat_supply) + heat_extract / (extract_drop + heat_extract),
        "fan_heat_supply_k": heat_supply,
        "fan_heat_extract_k": heat_extract,
        "fan_power_source": fans["source"],
    }


def _weighted_median(values: list[float], weights: list[float]) -> float:
    pairs = sorted(zip(values, weights))
    half = sum(weights) / 2.0
    running = 0.0
    for value, weight in pairs:
        running += weight
        if running >= half:
            return value
    return pairs[-1][0]


def _night(timestamp: float) -> str:
    """Local date of the evening a window belongs to: 22:00 and 04:00 are one night."""
    return datetime.fromtimestamp(timestamp - 12 * 3600).astimezone().strftime("%Y-%m-%d")


def summarize(windows: list[dict], now: float) -> dict[str, object]:
    """Duct ratio from the recent windows: weighted median, spread and confidence."""
    recent = [
        window for window in windows
        if isinstance(window, dict) and now - float(window.get("t", 0)) <= MAX_AGE_SECONDS
    ][-WINDOWS_KEPT:]
    if not recent:
        return {"windows": [], "ratio": None, "spread": None, "count": 0, "nights": 0, "confidence": "none"}
    values = [float(window["duct_ratio"]) for window in recent]
    # Larger temperature differences measure better.
    weights = [min(float(window["delta_t"]), 20.0) ** 2 for window in recent]
    ratio = _weighted_median(values, weights)
    # Mean absolute deviation: unlike the median of deviations it also sees
    # two camps of windows that disagree.
    spread = sum(weight * abs(value - ratio) for value, weight in zip(values, weights)) / sum(weights)
    nights = len({_night(float(window["t"])) for window in recent})
    if len(recent) >= CONFIDENT_WINDOWS and nights >= CONFIDENT_NIGHTS and spread <= CONFIDENT_SPREAD:
        confidence = "ok"
    elif len(recent) >= 3:
        confidence = "low"
    else:
        confidence = "none"
    return {"windows": recent, "ratio": round(ratio, 4), "spread": round(spread, 4),
            "count": len(recent), "nights": nights, "confidence": confidence}


def adopt(in_use: float | None, estimate: float) -> float:
    """Next duct ratio to use: follow the estimate in steps, ignore small wobbles."""
    low, high = DUCT_RATIO_RANGE
    estimate = min(high, max(low, estimate))
    if in_use is None:
        return round(estimate, 4)
    if abs(estimate - in_use) < ADOPT_DEADBAND:
        return in_use
    return round(in_use + max(-ADOPT_STEP, min(ADOPT_STEP, estimate - in_use)), 4)


class HeatBalanceLearner:
    """Collects steady windows from the live readings; no bus access."""

    def __init__(self, idle_power_w: float | None = None) -> None:
        self.pair: tuple[int, int] | None = None
        self.pair_since: float | None = None
        self.last_seen: float | None = None
        self.window: dict[str, object] | None = None
        self.idle_power_w = idle_power_w
        self.last_result: dict[str, object] | None = None
        self.status: dict[str, object] = {"state": "waiting", "reason": "Starter"}

    def _restart(self, reason: str, state: str = "waiting") -> None:
        self.pair, self.pair_since, self.window = None, None, None
        self.status = {"state": state, "reason": reason}

    def observe(self, sample: dict[str, object], now: float) -> dict[str, object] | None:
        """Feed one reading. Returns the verdict on a window when one completes."""
        supply_rpm = _number(sample.get("supply_rpm")) or 0.0
        extract_rpm = _number(sample.get("extract_rpm")) or 0.0
        power = _number(sample.get("power_w"))
        stopped = supply_rpm < MIN_FAN_RPM and extract_rpm < MIN_FAN_RPM
        if stopped and power is not None and power < 20.0:
            # Standby draw of the unit's electronics, for the fan-heat split.
            self.idle_power_w = power if self.idle_power_w is None else 0.98 * self.idle_power_w + 0.02 * power
        blocked = sample.get("blocked")
        if blocked:
            self._restart(str(blocked))
            return None
        if sample.get("t2") is None:
            self._restart("Ingen T2-føler: sæt en 1-Wire-føler i indblæsningen før eftervarmen og giv den rollen T2", "off")
            return None
        if supply_rpm < MIN_FAN_RPM or extract_rpm < MIN_FAN_RPM:
            self._restart("Ventilatorerne står stille")
            return None
        if sample.get("bypass"):
            self._restart("Bypass er åben")
            return None
        values = {key: _number(sample.get(key)) for key in ("t1", "t2", "t3", "t4")}
        if any(value is None for value in values.values()):
            if self.last_seen is not None and now - self.last_seen > MAX_GAP_SECONDS:
                self._restart("Mangler T1, T3 eller T4")
            return None
        self.last_seen = now
        try:
            pair = (int(sample["supply_percent"]), int(sample["extract_percent"]))
        except (KeyError, TypeError, ValueError):
            self._restart("Ukendt ventilatorprocent")
            return None
        if pair != self.pair:
            self.pair, self.pair_since, self.window = pair, now, None
        settled = now - (self.pair_since if self.pair_since is not None else now)
        delta_t = values["t3"] - values["t1"]
        if settled < SETTLE_SECONDS:
            self.status = {"state": "settling", "reason": "Venter på stabil drift efter skift af trin",
                           "remaining_seconds": round(SETTLE_SECONDS - settled), "delta_t": round(delta_t, 1)}
            return None
        window = self.window
        if window is None:
            window = self.window = {"start": now, "count": 0, "sums": {}, "min": {}, "max": {},
                                    "power_sum": 0.0, "power_count": 0, "rh_sum": 0.0, "rh_count": 0}
        window["count"] = int(window["count"]) + 1
        extras = {"supply_rpm": supply_rpm, "extract_rpm": extract_rpm,
                  "supply_m3h": _number(sample.get("supply_m3h")) or 0.0,
                  "extract_m3h": _number(sample.get("extract_m3h")) or 0.0}
        for key, value in {**values, **extras}.items():
            window["sums"][key] = window["sums"].get(key, 0.0) + value
            window["min"][key] = min(window["min"].get(key, value), value)
            window["max"][key] = max(window["max"].get(key, value), value)
        if power is not None:
            window["power_sum"] += power
            window["power_count"] += 1
        rh = _number(sample.get("rh"))
        if rh is not None:
            window["rh_sum"] += rh
            window["rh_count"] += 1
        elapsed = now - float(window["start"])
        self.status = {"state": "measuring", "reason": "Måler varmebalancen",
                       "progress_percent": round(min(100.0, elapsed / WINDOW_SECONDS * 100.0)),
                       "delta_t": round(delta_t, 1)}
        if elapsed < WINDOW_SECONDS:
            return None
        self.window = None
        verdict = self._judge(window, now)
        self.last_result = verdict
        self.status = {"state": "measured" if verdict["accepted"] else "rejected", "reason": verdict["reason"],
                       "delta_t": verdict.get("delta_t")}
        return verdict

    def _judge(self, window: dict, now: float) -> dict[str, object]:
        count = int(window["count"])
        mean = {key: total / count for key, total in window["sums"].items()}
        delta_t = mean["t3"] - mean["t1"]
        verdict: dict[str, object] = {"t": round(now), "accepted": False, "delta_t": round(delta_t, 2),
                                      "supply_percent": self.pair[0] if self.pair else None,
                                      "extract_percent": self.pair[1] if self.pair else None}
        if count < MIN_WINDOW_SAMPLES:
            return {**verdict, "reason": "For få målinger i perioden"}
        if delta_t < MIN_DELTA_T:
            return {**verdict, "reason": f"For lille forskel mellem inde og ude ({delta_t:.1f} K, skal være mindst {MIN_DELTA_T:.0f} K)"}
        for key, limit in MAX_RANGE.items():
            if window["max"][key] - window["min"][key] > limit:
                return {**verdict, "reason": "Temperaturerne ændrede sig for meget undervejs"}
        if mean["t4"] < MIN_EXHAUST_C:
            return {**verdict, "reason": "Frostrisiko i veksleren"}
        if not window["rh_count"]:
            return {**verdict, "reason": "Ingen luftfugtighed: kondens i veksleren kan ikke udelukkes"}
        dew = dew_point(mean["t3"], window["rh_sum"] / window["rh_count"])
        if dew is None:
            return {**verdict, "reason": "Ugyldig luftfugtighed"}
        cold_end = (mean["t1"] + mean["t4"]) / 2.0
        if dew > cold_end - CONDENSATION_MARGIN:
            return {**verdict, "reason": f"Kondens i veksleren (dugpunkt {dew:.1f} °C, kold ende {cold_end:.1f} °C)"}
        power = window["power_sum"] / window["power_count"] if window["power_count"] >= count / 2 else None
        result = balance_from_temperatures(
            mean["t1"], mean["t2"], mean["t3"], mean["t4"],
            supply_rpm=mean["supply_rpm"], extract_rpm=mean["extract_rpm"],
            supply_m3h=mean["supply_m3h"], extract_m3h=mean["extract_m3h"],
            power_w=power, idle_w=self.idle_power_w,
        )
        if result is None or not 0.6 <= float(result["duct_ratio"]) <= 1.6:
            return {**verdict, "reason": "Urimeligt resultat: tjek T1–T4 og T2-føleren"}
        excess = (1.0 / float(result["airflow_ratio"]) - 1.0) * 100.0
        return {
            **verdict, "accepted": True,
            "reason": f"Målt: udsugning {excess:+.1f} % i forhold til indblæsning ved {self.pair[0]}/{self.pair[1]} %",
            "duct_ratio": round(float(result["duct_ratio"]), 4),
            "airflow_ratio": round(float(result["airflow_ratio"]), 4),
            "uncertainty": round(float(result["uncertainty"]), 3),
            "power": result["fan_power_source"],
        }


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def window_record(verdict: dict[str, object]) -> dict[str, object]:
    """The part of an accepted window that is kept."""
    keys = ("t", "duct_ratio", "airflow_ratio", "delta_t", "supply_percent", "extract_percent", "uncertainty", "power")
    return {key: verdict.get(key) for key in keys}
