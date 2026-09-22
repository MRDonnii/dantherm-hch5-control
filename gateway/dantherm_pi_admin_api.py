#!/usr/bin/env python3
"""Authenticated, allowlisted privileged actions for HCH5 Control."""
from __future__ import annotations

import hmac
import json
import math
import os
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from diagnostics_report import build_report

TOKEN = os.environ["DANTHERM_REBOOT_TOKEN"]
BIND = os.getenv("DANTHERM_ADMIN_BIND", "127.0.0.1")
PORT = int(os.getenv("DANTHERM_ADMIN_PORT", "4198"))
PROFILE_FILE = Path("/var/lib/dantherm-admin/power-profile")
UPDATE_CHANNEL_FILE = Path("/var/lib/dantherm-admin/update-channel")
FILTER_STATE_FILE = Path("/var/lib/dantherm-hch5-ha/filter-state.json")
APP_DIR = Path("/opt/dantherm-passivelink-webui")
VERSION_FILE = APP_DIR / "VERSION"
BUILD_FILE = APP_DIR / "BUILD"
REPOSITORY = "MRDonnii/dantherm-hch-passivelink-webui"
BETA_REF = "beta/1.1-modern-controller"
USER_AGENT = "HCH5-Control-Updater/1.2"
PROFILES = {"powersave": "powersave", "balanced": "ondemand", "performance": "performance"}
SERVICES = {
    "gateway": os.getenv("DANTHERM_GATEWAY_SERVICE", "dantherm-webui-gateway.service"),
    "onewire": os.getenv("DANTHERM_ONEWIRE_SERVICE", "dantherm-webui-onewire.service"),
}
ADMIN_SERVICE = os.getenv("DANTHERM_ADMIN_SERVICE", "dantherm-webui-admin.service")
REPORT_SERVICES = {**SERVICES, "admin": ADMIN_SERVICE}
DIAGNOSTICS_LOCK = threading.Lock()
UPDATE_LOCK = threading.Lock()
UPDATE_STATE = {
    "running": False,
    "channel": None,
    "started_at": None,
    "finished_at": None,
    "progress": 0,
    "phase": "idle",
    "detail": "Klar",
    "last_error": None,
}
FILTER_INTERVAL_MIN_DAYS = 90
FILTER_INTERVAL_MAX_DAYS = 360


def _set_update_state(**changes) -> None:
    with UPDATE_LOCK:
        UPDATE_STATE.update(changes)


def set_profile(profile):
    governor = PROFILES[profile]
    for path in Path("/sys/devices/system/cpu").glob("cpu[0-9]*/cpufreq/scaling_governor"):
        path.write_text(governor)
    PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_FILE.write_text(profile + "\n")


def _request_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.read(128 * 1024).decode("utf-8", "replace").strip()


