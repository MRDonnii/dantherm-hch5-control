#!/usr/bin/env python3
"""Read-only PassiveLink dashboard, asset server and bounded history store."""
from __future__ import annotations
import hmac, importlib.util, json, logging, os, platform, shutil, socket, sqlite3, subprocess, threading, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
try:
    from webui_auth import AuthManager
except ModuleNotFoundError:
    _auth_spec=importlib.util.spec_from_file_location("webui_auth",Path(__file__).with_name("webui_auth.py")); _auth_module=importlib.util.module_from_spec(_auth_spec); _auth_spec.loader.exec_module(_auth_module); AuthManager=_auth_module.AuthManager
LOGGER = logging.getLogger("passivelink-dashboard")
ASSET_TYPES = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8"}
RANGES = {"1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800, "30d": 2592000}
HISTORY_FIELDS = ("outdoor_temp", "supply_temp", "extract_temp", "exhaust_temp", "hrc2_t5_temperature", "heating_coil_after_temperature", "heating_coil_frost_temperature", "flow_temperature", "return_temperature", "co2", "fan_supply_rpm", "fan_extract_rpm", "fan_supply_percent", "fan_extract_percent", "heat_recovery_efficiency", "system_cpu_usage_percent", "pi_cpu_temperature", "system_memory_used_percent", "system_load_1m")

class HistoryStore:
    """Bounded sample history. Optional: any failure disables it without
    ever taking down the controller, RS485, WebUI or auth."""
    def __init__(self, path: str | Path, retention_days: int = 30, sample_seconds: int = 60):
        self.path, self.retention_seconds = Path(path), max(1, retention_days) * 86400
        self.sample_seconds, self.lock, self.last_sample = max(10, sample_seconds), threading.Lock(), 0.0
        self.available, self.error = False, None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as db:
                columns = ",".join(f'"{field}" REAL' for field in HISTORY_FIELDS)
                db.execute(f"CREATE TABLE IF NOT EXISTS samples (ts INTEGER PRIMARY KEY,{columns})")
                existing = {row[1] for row in db.execute("PRAGMA table_info(samples)")}
                for field in HISTORY_FIELDS:
                    if field not in existing: db.execute(f'ALTER TABLE samples ADD COLUMN "{field}" REAL')
            self.available = True
        except (OSError, sqlite3.Error) as error:
            self.error = str(error)
            LOGGER.warning("History disabled: %s", error)
    def _connect(self): return sqlite3.connect(self.path, timeout=3)
    def record(self, state: dict[str, object], now: float | None = None) -> None:
        if not self.available: return
        now = now or time.time()
        if now - self.last_sample < self.sample_seconds: return
        values = []
        for field in HISTORY_FIELDS:
            try: value = float(state[field])
            except (KeyError, TypeError, ValueError): value = None
            if field == "heat_recovery_efficiency" and value is not None and not 0 <= value <= 100: value = None
            values.append(value)
        timestamp = int(now); placeholders = ",".join("?" for _ in range(len(HISTORY_FIELDS) + 1)); columns = ",".join(["ts", *(f'"{field}"' for field in HISTORY_FIELDS)])
        try:
            with self.lock, self._connect() as db:
                db.execute(f"INSERT OR REPLACE INTO samples ({columns}) VALUES ({placeholders})", [timestamp, *values])
                db.execute("DELETE FROM samples WHERE ts < ?", (timestamp - self.retention_seconds,))
            self.last_sample = now
        except (OSError, sqlite3.Error) as error:
            self.available, self.error = False, str(error)
            LOGGER.warning("History write failed, disabling: %s", error)
    def query(self, range_name: str) -> list[dict[str, object]]:
        if not self.available: return []
        since = int(time.time()) - RANGES.get(range_name, RANGES["24h"])
        try:
            with self.lock, self._connect() as db:
                db.row_factory = sqlite3.Row; rows = db.execute("SELECT * FROM samples WHERE ts >= ? ORDER BY ts", (since,)).fetchall()
        except (OSError, sqlite3.Error) as error:
            self.available, self.error = False, str(error)
            LOGGER.warning("History read failed, disabling: %s", error)
            return []
        stride = max(1, len(rows) // 720)
        return [dict(row) for row in rows[::stride]]

class DashboardHttpServer:
    """Serve the UI without exposing any write/control endpoint."""
    def __init__(self, host: str, port: int, state: dict[str, object], device_name: str, preheater_url: str | None, *, web_root: str | Path | None = None, history_path: str | Path = "/var/lib/dantherm-hch5-ha/history.sqlite3"):
        self.host, self.port, self.state, self.device_name, self.preheater_url = host, port, state, device_name, preheater_url
        self.web_root = Path(web_root or Path(__file__).with_name("webui")).resolve(); self.history = HistoryStore(history_path); self.server = None; self.thread = None
        self._preheater_cache = {}; self._preheater_last_fetch = 0.0; self._preheater_lock = threading.Lock()
        self._system_cache = {}; self._system_last_fetch = 0.0; self._cpu_sample = None
        self.auth = AuthManager(os.getenv("DANTHERM_WEBUI_AUTH_FILE","/var/lib/dantherm-hch5-ha/webui-auth.json")); self.admin_token = os.getenv("DANTHERM_REBOOT_TOKEN"); self.admin_url=os.getenv("DANTHERM_ADMIN_URL","http://127.0.0.1:4198")
        self.history_thread = None; self.history_stop = threading.Event()
    def _fetch_preheater(self) -> dict[str, object]:
        if not self.preheater_url: return {}
        with self._preheater_lock:
            now = time.monotonic()
            if self._preheater_cache and now - self._preheater_last_fetch < 10: return dict(self._preheater_cache)
            try:
                with urllib.request.urlopen(self.preheater_url, timeout=4) as response: payload = json.loads(response.read().decode("utf-8"))
            except (OSError, ValueError, urllib.error.URLError):
                payload = {**self._preheater_cache, "preheater_diagnostics_reachable": False}
                self._preheater_cache = payload; self._preheater_last_fetch = now; return dict(payload)
            if not isinstance(payload, dict): return {"preheater_diagnostics_reachable": False}
            payload["onewire_available"] = payload.pop("available", None)
            payload["preheater_diagnostics_reachable"] = True; self._preheater_cache = dict(payload); self._preheater_last_fetch = now; return payload
    def snapshot(self) -> dict[str, object]:
        merged = dict(self.state); merged.update(self._fetch_preheater()); merged.update(self._system_snapshot())
        age = merged.get("bus_last_frame_age")
        merged["available"] = merged.get("bus_traffic") is True and isinstance(age, (int, float)) and age <= 5
        merged["heat_recovery_efficiency_raw"] = merged.get("heat_recovery_efficiency")
        try:
            outdoor, extract, exhaust = (float(merged[key]) for key in ("outdoor_temp", "extract_temp", "exhaust_temp"))
            span = extract - outdoor
            recovery = (extract - exhaust) / span * 100 if abs(span) >= 0.5 and not merged.get("bypass_active") else None
            merged["heat_recovery_efficiency"] = round(recovery, 1) if recovery is not None and 0 <= recovery <= 105 else None
        except (KeyError, TypeError, ValueError):
            merged["heat_recovery_efficiency"] = None
        if merged.get("pi_cpu_temperature") is None: merged["pi_cpu_temperature"] = merged.get("system_cpu_temperature")
        self.history.record(merged); return merged
    @staticmethod
    def _read(path: str) -> str | None:
        try: return Path(path).read_text(encoding="utf-8").rstrip("\x00\n ") or None
        except OSError: return None
    @staticmethod
    def _run(*args: str) -> str | None:
        try: return subprocess.run(list(args), capture_output=True, text=True, timeout=2, check=True).stdout.strip() or None
        except (OSError, subprocess.SubprocessError): return None
    def _system_snapshot(self) -> dict[str, object]:
        now = time.monotonic()
        if self._system_cache and now - self._system_last_fetch < 10: return dict(self._system_cache)
        data: dict[str, object] = {"system_hostname": socket.gethostname(), "system_os": platform.freedesktop_os_release().get("PRETTY_NAME"), "system_architecture": platform.machine(), "system_time": time.strftime("%Y-%m-%d %H:%M:%S %Z"), "system_timezone": self._read("/etc/timezone"), "system_cpu_frequency_mhz": None, "system_cpu_usage_percent": None, "system_kernel": platform.release(), "system_python_version": platform.python_version(), "system_model": self._read("/proc/device-tree/model"), "system_hch5_version": self._read(str(Path(__file__).resolve().parent / "VERSION")) or self._read(str(Path(__file__).resolve().parent.parent / "VERSION"))}
        try: data["system_cpu_frequency_mhz"] = round(int(self._read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq") or 0) / 1000)
        except ValueError: pass
        try:
            fields = [int(value) for value in (self._read("/proc/stat") or "").splitlines()[0].split()[1:]]; total, idle = sum(fields), fields[3] + fields[4]
            if self._cpu_sample:
                total_delta, idle_delta = total - self._cpu_sample[0], idle - self._cpu_sample[1]
                if total_delta > 0: data["system_cpu_usage_percent"] = round((1 - idle_delta / total_delta) * 100, 1)
            self._cpu_sample = (total, idle)
        except (ValueError, IndexError): pass
        try:
            loads = os.getloadavg(); data.update({"system_load_1m": round(loads[0], 2), "system_load_5m": round(loads[1], 2), "system_load_15m": round(loads[2], 2), "system_cpu_count": os.cpu_count()})
        except OSError: pass
        try:
            uptime = float((self._read("/proc/uptime") or "").split()[0]); data["system_uptime_seconds"] = int(uptime); data["system_boot_time"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - uptime))
        except (ValueError, IndexError): pass
        try: data["system_cpu_temperature"] = round(int(self._read("/sys/class/thermal/thermal_zone0/temp") or "") / 1000, 1)
        except ValueError: data["system_cpu_temperature"] = None
        mem = {}
        try:
            for line in (self._read("/proc/meminfo") or "").splitlines():
                key, _, value = line.partition(":"); mem[key] = int(value.strip().split()[0])
            data["system_memory_total_bytes"] = mem.get("MemTotal", 0) * 1024
            data["system_memory_used_bytes"] = (mem.get("MemTotal", 0) - mem.get("MemAvailable", 0)) * 1024
            data["system_memory_used_percent"] = round(data["system_memory_used_bytes"] / data["system_memory_total_bytes"] * 100, 1) if data["system_memory_total_bytes"] else None
            data["system_swap_used_percent"] = round((mem.get("SwapTotal", 0) - mem.get("SwapFree", 0)) / mem["SwapTotal"] * 100, 1) if mem.get("SwapTotal") else 0
        except (ValueError, IndexError): data["system_swap_used_percent"] = None
        try:
            usage = shutil.disk_usage("/"); data["system_root_total_gb"] = round(usage.total / 1073741824, 1); data["system_root_used_gb"] = round(usage.used / 1073741824, 1); data["system_root_free_gb"] = round(usage.free / 1073741824, 1); data["system_root_used_percent"] = round(usage.used / usage.total * 100, 1)
        except OSError: pass
        root = next((line.split() for line in (self._read("/proc/mounts") or "").splitlines() if len(line.split()) > 3 and line.split()[1] == "/"), None)
        if root: data.update({"system_root_source": root[0], "system_rootfs_type": root[2], "system_root_read_only": "ro" in root[3].split(",")})
        route_text = self._run("/usr/sbin/ip", "-j", "route", "show", "default") or self._run("/usr/bin/ip", "-j", "route", "show", "default")
        try: route = json.loads(route_text or "[]")[0]
        except (ValueError, IndexError): route = {}
        interface = route.get("dev"); data["network_interface"] = interface; data["network_gateway"] = route.get("gateway"); data["network_default_route"] = bool(route)
        if interface and all(ch.isalnum() or ch in "_.-" for ch in interface):
            addr_text = self._run("/usr/sbin/ip", "-j", "address", "show", "dev", interface) or self._run("/usr/bin/ip", "-j", "address", "show", "dev", interface)
            try: link = json.loads(addr_text or "[]")[0]
            except (ValueError, IndexError): link = {}
            ipv4 = next((item for item in link.get("addr_info", []) if item.get("family") == "inet"), {})
            base = f"/sys/class/net/{interface}"
            data.update({"network_link_status": link.get("operstate"), "network_mac": link.get("address"), "network_ipv4": ipv4.get("local"), "network_prefix": ipv4.get("prefixlen"), "network_link_speed_mbps": self._read(f"{base}/speed"), "network_rx_bytes": self._read(f"{base}/statistics/rx_bytes"), "network_tx_bytes": self._read(f"{base}/statistics/tx_bytes"), "network_rx_errors": self._read(f"{base}/statistics/rx_errors"), "network_tx_errors": self._read(f"{base}/statistics/tx_errors")})
        resolv = self._read("/etc/resolv.conf") or ""; data["network_dns"] = ", ".join(line.split()[1] for line in resolv.splitlines() if line.startswith("nameserver ")) or None
        stack = "unknown"
        for service, label in (("NetworkManager", "NetworkManager"), ("systemd-networkd", "systemd-networkd"), ("dhcpcd", "dhcpcd"), ("networking", "ifupdown")):
            if self._run("/usr/bin/systemctl", "is-active", service) == "active": stack = label; break
        data["network_stack"] = stack
        onewire_service = os.getenv("DANTHERM_ONEWIRE_SERVICE")
        if not onewire_service:
            candidates = ("dantherm-passivelink-onewire.service", "dantherm-webui-onewire.service")
            onewire_service = next((name for name in candidates if self._run("/usr/bin/systemctl", "is-active", name) == "active"), candidates[0])
        for service, prefix in ((os.getenv("DANTHERM_GATEWAY_SERVICE","dantherm-webui-gateway.service"), "gateway"), (onewire_service, "onewire"), (os.getenv("DANTHERM_ADMIN_SERVICE","dantherm-webui-admin.service"), "admin"), ("ssh.service", "ssh")):
            output = self._run("/usr/bin/systemctl", "show", service, "-p", "ActiveState", "-p", "SubState", "-p", "MainPID", "-p", "NRestarts", "-p", "MemoryCurrent") or ""
            values = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
            for key, value in values.items(): data[f"service_{prefix}_{key.lower()}"] = value
        try:
            with socket.create_connection(("127.0.0.1", 22), timeout=.3): data["diagnostic_ssh_port_listening"] = True
        except OSError: data["diagnostic_ssh_port_listening"] = False
        data["diagnostic_failed_units"] = self._run("/usr/bin/systemctl", "--failed", "--no-legend", "--plain") or "Ingen"
        self._system_cache, self._system_last_fetch = data, now; return dict(data)
    def start(self) -> None:
        dashboard = self
        class Handler(BaseHTTPRequestHandler):
            def _session(self): return dashboard.auth.authenticate_cookie(self.headers.get("Cookie",""))
            def _require_auth(self):
                session=self._session()
                if session is not None: return session
                self.send_response(401); self.send_header("Content-Type","application/json"); self.send_header("Content-Length","0"); self.end_headers(); return None
            def _read_json(self):
                try: return json.loads(self.rfile.read(min(int(self.headers.get("Content-Length","0")),4096)))
                except (ValueError,TypeError,json.JSONDecodeError): return None
            def _csrf(self,session): return session is not None and hmac.compare_digest(self.headers.get("X-CSRF-Token",""),session.get("csrf") or "")
            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path == "/api/auth/status":
                    session=self._session(); self._json({"configured":dashboard.auth.configured(),"enabled":dashboard.auth.enabled(),"authenticated":session is not None,"username":session.get("username") if session else None,"csrf":session.get("csrf") if session else None}); return
                if parsed.path in ("/login","/setup"): self._file(dashboard.web_root / "login.html","text/html; charset=utf-8"); return
                if parsed.path in ("/assets/auth.css","/assets/auth.js"):
                    target=dashboard.web_root/Path(parsed.path).name; self._file(target,ASSET_TYPES.get(target.suffix)); return
                if not dashboard.auth.configured(): self.send_response(302); self.send_header("Location","/setup"); self.end_headers(); return
                if self._session() is None and dashboard.auth.enabled(): self.send_response(302); self.send_header("Location","/login"); self.end_headers(); return
                if parsed.path in ("/", "/index.html"): self._file(dashboard.web_root / "index.html", "text/html; charset=utf-8")
                elif parsed.path in ("/state.json", "/api"): self._json(dashboard.snapshot())
                elif parsed.path == "/api/diagnostics/report": self._diagnostic_report()
                elif parsed.path == "/history.json":
                    name = parse_qs(parsed.query).get("range", ["24h"])[0]; self._json({"range": name, "samples": dashboard.history.query(name), "available": dashboard.history.available, "error": dashboard.history.error})
                elif parsed.path.startswith("/assets/"):
                    target = dashboard.web_root / Path(parsed.path).name; content_type = ASSET_TYPES.get(target.suffix); self._file(target, content_type) if content_type else self.send_error(404)
                else: self.send_error(404)
            def _diagnostic_report(self):
                if not dashboard.admin_token: return self.send_error(503,"Diagnostic helper unavailable")
                request=urllib.request.Request(f"{dashboard.admin_url.rstrip('/')}/diagnostics",headers={"Authorization":f"Bearer {dashboard.admin_token}"})
                try:
                    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=60) as response:
                        helper_payload=response.read(8*1024*1024+1); disposition=response.headers.get("Content-Disposition","")
                except (OSError,urllib.error.URLError): return self.send_error(503,"Diagnostic helper unavailable")
                if len(helper_payload)>8*1024*1024: return self.send_error(413,"Diagnostic report too large")
                snapshot=dashboard.snapshot(); safe_snapshot={key:("[REDACTED]" if any(word in key.lower() for word in ("token","password","secret","cookie","authorization")) else value) for key,value in snapshot.items()}
                state=json.dumps(safe_snapshot,indent=2,ensure_ascii=False,default=str).encode("utf-8")
                body=helper_payload+b"\n\n==================== PASSIVELINK CURRENT STATE ====================\n"+state+b"\n"
                filename="dantherm-debug.txt"
                if 'filename="' in disposition: filename=disposition.split('filename="',1)[1].split('"',1)[0]
                self.send_response(200); self.send_header("Content-Type","text/plain; charset=utf-8"); self.send_header("Content-Disposition",f'attachment; filename="{filename}"'); self.send_header("Cache-Control","no-store"); self.send_header("X-Content-Type-Options","nosniff"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
            def do_POST(self):
                if self.path == "/api/auth/setup":
                    if dashboard.auth.configured(): return self._json_error(409,"Allerede konfigureret")
                    data=self._read_json() or {}
                    try: dashboard.auth.save(data.get("username",""),data.get("password",""),True)
                    except ValueError as error: return self._json_error(400,str(error))
                    sid,csrf=dashboard.auth.session(data["username"].strip()); return self._login_reply(sid,csrf)
                if self.path == "/api/auth/login":
                    data=self._read_json() or {}; ip=self.client_address[0]
                    if not dashboard.auth.allow_attempt(ip): return self._json_error(429,"For mange forsøg. Vent fem minutter.")
                    if not dashboard.auth.verify(data.get("username",""),data.get("password","")): dashboard.auth.failed(ip); return self._json_error(401,"Forkert brugernavn eller adgangskode")
                    sid,csrf=dashboard.auth.session(data["username"]); return self._login_reply(sid,csrf)
                session=self._require_auth()
                if session is None: return
                if not self._csrf(session): return self._json_error(403,"Ugyldig sikkerhedstoken")
                if self.path == "/api/auth/logout": dashboard.auth.logout(self.headers.get("Cookie","")); return self._json({"ok":True})
                if self.path == "/api/auth/settings":
                    data=self._read_json() or {}
                    try: dashboard.auth.update(data.get("current_password",""),data.get("username",""),data.get("password",""),data.get("enabled",True))
                    except PermissionError as error: return self._json_error(401,str(error))
                    except ValueError as error: return self._json_error(400,str(error))
                    return self._json({"ok":True})
                if self.path != "/api/admin/action" or not dashboard.admin_token: return self.send_error(405)
                body=json.dumps(self._read_json() or {}).encode()
                request=urllib.request.Request(f"{dashboard.admin_url.rstrip('/')}/action",data=body,method="POST",headers={"Authorization":f"Bearer {dashboard.admin_token}","Content-Type":"application/json"})
                try:
                    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=4) as response: payload=response.read(); status=response.status
                except urllib.error.HTTPError as error: payload=error.read(); status=error.code
                except OSError: return self.send_error(503,"Admin helper unavailable")
                self.send_response(status); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(payload))); self.end_headers(); self.wfile.write(payload)
            def _login_reply(self,sid,csrf):
                body=json.dumps({"ok":True,"csrf":csrf}).encode(); self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Set-Cookie",f"dantherm_session={sid}; Path=/; HttpOnly; SameSite=Strict; Max-Age=43200"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
            def _json_error(self,status,message): self.send_response(status); body=json.dumps({"error":message}).encode(); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
            def _json(self, payload): self._body(json.dumps(payload, separators=(",", ":")).encode(), "application/json")
            def _file(self, path, content_type):
                try: body = path.read_bytes()
                except OSError: self.send_error(404); return
                self._body(body, content_type)
            def _body(self, body, content_type):
                self.send_response(200); self.send_header("Content-Type", content_type); self.send_header("Cache-Control", "no-store"); self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            def log_message(self, format_, *args): LOGGER.debug(format_, *args)
        self.server = ThreadingHTTPServer((self.host, self.port), Handler); self.thread = threading.Thread(target=self.server.serve_forever, name="dashboard-http", daemon=True); self.thread.start()
        def record_history():
            while not self.history_stop.is_set(): self.snapshot(); self.history_stop.wait(self.history.sample_seconds)
        self.history_stop.clear(); self.history_thread = threading.Thread(target=record_history, name="dashboard-history", daemon=True); self.history_thread.start()
        LOGGER.info("Web-dashboard lytter på %s:%s", self.host, self.port)
    def stop(self):
        self.history_stop.set()
        if self.server: self.server.shutdown(); self.server.server_close(); self.server = None
        if self.thread: self.thread.join(timeout=2); self.thread = None
        if self.history_thread: self.history_thread.join(timeout=2); self.history_thread = None
