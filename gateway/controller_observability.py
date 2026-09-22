#!/usr/bin/env python3
"""Observability helpers for HCH5 Control.

This module is deliberately read-only with respect to the ventilation bus. It
adds controller decision history, data-health diagnostics and comfort status by
wrapping ControllerRuntime.snapshot(). No Modbus write path is introduced here.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any


class ControllerObservability:
    def __init__(self, runtime, *, path: str | Path | None = None, max_events: int = 200) -> None:
        self.runtime = runtime
        self.path = Path(path or os.getenv(
            "DANTHERM_DECISION_LOG",
            "/var/lib/dantherm-hch5-ha/decision-log.jsonl",
        ))
        self.events: deque[dict[str, Any]] = deque(maxlen=max(20, int(max_events)))
        self.lock = threading.RLock()
        self._last_signature: tuple[Any, ...] | None = None
        self._load_tail()

    def _load_tail(self) -> None:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()[-self.events.maxlen:]
        except OSError:
            return
        for line in lines:
            try:
                item = json.loads(line)
            except (TypeError, ValueError):
                continue
            if isinstance(item, dict):
                self.events.append(item)

    def _append_disk(self, event: dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Keep the persistent file bounded on long-running installations.
            if self.path.exists() and self.path.stat().st_size > 1_500_000:
                tail = list(self.events)[-100:]
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(
                    "".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n" for item in tail),
                    encoding="utf-8",
                )
                os.replace(tmp, self.path)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError:
            # Observability must never be able to interrupt ventilation control.
            pass

    @staticmethod
    def _number(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _data_health(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        gateway = self.runtime.gateway_state
        age = self._number(gateway.get("bus_last_frame_age"))
        if age is None:
            master_age = self.runtime.master.bus_age()
            age = float(master_age) if master_age is not None else None
        bus_fresh = bool(gateway.get("bus_traffic") is True and age is not None and age <= 10.0)

        local = {
            "rh": self.runtime._first(gateway, "humidity", "relative_humidity"),
            "co2": self.runtime._first(gateway, "co2"),
            "outdoor": self.runtime._first(gateway, "outdoor_temp", "outdoor_temperature"),
            "room": self.runtime._first(gateway, "room_temp", "hrc2_t5_temperature", "room_temperature", "extract_temp"),
            "supply": self.runtime._first(gateway, "heating_coil_after_temperature", "supply_temp"),
        }
        sensors = {
            key: {
                "available": value is not None,
                "fresh": bool(value is not None and bus_fresh),
                "value": value,
                "source": "hch5",
            }
            for key, value in local.items()
        }
        smart_online = bool(snapshot.get("smart_inputs_online"))
        if smart_online:
            sensors["ha_rooms"] = {
                "available": True,
                "fresh": True,
                "value": len(snapshot.get("smart_ha_rooms") or {}),
                "source": "home_assistant",
            }
        else:
            sensors["ha_rooms"] = {
                "available": bool(snapshot.get("smart_ha_rooms")),
                "fresh": False,
                "value": len(snapshot.get("smart_ha_rooms") or {}),
                "source": "home_assistant",
            }

        required = [sensors["rh"], sensors["outdoor"], sensors["room"]]
        if not bus_fresh:
            overall = "stale"
        elif all(item["available"] for item in required):
            overall = "healthy"
        else:
            overall = "degraded"
        return {
            "state": overall,
            "bus_fresh": bus_fresh,
            "bus_age_seconds": round(age, 1) if age is not None else None,
            "sensors": sensors,
        }

    def _comfort(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        supply = self._number(snapshot.get("actual_supply_air_temperature"))
        room = self._number((snapshot.get("measurements") or {}).get("room"))
        outdoor = self._number((snapshot.get("measurements") or {}).get("outdoor"))
        if supply is None:
            state = "unknown"
            reason = "Ingen gyldig indblæsningstemperatur"
        elif supply < 15.0:
            state = "cold"
            reason = "Indblæsningen er kølig"
        elif supply > 26.0:
            state = "warm"
            reason = "Indblæsningen er varm"
        else:
            state = "comfortable"
            reason = "Indblæsning inden for komfortområde"
        return {
            "state": state,
            "reason": reason,
            "supply_temperature": supply,
            "room_temperature": room,
            "outdoor_temperature": outdoor,
            "diagnostic_only": True,
        }

    @staticmethod
    def _signature(snapshot: dict[str, Any]) -> tuple[Any, ...]:
        return (
            snapshot.get("active_master"),
            snapshot.get("effective_source"),
            snapshot.get("effective_level"),
            snapshot.get("effective_bypass"),
            snapshot.get("cooling_state"),
            bool(snapshot.get("quick_boost_active")),
            bool(snapshot.get("vacation_active")),
            bool(snapshot.get("night_active")),
            bool(snapshot.get("schedule_active")),
            bool(snapshot.get("fireplace")),
            snapshot.get("smart_controlling_room"),
            snapshot.get("smart_controlling_metric"),
        )

    def _record_transition(self, snapshot: dict[str, Any]) -> None:
        signature = self._signature(snapshot)
        if signature == self._last_signature:
            return
        self._last_signature = signature
        event = {
            "timestamp": time.time(),
            "master": snapshot.get("active_master"),
            "source": snapshot.get("effective_source"),
            "level": snapshot.get("effective_level"),
            "reason": snapshot.get("effective_reason"),
            "bypass": snapshot.get("effective_bypass"),
            "cooling_state": snapshot.get("cooling_state"),
            "quick_boost": bool(snapshot.get("quick_boost_active")),
            "vacation": bool(snapshot.get("vacation_active")),
            "night": bool(snapshot.get("night_active")),
            "schedule": bool(snapshot.get("schedule_active")),
            "fireplace": bool(snapshot.get("fireplace")),
            "controlling_room": snapshot.get("smart_controlling_room"),
            "controlling_metric": snapshot.get("smart_controlling_metric"),
        }
        with self.lock:
            self.events.append(event)
            self._append_disk(event)

    def augment(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        self._record_transition(snapshot)
        with self.lock:
            log = list(self.events)
        snapshot["data_health"] = self._data_health(snapshot)
        snapshot["comfort_guard"] = self._comfort(snapshot)
        snapshot["decision_log"] = log
        snapshot["decision_log_size"] = len(log)
        return snapshot


def install_controller_observability(runtime) -> ControllerObservability:
    """Wrap a ControllerRuntime instance without changing control semantics."""
    existing = getattr(runtime, "_hch_observability", None)
    if existing is not None:
        return existing

    observer = ControllerObservability(runtime)
    original_snapshot = runtime.snapshot

    def snapshot_with_observability():
        return observer.augment(original_snapshot())

    runtime.snapshot = snapshot_with_observability
    runtime._hch_observability = observer
    return observer


__all__ = ["ControllerObservability", "install_controller_observability"]