def _final_url(url: str) -> str:
    """Resolve a public GitHub redirect without consuming REST API quota."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.geturl()


def _read_text(path: Path, fallback: str = "unknown") -> str:
    try:
        return path.read_text(encoding="utf-8").strip() or fallback
    except OSError:
        return fallback


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def current_version() -> str:
    return _read_text(VERSION_FILE)


def current_build() -> str:
    return _read_text(BUILD_FILE)


def current_update_channel() -> str:
    value = _read_text(UPDATE_CHANNEL_FILE, "stable").lower()
    return value if value in {"stable", "beta"} else "stable"


def set_update_channel(channel: str) -> str:
    if channel not in {"stable", "beta"}:
        raise ValueError("invalid_channel")
    _atomic_write_text(UPDATE_CHANNEL_FILE, channel + "\n")
    return channel


def _read_filter_state() -> dict[str, object]:
    reset_epoch = time.time()
    interval_days = FILTER_INTERVAL_MAX_DAYS
    try:
        saved = json.loads(FILTER_STATE_FILE.read_text(encoding="utf-8"))
        reset_epoch = float(saved.get("reset_epoch", reset_epoch))
        interval_days = int(saved.get("interval_days", interval_days))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    interval_days = max(FILTER_INTERVAL_MIN_DAYS, min(FILTER_INTERVAL_MAX_DAYS, interval_days))
    elapsed = max(0.0, (time.time() - reset_epoch) / 86400.0)
    remaining = max(0, math.ceil(interval_days - elapsed))
    percent = max(0, min(100, round(remaining / interval_days * 100)))
    return {
        "reset_epoch": reset_epoch,
        "interval_days": interval_days,
        "days_remaining": remaining,
        "life_percent": percent,
    }


def _write_filter_state(*, interval_days: int | None = None, reset_now: bool = False) -> dict[str, object]:
    state = _read_filter_state()
    if interval_days is not None:
        interval_days = int(interval_days)
        if not FILTER_INTERVAL_MIN_DAYS <= interval_days <= FILTER_INTERVAL_MAX_DAYS:
            raise ValueError("invalid_filter_interval")
        state["interval_days"] = interval_days
    if reset_now:
        state["reset_epoch"] = time.time()
    payload = {
        "reset_epoch": float(state["reset_epoch"]),
        "interval_days": int(state["interval_days"]),
    }
    _atomic_write_text(FILTER_STATE_FILE, json.dumps(payload, separators=(",", ":")) + "\n")
    return _read_filter_state()


def _schedule_service_restart(service: str, delay: float = 0.7) -> None:
    def restart():
        time.sleep(delay)
        subprocess.run(["systemctl", "restart", service], check=False)
    threading.Thread(target=restart, daemon=True).start()


_UPDATE_INFO_CACHE: dict[str, dict[str, object]] = {}
_UPDATE_INFO_CACHE_AT: dict[str, float] = {}
UPDATE_INFO_CACHE_SECONDS = 300


def update_info(channel: str | None = None) -> dict[str, object]:
    channel = channel or current_update_channel()
    if channel not in {"stable", "beta"}:
        raise ValueError("invalid_channel")
    now = time.monotonic()
    cached = _UPDATE_INFO_CACHE.get(channel)
    cache_age = now - _UPDATE_INFO_CACHE_AT.get(channel, 0.0)
    if cached is not None and cache_age < UPDATE_INFO_CACHE_SECONDS:
        return {**cached, "current_build": current_build(), "update": dict(UPDATE_STATE)}
    try:
        current = current_version()
        installed_build = current_build()
        available_build = None
        if channel == "stable":
            latest_url = _final_url(f"https://github.com/{REPOSITORY}/releases/latest")
            ref = urllib.parse.unquote(urllib.parse.urlparse(latest_url).path.rsplit("/", 1)[-1])
            if not ref or ref == "latest":
                raise ValueError("latest_release_redirect_missing_tag")
            remote_version = ref.lstrip("v")
            published = None
            update_available = current != remote_version
        else:
            ref = BETA_REF
            remote_version = _request_text(f"https://raw.githubusercontent.com/{REPOSITORY}/{BETA_REF}/VERSION")
            available_build = remote_version
            published = None
            update_available = current != remote_version
    except (OSError, ValueError, KeyError, urllib.error.URLError, json.JSONDecodeError) as error:
        # A GitHub rate limit (HTTP 403) or transient network error should not
        # spam the UI with a failure on every poll. Fall back to the last
        # known-good check instead of raising, if one exists.
        if cached is not None:
            return {**cached, "current_build": current_build(), "update": dict(UPDATE_STATE), "check_error": str(error)}
        raise
    result = {
        "ok": True,
        "channel": channel,
        "current_version": current,
        "current_build": installed_build,
        "available_version": remote_version,
        "available_build": available_build,
        "ref": ref,
        "published_at": published,
        "update_available": update_available,
    }
    _UPDATE_INFO_CACHE[channel] = result
    _UPDATE_INFO_CACHE_AT[channel] = now
    return {**result, "update": dict(UPDATE_STATE)}


def _download_tarball(ref: str, destination: Path) -> None:
    request = urllib.request.Request(
        f"https://codeload.github.com/{REPOSITORY}/tar.gz/{urllib.parse.quote(ref, safe='')}",
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=45) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle, length=1024 * 1024)


def _safe_extract(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        roots = {Path(member.name).parts[0] for member in members if member.name and Path(member.name).parts}
        if len(roots) != 1:
            raise RuntimeError("unexpected_archive_layout")
        root = next(iter(roots))
        base = destination.resolve()
        for member in members:
            target = (destination / member.name).resolve()
            if base not in target.parents and target != base:
                raise RuntimeError("unsafe_archive_path")
        tar.extractall(destination)
    return destination / root


def _schedule_admin_restart() -> None:
    unit = f"hch5-control-admin-restart-{int(time.time())}"
    subprocess.run(
        [
            "systemd-run", "--quiet", f"--unit={unit}", "--on-active=2s",
            "/usr/bin/systemctl", "restart", ADMIN_SERVICE,
        ],
        check=False,
        timeout=10,
    )


def _install_update(channel: str) -> None:
    _set_update_state(
        running=True,
        channel=channel,
        started_at=time.time(),
        finished_at=None,
        progress=2,
        phase="starting",
        detail="Forbereder sikker opdatering…",
        last_error=None,
    )
    success = False
    try:
        set_update_channel(channel)
        _set_update_state(progress=7, phase="checking", detail="Kontrollerer kanal og tilgængelig build…")
        info = update_info(channel)
        ref = str(info["ref"])
        build = str(info.get("available_build") or ref)
        _set_update_state(progress=14, phase="preparing", detail="Opretter isoleret staging-område…")
        with tempfile.TemporaryDirectory(prefix="hch5-control-update-") as temporary:
            directory = Path(temporary)
            archive = directory / "source.tar.gz"
            _set_update_state(progress=24, phase="downloading", detail="Downloader kildekode…")
            _download_tarball(ref, archive)
            _set_update_state(progress=38, phase="extracting", detail="Pakker ny build ud…")
            source = _safe_extract(archive, directory / "src")
            updater = source / "update.sh"
            if not updater.is_file():
                raise RuntimeError("updater_missing")
            _set_update_state(progress=50, phase="validating", detail="Validerer updater og eksisterende installation…")
            env = os.environ.copy()
            env["HCH5_UPDATE_BUILD"] = build
            _set_update_state(progress=58, phase="installing", detail="Installerer og kører failsafe-validering…")
            subprocess.run(["bash", str(updater)], cwd=source, check=True, timeout=300, env=env)
            _set_update_state(progress=93, phase="verifying", detail="Bekræfter ny build og services…")
        success = True
        _set_update_state(progress=100, phase="complete", detail="Opdatering installeret. Genindlæser WebUI…")
    except Exception as error:
        _set_update_state(
            phase="failed",
            detail="Opdateringen fejlede og failsafe har bevaret/tilbageført installationen.",
            last_error=f"{type(error).__name__}: {error}",
        )
    finally:
        _set_update_state(running=False, finished_at=time.time())
    if success:
        _schedule_admin_restart()


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        return hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {TOKEN}")

    def do_GET(self):
        if self.path == "/health":
            return self.reply(200, {"ok": True})
        if not self.authorized():
            return self.reply(401, {"error": "unauthorized"})
        if self.path == "/diagnostics":
            if not DIAGNOSTICS_LOCK.acquire(blocking=False):
                return self.reply(429, {"error": "diagnostics_busy"})
            try:
                payload, filename = build_report(REPORT_SERVICES)
            finally:
                DIAGNOSTICS_LOCK.release()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == "/status":
            governor = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor").read_text().strip()
            return self.reply(200, {
                "power_profile": next((p for p, g in PROFILES.items() if g == governor), governor),
                "governor": governor,
                "version": current_version(),
                "build": current_build(),
                "update_channel": current_update_channel(),
                "filter": _read_filter_state(),
                "update": dict(UPDATE_STATE),
            })
        self.reply(404, {"error": "not_found"})

    def do_POST(self):
        if not self.authorized():
            return self.reply(401, {"error": "unauthorized"})
        if self.path == "/reboot":
            action, target = "reboot", None
        elif self.path == "/action":
            try:
                length = min(int(self.headers.get("Content-Length", "0")), 4096)
                data = json.loads(self.rfile.read(length))
                action = data.get("action")
                target = data.get("target")
            except (ValueError, TypeError, json.JSONDecodeError):
                return self.reply(400, {"error": "invalid_json"})
        else:
            return self.reply(404, {"error": "not_found"})

        if action == "power_profile" and target in PROFILES:
            set_profile(target)
            return self.reply(200, {"ok": True, "power_profile": target})
        if action == "restart_service" and target in SERVICES:
            self.reply(202, {"ok": True, "message": "service restart scheduled"})
            _schedule_service_restart(SERVICES[target], 0.5)
            return
        if action == "get_update_channel":
            return self.reply(200, {"ok": True, "channel": current_update_channel()})
        if action == "get_update_status":
            return self.reply(200, {
                "ok": True,
                "channel": current_update_channel(),
                "current_version": current_version(),
                "current_build": current_build(),
                "update": dict(UPDATE_STATE),
            })
        if action == "set_update_channel" and target in {"stable", "beta"}:
            try:
                channel = set_update_channel(str(target))
            except OSError as error:
                return self.reply(500, {"error": f"channel_save_failed: {error}"})
            return self.reply(200, {"ok": True, "channel": channel})
        if action == "get_filter_config":
            return self.reply(200, {"ok": True, "enabled": True, **_read_filter_state()})
        if action == "set_filter_interval":
            try:
                interval = int(target)
                state = _write_filter_state(interval_days=interval)
            except (TypeError, ValueError, OSError) as error:
                return self.reply(400, {"error": f"filter_interval_failed: {error}"})
            self.reply(200, {"ok": True, "enabled": True, **state})
            _schedule_service_restart(SERVICES["gateway"])
            return
        if action == "reset_filter":
            try:
                state = _write_filter_state(reset_now=True)
            except (ValueError, OSError) as error:
                return self.reply(500, {"error": f"filter_reset_failed: {error}"})
            self.reply(200, {"ok": True, "enabled": True, **state})
            _schedule_service_restart(SERVICES["gateway"])
            return
        if action == "check_update":
            channel = str(target) if target in {"stable", "beta"} else current_update_channel()
            try:
                return self.reply(200, update_info(channel))
            except (OSError, ValueError, KeyError, urllib.error.URLError, json.JSONDecodeError) as error:
                return self.reply(503, {"error": f"update_check_failed: {error}"})
        if action == "install_update":
            channel = str(target) if target in {"stable", "beta"} else current_update_channel()
            if UPDATE_STATE["running"]:
                return self.reply(409, {"error": "update_already_running", "update": dict(UPDATE_STATE)})
            try:
                set_update_channel(channel)
            except OSError as error:
                return self.reply(500, {"error": f"channel_save_failed: {error}"})
            self.reply(202, {"ok": True, "message": "update scheduled", "channel": channel})
            threading.Thread(target=_install_update, args=(channel,), daemon=True).start()
            return
        command = {"reboot": ["systemctl", "reboot"], "shutdown": ["systemctl", "poweroff"]}.get(action)
        if command:
            self.reply(202, {"ok": True, "message": f"{action} scheduled"})
            threading.Thread(target=lambda: (time.sleep(1), subprocess.run(command, check=False)), daemon=True).start()
            return
        self.reply(400, {"error": "action_not_allowed"})

    def log_message(self, *args):
        pass


def main() -> None:
    if PROFILE_FILE.exists():
        saved = PROFILE_FILE.read_text().strip()
        if saved in PROFILES:
            try:
                set_profile(saved)
            except OSError:
                pass
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
