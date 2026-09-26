"""Diagnostics and protection built on the controller snapshot.

Fed every few seconds by the controller runtime with the values it already
reports (temperatures, the measured T2, the running level, airflow, the
unit's power draw from Home Assistant). Nothing here writes to the unit; it
only derives states, alarms and energy counters that the WebUI and Home
Assistant show.

- Frost: the exchanger ices up when the exhaust air (T4) nears 0 C. The HCH5
  has its own protection; this warns earlier and shows when it happens.
- Alarms: each condition must hold for a while before it is raised, and
  clears on its own when the condition is gone.
- Fan power (SFP) and filter: specific fan power, W per m3/s, per level.
  The lowest value seen for a level after a filter change is the clean
  reference; a rising ratio means the filter or a grille is clogging.
- Energy: recovered heat, afterheat and the unit's own consumption are
  integrated to kWh totals that survive restarts, plus today's values.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path

LOG = logging.getLogger(__name__)

# Seconds a condition must hold before its alarm is raised.
ALARM_DELAYS = {
    "frost_risk": 300,
    "recovery_low": 1800,
    "recovery_mismatch": 3600,
    "bypass_not_closing": 1200,
    "afterheat_no_lift": 1800,
    "sensor_missing": 300,
    "bus_unhealthy": 120,
    "filter_clogging": 3600,
}
ALARM_TEXT = {
    "frost_risk": "Frostrisiko i veksleren: afkastluften (T4) er nær 0 °C",
    "recovery_low": "Lav varmegenvinding: veksleren kan være snavset eller utæt",
    "recovery_mismatch": "Genvinding målt på indblæsning og udsugning er uenige: mulig utæthed eller følerfejl",
    "bypass_not_closing": "Bypass ser ikke ud til at lukke: indblæsningen følger udeluften",
    "afterheat_no_lift": "Eftervarmen kalder, men luften bliver ikke varmere: ventil, pumpe eller luft i fladen",
    "sensor_missing": "En 1-Wire-føler med en rolle svarer ikke",
    "bus_unhealthy": "Ingen sund RS485-forbindelse til anlægget",
    "filter_clogging": "Ventilatorerne bruger mere strøm end med rent filter: filter eller rist stopper til",
}
ALARM_SEVERITY = {
    "frost_risk": "warning",
    "recovery_low": "warning",
    "recovery_mismatch": "info",
    "bypass_not_closing": "warning",
    "afterheat_no_lift": "warning",
    "sensor_missing": "warning",
    "bus_unhealthy": "critical",
    "filter_clogging": "info",
}
FROST_WATCH_T4 = 3.0
FROST_RISK_T4 = 0.5
# Filter ratio against the clean reference at which the alarm is raised.
FILTER_CLOGGING_RATIO = 1.25
SAVE_EVERY = 300.0
MAX_STEP = 60.0


def _num(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


class Diagnostics:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self.started: dict[str, float] = {}
        self.active: dict[str, float] = {}
        self.energy = {"recovered_kwh": 0.0, "afterheat_kwh": 0.0, "unit_kwh": 0.0}
        self.today = {"date": "", "recovered_kwh": 0.0, "afterheat_kwh": 0.0, "unit_kwh": 0.0}
        # Clean SFP per fan level, learned after each filter change.
        self.sfp_reference: dict[str, float] = {}
        self.sfp_window: dict[str, list[float]] = {}
        self.filter_marker: object = None
        self.last_update: float | None = None
        self.last_save = 0.0
        self.result: dict[str, object] = {}
        self._load()

    # ---- persistence -------------------------------------------------
    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            LOG.warning("Diagnostics state unreadable, starting fresh: %s", error)
            return
        for key in self.energy:
            self.energy[key] = float(saved.get("energy", {}).get(key, 0.0) or 0.0)
        today = saved.get("today", {})
        if isinstance(today, dict):
            self.today.update({k: today[k] for k in self.today if k in today})
        refs = saved.get("sfp_reference", {})
        if isinstance(refs, dict):
            self.sfp_reference = {str(k): float(v) for k, v in refs.items() if _num(v)}
        self.filter_marker = saved.get("filter_marker")

    def save(self) -> None:
        if not self.path:
            return
        payload = {"energy": self.energy, "today": self.today,
                   "sfp_reference": self.sfp_reference, "filter_marker": self.filter_marker}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".diagnostics-", dir=self.path.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            os.replace(tmp, self.path)
        except OSError as error:
            LOG.warning("Unable to save diagnostics state: %s", error)

    def reset_filter_reference(self) -> None:
        self.sfp_reference.clear()
        self.sfp_window.clear()
        self.save()

    # ---- update ------------------------------------------------------
    def update(self, s: dict[str, object], now: float | None = None) -> dict[str, object]:
        now = time.time() if now is None else now
        step = 0.0 if self.last_update is None else min(MAX_STEP, max(0.0, now - self.last_update))
        self.last_update = now

        t1 = _num(s.get("outdoor_temperature"))
        t3 = _num(s.get("extract_temperature"))
        t4 = _num(s.get("exhaust_temperature"))
        t2 = _num(s.get("actual_supply_before_heater_temperature"))
        bypass = s.get("actual_bypass") is True
        supply_recovery = _num(s.get("supply_recovery_percent"))
        extract_recovery = None
        if t1 is not None and t3 is not None and t4 is not None and t3 - t1 >= 3 and not bypass:
            extract_recovery = (t3 - t4) / (t3 - t1) * 100
        power = _num(s.get("unit_power_w"))
        airflow = _num(s.get("supply_airflow_estimate_m3h"))
        level = s.get("effective_level")
        cold = t1 is not None and t3 is not None and t3 - t1 >= 8

        # Frost: T4 near zero with the core in use.
        frost_state = "unknown" if t4 is None else "ok"
        if t4 is not None and not bypass:
            if t4 <= FROST_RISK_T4:
                frost_state = "risk"
            elif t4 <= FROST_WATCH_T4:
                frost_state = "watch"

        # SFP and filter: stable level, fresh power and a known airflow.
        sfp = None
        filter_ratio = None
        # A filter reset shows as the remaining filter life jumping up.
        life = _num(s.get("filter_life_percent"))
        if life is not None:
            previous = _num(self.filter_marker)
            if previous is not None and life - previous >= 20:
                self.sfp_reference.clear()
                self.sfp_window.clear()
            self.filter_marker = life
        if power is not None and airflow and level is not None:
            sfp = power / (airflow / 3600.0)
            key = str(level)
            window = self.sfp_window.setdefault(key, [])
            window.append(sfp)
            del window[:-60]
            if len(window) >= 30:
                average = sum(window) / len(window)
                reference = self.sfp_reference.get(key)
                if reference is None or average < reference:
                    self.sfp_reference[key] = average
                    reference = average
                filter_ratio = average / reference if reference else None

        # Energy: integrate the watts over the step.
        today = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
        if self.today["date"] != today:
            self.today = {"date": today, "recovered_kwh": 0.0, "afterheat_kwh": 0.0, "unit_kwh": 0.0}
        for key, watts in (("recovered_kwh", s.get("recovered_heat_w")),
                           ("afterheat_kwh", s.get("afterheat_power_w")),
                           ("unit_kwh", power)):
            value = _num(watts)
            if value is not None and value > 0 and step:
                kwh = value * step / 3_600_000
                self.energy[key] += kwh
                self.today[key] += kwh

        # Alarm conditions, raised after their delay.
        roles = s.get("onewire_sensors") or []
        missing = any(isinstance(x, dict) and x.get("role") not in (None, "none") and x.get("temperature") is None for x in roles)
        conditions = {
            "frost_risk": frost_state == "risk",
            "recovery_low": cold and supply_recovery is not None and supply_recovery < 60,
            "recovery_mismatch": cold and supply_recovery is not None and extract_recovery is not None
                and abs(supply_recovery - extract_recovery) > 20,
            "bypass_not_closing": cold and s.get("actual_bypass_request") in (False, "off", "OFF", 0)
                and not bypass and t2 is not None and t1 is not None and t3 is not None
                and (t2 - t1) < 0.25 * (t3 - t1),
            "afterheat_no_lift": s.get("actual_afterheat") is True
                and s.get("actual_afterheat_outdoor_lockout") is not True
                and _num(s.get("afterheat_lift")) is not None and _num(s.get("afterheat_lift")) < 0.5,
            "sensor_missing": missing,
            "bus_unhealthy": s.get("rs485_healthy") is False,
            "filter_clogging": filter_ratio is not None and filter_ratio >= FILTER_CLOGGING_RATIO,
        }
        for code, holds in conditions.items():
            if holds:
                self.started.setdefault(code, now)
                if now - self.started[code] >= ALARM_DELAYS[code]:
                    self.active.setdefault(code, now)
            else:
                self.started.pop(code, None)
                self.active.pop(code, None)

        alarms = [
            {"code": code, "severity": ALARM_SEVERITY[code], "text": ALARM_TEXT[code], "since": int(since)}
            for code, since in sorted(self.active.items(), key=lambda item: item[1])
        ]
        worst = "ok"
        for alarm in alarms:
            if alarm["severity"] == "critical" or (alarm["severity"] == "warning" and worst != "critical"):
                worst = alarm["severity"]
            elif worst == "ok":
                worst = "info"
        self.result = {
            "diagnostics_status": worst,
            "diagnostics_alarms": alarms,
            "diagnostics_alarm_count": len(alarms),
            "diagnostics_alarm_text": "; ".join(a["text"] for a in alarms) or "Ingen",
            "frost_state": frost_state,
            "extract_recovery_percent": None if extract_recovery is None else round(max(0.0, min(100.0, extract_recovery)), 1),
            "specific_fan_power": None if sfp is None else round(sfp),
            "filter_power_ratio": None if filter_ratio is None else round(filter_ratio, 2),
            "recovered_energy_kwh": round(self.energy["recovered_kwh"], 3),
            "afterheat_energy_kwh": round(self.energy["afterheat_kwh"], 3),
            "unit_energy_kwh": round(self.energy["unit_kwh"], 3),
            "recovered_energy_today_kwh": round(self.today["recovered_kwh"], 3),
            "afterheat_energy_today_kwh": round(self.today["afterheat_kwh"], 3),
            "unit_energy_today_kwh": round(self.today["unit_kwh"], 3),
            "recovery_factor": (
                round(self.today["recovered_kwh"] / self.today["unit_kwh"], 1)
                if self.today["unit_kwh"] > 0.01 else None
            ),
        }
        if now - self.last_save >= SAVE_EVERY:
            self.last_save = now
            self.save()
        return self.result
