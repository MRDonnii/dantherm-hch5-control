#!/usr/bin/env python3
"""Authenticated, allowlisted privileged actions for HCH5 Control."""
from __future__ import annotations

import hmac
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from diagnostics_report import build_report

TOKEN = os.environ["DANTHERM_REBOOT_TOKEN"]
BIND = os.getenv("DANTHERM_ADMIN_BIND", "127.0.0.1")
PORT = int(os.getenv("DANTHERM_ADMIN_PORT", "4198"))
PROFILE_FILE = Path("/var/lib/dantherm-admin/power-profile")
VERSION_FILE = Path("/opt/dantherm-passivelink-webui/VERSION")
REPOSITORY = "MRDonnii/dantherm-hch-passivelink-webui"
BETA_REF = "beta/1.1-modern-controller"
USER_AGENT = "HCH5-Control-Updater/1.0"
PROFILES = {"powersave": "powersave", "balanced": "ondemand", "performance": "performance"}
SERVICES = {
    "gateway": os.getenv("DANTHERM_GATEWAY_SERVICE", "dantherm-webui-gateway.service"),
    "onewire": os.getenv("DANTHERM_ONEWIRE_SERVICE", "dantherm-webui-onewire.service"),
}
REPORT_SERVICES = {**SERVICES, "admin": os.getenv("DANTHERM_ADMIN_SERVICE", "dantherm-webui-admin.service")}
DIAGNOSTICS_LOCK = threading.Lock()
UPDATE_LOCK = threading.Lock()
UPDATE_STATE = {"running": False, "channel": None, "started_at": None, "last_error": None}


def set_profile(profile):
    governor = PROFILES[profile]
    for path in Path("/sys/devices/system/cpu").glob("cpu[0-9]*/cpufreq/scaling_governor"):
        path.write_text(governor)
    PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_FILE.write_text(profile + "\n")


def _request_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read(1024 * 1024))


def _request_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.read(128 * 1024).decode("utf-8", "replace").strip()


def current_version() -> str:
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


def update_info(channel: str) -> dict[str, object]:
    if channel not in {"stable", "beta"}:
        raise ValueError("invalid_channel")
    current = current_version()
    if channel == "stable":
        release = _request_json(f"https://api.github.com/repos/{REPOSITORY}/releases/latest")
        ref = str(release["tag_name"])
        remote_version = ref.lstrip("v")
        published = release.get("published_at")
    else:
        ref = BETA_REF
        remote_version = _request_text(f"https://raw.githubusercontent.com/{REPOSITORY}/{BETA_REF}/VERSION")
        branch = _request_json(f"https://api.github.com/repos/{REPOSITORY}/branches/{BETA_REF}")
        published = branch.get("commit", {}).get("commit", {}).get("committer", {}).get("date")
    return {
        "ok": True,
        "channel": channel,
        "current_version": current,
        "available_version": remote_version,
        "ref": ref,
        "published_at": published,
        "update_available": current != remote_version,
        "update": dict(UPDATE_STATE),
    }


def _download_tarball(ref: str, destination: Path) -> None:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPOSITORY}/tarball/{ref}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
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


def _install_update(channel: str) -> None:
    with UPDATE_LOCK:
        UPDATE_STATE.update(running=True, channel=channel, started_at=time.time(), last_error=None)
    try:
        info = update_info(channel)
        ref = str(info["ref"])
        with tempfile.TemporaryDirectory(prefix="hch5-control-update-") as temporary:
            directory = Path(temporary)
            archive = directory / "source.tar.gz"
            _download_tarball(ref, archive)
            source = _safe_extract(archive, directory / "src")
            updater = source / "update.sh"
            if not updater.is_file():
                raise RuntimeError("updater_missing")
            subprocess.run(["bash", str(updater)], cwd=source, check=True, timeout=300)
    except Exception as error:
        UPDATE_STATE["last_error"] = f"{type(error).__name__}: {error}"
    finally:
        UPDATE_STATE["running"] = False


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
            threading.Thread(target=lambda: (time.sleep(.5), subprocess.run(["systemctl", "restart", SERVICES[target]], check=False)), daemon=True).start()
            return
        if action == "check_update" and target in {"stable", "beta"}:
            try:
                return self.reply(200, update_info(target))
            except (OSError, ValueError, KeyError, urllib.error.URLError, json.JSONDecodeError) as error:
                return self.reply(503, {"error": f"update_check_failed: {error}"})
        if action == "install_update" and target in {"stable", "beta"}:
            if UPDATE_STATE["running"]:
                return self.reply(409, {"error": "update_already_running", "update": dict(UPDATE_STATE)})
            self.reply(202, {"ok": True, "message": "update scheduled", "channel": target})
            threading.Thread(target=_install_update, args=(target,), daemon=True).start()
            return
        command = {"reboot": ["systemctl", "reboot"], "shutdown": ["systemctl", "poweroff"]}.get(action)
        if command:
            self.reply(202, {"ok": True, "message": f"{action} scheduled"})
            threading.Thread(target=lambda: (time.sleep(1), subprocess.run(command, check=False)), daemon=True).start()
            return
        self.reply(400, {"error": "action_not_allowed"})

    def log_message(self, *args):
        pass


if PROFILE_FILE.exists():
    saved = PROFILE_FILE.read_text().strip()
    if saved in PROFILES:
        try:
            set_profile(saved)
        except OSError:
            pass
ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()
