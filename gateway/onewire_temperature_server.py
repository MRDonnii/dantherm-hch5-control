#!/usr/bin/env python3
"""Optional read-only DS18B20 HTTP service for HCH5 Control."""

from __future__ import annotations

import argparse
import json
import logging
import platform
import shutil
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LOGGER = logging.getLogger("passivelink-onewire")


STATE_PATH = Path("/var/lib/dantherm-passivelink/sensors.json")
THERMAL_ZONE_PATH = Path("/sys/class/thermal/thermal_zone0/temp")
UPTIME_PATH = Path("/proc/uptime")
LOADAVG_PATH = Path("/proc/loadavg")
MEMINFO_PATH = Path("/proc/meminfo")
MODEL_PATH = Path("/proc/device-tree/model")

# vcgencmd get_throttled bitmask - "now" bits report the live condition,
# "occurred" bits latch until the next reboot. See
# https://www.raspberrypi.com/documentation/computers/os.html#get_throttled
THROTTLED_BITS = {
    "undervoltage": (1 << 0, 1 << 16),
    "frequency_capped": (1 << 1, 1 << 17),
    "throttled": (1 << 2, 1 << 18),
    "soft_temp_limit": (1 << 3, 1 << 19),
}


class SensorReader:
    def __init__(self, config_path: str) -> None:
        try:
            config = json.loads(Path(config_path).read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError):
            config = {}
        self.flow_id = self._normalise(config.get("flow_sensor"))
        self.return_id = self._normalise(config.get("return_sensor"))
        state = self._load_state()
        self.saved_flow_id = self._normalise(state.get("flow_sensor"))
        self.saved_return_id = self._normalise(state.get("return_sensor"))

    @staticmethod
    def _load_state() -> dict:
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError):
            return {}

    def _save_state(self, flow_id: str, return_id: str) -> None:
        # Gem den automatisk fundne tildeling, saa frem/retur ikke kan bytte
        # plads ved genstart. Skrives kun naar tildelingen faktisk aendrer
        # sig, dvs. foerste gang eller hvis der kommer andre foelere paa.
        if (flow_id, return_id) == (self.saved_flow_id, self.saved_return_id):
            return
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            temporary = STATE_PATH.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(
                    {"flow_sensor": flow_id, "return_sensor": return_id},
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            temporary.replace(STATE_PATH)
            self.saved_flow_id = flow_id
            self.saved_return_id = return_id
            LOGGER.info(
                "Gemte foelertildeling: frem=%s retur=%s", flow_id, return_id
            )
        except OSError as exc:
            LOGGER.warning("Kunne ikke gemme foelertildeling: %s", exc)

    @staticmethod
    def _normalise(value: object) -> str | None:
        if not value:
            return None
        return str(value).lower().removeprefix("0x")

    def _sensor_ids(self) -> tuple[str | None, str | None]:
        discovered = sorted(
            path.name
            for path in Path("/sys/bus/w1/devices").glob("28-*")
            if (path / "w1_slave").exists()
        )
        # 1) Manuel opsaetning i /etc vinder altid, hvis begge foelere findes.
        configured = [self.flow_id, self.return_id]
        if all(sensor_id and sensor_id in discovered for sensor_id in configured):
            return self.flow_id, self.return_id
        # 2) Ellers genbruges den tidligere gemte automatiske tildeling, saa
        #    frem/retur ikke bytter plads ved genstart.
        saved = [self.saved_flow_id, self.saved_return_id]
        if all(sensor_id and sensor_id in discovered for sensor_id in saved):
            return self.saved_flow_id, self.saved_return_id
        # 3) Foerste gang - eller hvis der er kommet andre foelere paa -
        #    findes de automatisk og tildelingen gemmes.
        if len(discovered) >= 2:
            self._save_state(discovered[0], discovered[1])
            return discovered[0], discovered[1]
        return None, None

    @staticmethod
    def _read(sensor_id: str) -> float | None:
        path = Path("/sys/bus/w1/devices") / sensor_id / "w1_slave"
        try:
            lines = path.read_text(encoding="ascii").splitlines()
            if len(lines) < 2 or not lines[0].strip().endswith("YES"):
                return None
            marker = "t="
            position = lines[1].find(marker)
            if position < 0:
                return None
            value = int(lines[1][position + len(marker):]) / 1000.0
            if value == 85.0 or value <= -55.0 or value >= 125.0:
                return None
            return round(value, 2)
        except (FileNotFoundError, OSError, ValueError):
            return None

    @staticmethod
    def _read_model() -> str | None:
        try:
            return MODEL_PATH.read_text(encoding="utf-8").rstrip("\x00").strip() or None
        except (FileNotFoundError, OSError):
            return None

    @staticmethod
    def _read_kernel_version() -> str | None:
        try:
            return platform.release() or None
        except OSError:
            return None

    @staticmethod
    def _read_cpu_temperature() -> float | None:
        try:
            millidegrees = int(THERMAL_ZONE_PATH.read_text(encoding="ascii").strip())
            return round(millidegrees / 1000.0, 1)
        except (FileNotFoundError, OSError, ValueError):
            return None

    @staticmethod
    def _read_uptime_seconds() -> int | None:
        try:
            text = UPTIME_PATH.read_text(encoding="ascii")
            return int(float(text.split()[0]))
        except (FileNotFoundError, OSError, ValueError, IndexError):
            return None

    @staticmethod
    def _read_load_average_1m() -> float | None:
        try:
            text = LOADAVG_PATH.read_text(encoding="ascii")
            return float(text.split()[0])
        except (FileNotFoundError, OSError, ValueError, IndexError):
            return None

    @staticmethod
    def _read_memory_used_percent() -> float | None:
        try:
            values: dict[str, int] = {}
            for line in MEMINFO_PATH.read_text(encoding="ascii").splitlines():
                key, _, rest = line.partition(":")
                if key in ("MemTotal", "MemAvailable"):
                    values[key] = int(rest.strip().split()[0])
            total = values.get("MemTotal")
            available = values.get("MemAvailable")
            if not total:
                return None
            return round((total - available) / total * 100, 1)
        except (FileNotFoundError, OSError, ValueError, IndexError):
            return None

    @staticmethod
    def _read_disk_used_percent() -> float | None:
        try:
            usage = shutil.disk_usage("/")
            return round(usage.used / usage.total * 100, 1)
        except OSError:
            return None

    @staticmethod
    def _run_vcgencmd(*args: str) -> str | None:
        try:
            return subprocess.run(
                ["/usr/bin/vcgencmd", *args],
                capture_output=True,
                text=True,
                timeout=2,
                check=True,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None

    @classmethod
    def _read_core_voltage(cls) -> float | None:
        output = cls._run_vcgencmd("measure_volts", "core")
        if output is None:
            return None
        _, _, value = output.partition("=")
        try:
            return float(value.rstrip("V"))
        except ValueError:
            return None

    @classmethod
    def _read_throttled(cls) -> int | None:
        output = cls._run_vcgencmd("get_throttled")
        if output is None:
            return None
        _, _, hex_value = output.partition("=")
        try:
            return int(hex_value, 16)
        except ValueError:
            return None

    def _pi_diagnostics(self) -> dict[str, object]:
        cpu_temperature = self._read_cpu_temperature()
        throttled = self._read_throttled()
        bits: dict[str, object] = {}
        for name, (now_bit, occurred_bit) in THROTTLED_BITS.items():
            if throttled is None:
                bits[f"pi_{name}_now"] = None
                bits[f"pi_{name}_occurred"] = None
            else:
                bits[f"pi_{name}_now"] = bool(throttled & now_bit)
                bits[f"pi_{name}_occurred"] = bool(throttled & occurred_bit)
        return {
            "pi_diagnostics_available": cpu_temperature is not None or throttled is not None,
            "pi_model": self._read_model(),
            "pi_kernel_version": self._read_kernel_version(),
            "pi_cpu_temperature": cpu_temperature,
            "pi_uptime_seconds": self._read_uptime_seconds(),
            "pi_load_average_1m": self._read_load_average_1m(),
            "pi_memory_used_percent": self._read_memory_used_percent(),
            "pi_disk_used_percent": self._read_disk_used_percent(),
            "pi_core_voltage": self._read_core_voltage(),
            **bits,
        }

    def payload(self) -> dict[str, object]:
        flow_id, return_id = self._sensor_ids()
        flow = self._read(flow_id) if flow_id else None
        return_temp = self._read(return_id) if return_id else None
        payload = {
            "available": flow is not None and return_temp is not None,
            "flow_temperature": flow,
            "return_temperature": return_temp,
            "flow_sensor": flow_id,
            "return_sensor": return_id,
        }
        payload.update(self._pi_diagnostics())
        return payload


def handler_factory(reader: SensorReader):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path not in ("/temperatures", "/health"):
                self.send_error(404)
                return
            payload = reader.payload()
            body = json.dumps(payload, separators=(",", ":")).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format_: str, *args) -> None:
            LOGGER.debug(format_, *args)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="/etc/dantherm-passivelink/onewire.json")
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=4197)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    reader = SensorReader(args.config)
    server = ThreadingHTTPServer((args.bind, args.port), handler_factory(reader))
    LOGGER.info("Optional DS18B20 service listening on %s:%d", args.bind, args.port)
    server.serve_forever()


if __name__ == "__main__":
    main()
