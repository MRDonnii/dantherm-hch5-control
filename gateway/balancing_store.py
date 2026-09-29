"""Airflow balancing (indregulering): rooms, valve measurements and saved reports.

The WebUI does the calculation; the Pi keeps the project and a copy of every
report so a technician can print it again later.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from pathlib import Path

ROOM_TYPES = ("living", "bedroom", "office", "kitchen", "bathroom", "toilet", "utility", "hallway", "other")
MAX_ROOMS = 60
MAX_REPORTS = 30
MAX_REPORT_BYTES = 200_000
META_KEYS = ("site", "address", "owner", "technician", "company", "instrument", "notes")


class BalancingError(ValueError):
    pass


def _number(value, low, high, label, *, optional=False):
    if value in (None, ""):
        if optional:
            return None
        raise BalancingError(f"{label} mangler")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise BalancingError(f"{label} skal være et tal") from error
    if not low <= number <= high:
        raise BalancingError(f"{label} skal være {low:g}–{high:g}")
    return round(number, 2)


def _text(value, limit):
    return str(value or "").replace("\r", "").strip()[:limit]


def clean_project(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise BalancingError("Projektet skal være et objekt")
    rooms_in = raw.get("rooms") or []
    if not isinstance(rooms_in, list) or len(rooms_in) > MAX_ROOMS:
        raise BalancingError(f"Højst {MAX_ROOMS} rum")
    rooms = []
    for index, room in enumerate(rooms_in, start=1):
        if not isinstance(room, dict):
            raise BalancingError("Et rum skal være et objekt")
        name = _text(room.get("name"), 60) or f"Rum {index}"
        if room.get("type") not in ROOM_TYPES:
            raise BalancingError(f"{name}: ukendt rumtype")
        rooms.append({
            "id": _text(room.get("id"), 24) or secrets.token_hex(4),
            "name": name,
            "type": room["type"],
            "area": _number(room.get("area"), 0.5, 500, f"{name}: areal"),
            "height": _number(room.get("height"), 1.8, 6, f"{name}: loftshøjde"),
            "supply": room.get("supply") is True,
            "extract": room.get("extract") is True,
            "measured_supply": _number(room.get("measured_supply"), 0, 500, f"{name}: målt indblæsning", optional=True),
            "measured_extract": _number(room.get("measured_extract"), 0, 500, f"{name}: målt udsugning", optional=True),
            "valve_supply": _text(room.get("valve_supply"), 40),
            "valve_extract": _text(room.get("valve_extract"), 40),
            "note": _text(room.get("note"), 120),
        })
    meta_in = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    meta = {key: _text(meta_in.get(key), 2000 if key == "notes" else 120) for key in META_KEYS}
    level = raw.get("measure_level")
    if level not in (None, ""):
        try:
            level = int(level)
        except (TypeError, ValueError) as error:
            raise BalancingError("Måletrin skal være 1–6") from error
        if not 1 <= level <= 6:
            raise BalancingError("Måletrin skal være 1–6")
    else:
        level = None
    return {"rooms": rooms, "meta": meta, "measure_level": level}


class BalancingStore:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            pass
        return {}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False))
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    @staticmethod
    def _summary(report: dict) -> dict:
        return {key: report.get(key) for key in ("id", "created_at", "created_by", "site", "verdict", "level")}

    def state(self) -> dict:
        data = self._load()
        try:
            project = clean_project(data.get("project") or {})
        except BalancingError:
            project = clean_project({})
        return {"project": project, "reports": [self._summary(r) for r in reversed(data.get("reports") or [])]}

    def save_project(self, raw: object, user: str | None = None) -> dict:
        project = clean_project(raw)
        project["updated_at"] = time.time()
        project["updated_by"] = user
        with self.lock:
            data = self._load()
            data["project"] = project
            self._write(data)
        return project

    def add_report(self, raw: object, user: str | None = None) -> dict:
        if not isinstance(raw, dict):
            raise BalancingError("Rapporten skal være et objekt")
        if len(json.dumps(raw, ensure_ascii=False)) > MAX_REPORT_BYTES:
            raise BalancingError("Rapporten er for stor")
        report = dict(raw)
        report.update({
            "id": secrets.token_hex(6),
            "created_at": time.time(),
            "created_by": user,
            "site": _text((raw.get("meta") or {}).get("site") if isinstance(raw.get("meta"), dict) else "", 120),
            "verdict": _text(raw.get("verdict"), 40),
        })
        with self.lock:
            data = self._load()
            data["reports"] = ((data.get("reports") or []) + [report])[-MAX_REPORTS:]
            self._write(data)
        return self._summary(report)

    def get_report(self, report_id: str) -> dict | None:
        return next((r for r in self._load().get("reports") or [] if r.get("id") == report_id), None)

    def delete_report(self, report_id: str) -> bool:
        with self.lock:
            data = self._load()
            before = len(data.get("reports") or [])
            data["reports"] = [r for r in data.get("reports") or [] if r.get("id") != report_id]
            if len(data["reports"]) == before:
                return False
            self._write(data)
        return True
