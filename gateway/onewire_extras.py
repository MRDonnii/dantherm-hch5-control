#!/usr/bin/env python3
"""Extra DS18B20 sensors on the Pi's 1-Wire bus, read in the background.

The separate 1-Wire service keeps owning the afterheat water flow and return
sensors. Any further DS18B20 on the same bus is read here and given a role
chosen in the WebUI: T2 in the supply duct before the afterheat coil, the loft
space, or a free name. Nothing here talks to RS485.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request
from pathlib import Path

LOG = logging.getLogger("passivelink-onewire-extras")

W1_DEVICES = Path("/sys/bus/w1/devices")
ONEWIRE_SERVICE_URL = "http://127.0.0.1:4197/temperatures"
READ_INTERVAL_SECONDS = 15.0
# A reading older than this is treated as missing.
FRESH_SECONDS = 90.0
ROLES = ("none", "t2", "attic", "other")
ROLE_LABELS = {"t2": "T2 · før eftervarme", "attic": "Loftrum", "other": "Føler"}


def read_ds18b20(sensor_id: str, devices: Path = W1_DEVICES) -> float | None:
    """Temperature in °C from the kernel w1_therm driver, or None."""
    try:
        lines = (devices / sensor_id / "w1_slave").read_text(encoding="ascii").splitlines()
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return None
    if len(lines) < 2 or not lines[0].strip().endswith("YES"):
        return None
    position = lines[1].find("t=")
    if position < 0:
        return None
    try:
        value = int(lines[1][position + 2:]) / 1000.0
    except ValueError:
        return None
    # 85.0 is the power-on value before a conversion; outside the range is a fault.
    if value == 85.0 or not -55.0 < value < 125.0:
        return None
    return round(value, 2)


def clean_roles(value: object) -> dict[str, dict[str, str]]:
    """Validate the WebUI role map: {sensor_id: {"role": ..., "name": ...}}."""
    if value in (None, ""):
        return {}
    if not isinstance(value, dict) or len(value) > 16:
        raise ValueError("onewire_roles skal være et objekt med højst 16 følere")
    cleaned: dict[str, dict[str, str]] = {}
    t2_seen = False
    for raw_id, entry in value.items():
        sensor_id = str(raw_id).strip().lower()
        if not sensor_id.startswith("28-") or not 6 <= len(sensor_id) <= 20 or not all(c in "0123456789abcdef-" for c in sensor_id):
            raise ValueError(f"Ugyldigt føler-id: {raw_id}")
        if not isinstance(entry, dict):
            raise ValueError(f"Føler {sensor_id} skal have role og name")
        role = str(entry.get("role", "none"))
        if role not in ROLES:
            raise ValueError(f"Ugyldig rolle for {sensor_id}")
        if role == "t2":
            if t2_seen:
                raise ValueError("Kun én føler kan være T2")
            t2_seen = True
        name = str(entry.get("name") or "").strip()[:32]
        cleaned[sensor_id] = {"role": role, "name": name}
    return cleaned


class OneWireExtras:
    """Background reader for DS18B20 sensors beyond the water flow/return pair."""

    def __init__(self, roles: callable, *, devices: Path = W1_DEVICES, service_url: str | None = ONEWIRE_SERVICE_URL) -> None:
        self._roles = roles
        self.devices = devices
        self.service_url = service_url
        self.lock = threading.Lock()
        self.readings: dict[str, tuple[float | None, float]] = {}
        self.water_ids: set[str] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _water_sensor_ids(self) -> set[str]:
        """Flow/return sensors owned by the 1-Wire service; left alone here."""
        if not self.service_url:
            return set()
        try:
            with urllib.request.urlopen(self.service_url, timeout=4) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError):
            return self.water_ids
        return {str(payload[key]).lower() for key in ("flow_sensor", "return_sensor") if payload.get(key)}

    def discovered(self) -> list[str]:
        try:
            return sorted(path.name for path in self.devices.glob("28-*") if (path / "w1_slave").exists())
        except OSError:
            return []

    def read_once(self, now: float | None = None) -> None:
        self.water_ids = self._water_sensor_ids()
        now = time.monotonic() if now is None else now
        values = {sensor_id: (read_ds18b20(sensor_id, self.devices), now)
                  for sensor_id in self.discovered() if sensor_id not in self.water_ids}
        with self.lock:
            self.readings = values

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.read_once()
            except Exception as error:  # noqa: BLE001 - never stop the reader
                LOG.warning("1-Wire read failed: %s", error)
            self._stop.wait(READ_INTERVAL_SECONDS)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="onewire-extras", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def sensors(self, now: float | None = None) -> list[dict[str, object]]:
        """Every extra sensor with its role, name and fresh temperature."""
        now = time.monotonic() if now is None else now
        roles = self._roles() or {}
        with self.lock:
            readings = dict(self.readings)
        result = []
        for sensor_id, (value, read_at) in sorted(readings.items()):
            entry = roles.get(sensor_id, {})
            role = entry.get("role", "none")
            fresh = value if now - read_at <= FRESH_SECONDS else None
            result.append({
                "id": sensor_id,
                "temperature": fresh,
                "role": role,
                "name": entry.get("name") or ROLE_LABELS.get(role) or sensor_id,
            })
        return result

    def by_role(self, role: str, now: float | None = None) -> float | None:
        for sensor in self.sensors(now):
            if sensor["role"] == role and sensor["temperature"] is not None:
                return float(sensor["temperature"])
        return None


__all__ = ["OneWireExtras", "ROLES", "clean_roles", "read_ds18b20"]
