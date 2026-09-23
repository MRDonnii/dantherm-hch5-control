#!/usr/bin/env python3
"""Dantherm HCH5/HAC1 RS485 -> MQTT gateway.

Programmet aflytter den eksisterende Modbus RTU-trafik mellem HAC1 og
hovedprintet. Det publicerer verificerede værdier og skriver kun via særskilt
verificerede og readback-beskyttede registersekvenser.
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import math
import os
import queue
import selectors
import signal
import socket
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import paho.mqtt.client as mqtt
import serial
import yaml

from controller_core import HardwareAdapter
from controller_dashboard_server import ControllerDashboardHttpServer
from controller_runtime import ControllerRuntime
from sensor_freshness import SENSOR_SAMPLE_TIMESTAMPS

LOG = logging.getLogger("dantherm_gateway")

# High-frequency measurements can change every few seconds. Keep them at
# DEBUG so journald remains useful for lifecycle events and real faults.
INFO_STATE_KEYS = {
    "availability",
    "bus_traffic",
    "control_status",
    "gateway_mode",
    "hac1_connected",
    "operating_mode",
    "current_level",
    "bypass_active",
    "bypass_raw",
    "bypass_travel_direction",
    "fireplace",
    "standby",
    "night_mode",
    "filter_status",
    "filter_alarm",
}
KNOWN_SLAVES = {1, 0x40}
# FC04 register 7 is the damper's status, not its position (captured on the
# live HCH5 2026-09-23): 0 closed, 64 opening, 32 closing, 255 open. The unit
# runs the damper for a fixed ~180 s in either direction.
BYPASS_TRAVEL_CODES = {64: "opening", 32: "closing"}
FIREPLACE_DURATION_SECONDS = 15 * 60
FILTER_INTERVAL_MIN_DAYS = 90
FILTER_INTERVAL_MAX_DAYS = 360
CONTROL_STEPS = {
    "manual_1": (25, 13),
    "manual_2": (55, 43),
    "manual_3": (85, 73),
    "boost": (100, 88),
}
MODE_LABELS = {
    "auto": "AUTO",
    "manual_1": "Trin 1",
    "manual_2": "Trin 2",
    "manual_3": "Trin 3",
    "boost": "Boost",
}
MODE_COMMANDS = {label.lower(): mode for mode, label in MODE_LABELS.items()}
MODE_COMMANDS.update({mode: mode for mode in MODE_LABELS})
LEVEL_TARGETS = {
    "OFF (Trin 0)": (0, 0),
    "Trin 1": (25, 13),
    "Trin 2": (55, 43),
    "Trin 3": (85, 73),
    "Boost": (100, 88),
}


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


class DirectionCapture:
    """Non-blocking serial-boundary capture with independent RX framing."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.records: queue.SimpleQueue[dict | None] = queue.SimpleQueue()
        self.running = False
        self.thread: threading.Thread | None = None
        self.rx_buffer = bytearray()
        self.recent_tx: deque[tuple[int, bytes, str]] = deque(maxlen=64)
        self.path: Path | None = None

    @staticmethod
    def _timestamp() -> tuple[int, str]:
        return time.monotonic_ns(), datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _fields(frame: bytes) -> dict[str, object]:
        result: dict[str, object] = {
            "slave": frame[0] if frame else None,
            "function": frame[1] if len(frame) > 1 else None,
            "raw_hex": frame.hex(" "),
            "crc_ok": len(frame) >= 4
            and crc16(frame[:-2]) == int.from_bytes(frame[-2:], "little"),
            "frame_length": len(frame),
        }
        if len(frame) >= 6 and frame[1] == 6:
            result["frame_kind"] = "request_or_response"
            result.update(
                register=int.from_bytes(frame[2:4], "big"),
                value=int.from_bytes(frame[4:6], "big"),
            )
        elif len(frame) >= 6 and frame[1] in (3, 4):
            is_response = len(frame) > 8 and frame[2] == len(frame) - 5
            result["frame_kind"] = "response" if is_response else "request"
            if is_response:
                result["byte_count"] = frame[2]
                result["payload"] = frame[3:-2].hex(" ")
            else:
                result.update(
                    start_register=int.from_bytes(frame[2:4], "big"),
                    count=int.from_bytes(frame[4:6], "big"),
                )
        elif len(frame) >= 6 and frame[1] == 16:
            is_request = len(frame) > 8
            result["frame_kind"] = "request" if is_request else "response"
            result.update(
                start_register=int.from_bytes(frame[2:4], "big"),
                count=int.from_bytes(frame[4:6], "big"),
            )
            if is_request:
                result["payload"] = frame[7:-2].hex(" ")
        return result

    @staticmethod
    def _frame_length(buffer: bytearray) -> int | None:
        if len(buffer) < 5:
            return None
        function = buffer[1]
        candidates: list[int] = []
        if function in (3, 4):
            byte_count = buffer[2]
            if 0 < byte_count <= 250 and byte_count % 2 == 0:
                candidates.append(5 + byte_count)
            candidates.append(8)
        elif function == 6:
            candidates.append(8)
        elif function == 16:
            if len(buffer) >= 7:
                count = int.from_bytes(buffer[4:6], "big")
                byte_count = buffer[6]
                if byte_count == count * 2 and 0 < byte_count <= 246:
                    candidates.append(9 + byte_count)
            candidates.append(8)
        for length in candidates:
            if len(buffer) >= length and crc16(buffer[: length - 2]) == int.from_bytes(
                buffer[length - 2 : length], "little"
            ):
                return length
        return -1 if len(buffer) >= max(candidates, default=5) else None

    def start(self) -> None:
        if self.running:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.path = self.directory / f"direction-{stamp}.jsonl"
        self.running = True
        self.thread = threading.Thread(
            target=self._writer, name="rs485-direction-capture", daemon=True
        )
        self.thread.start()
        LOG.info("Direction-aware capture startet: %s", self.path)

    def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        self.records.put(None)
        if self.thread is not None:
            self.thread.join(timeout=3)
        LOG.info("Direction-aware capture stoppet: %s", self.path)

    def _writer(self) -> None:
        assert self.path is not None
        with self.path.open("a", encoding="utf-8", buffering=1) as output:
            while True:
                record = self.records.get()
                if record is None:
                    break
                output.write(json.dumps(record, separators=(",", ":")) + "\n")

    def record_tx(self, data: bytes, reason: str) -> None:
        if not self.running:
            return
        monotonic_ns, wall = self._timestamp()
        self.recent_tx.append((monotonic_ns, data, reason))
        self.records.put(
            {
                "record_type": "frame",
                "monotonic_ns": monotonic_ns,
                "wall_clock": wall,
                "direction": "TX-GATEWAY",
                "source": reason,
                "echo_candidate": False,
                **self._fields(data),
            }
        )

    def record_rx(self, data: bytes) -> None:
        if not self.running or not data:
            return
        monotonic_ns, wall = self._timestamp()
        self.records.put(
            {
                "record_type": "raw_chunk",
                "monotonic_ns": monotonic_ns,
                "wall_clock": wall,
                "direction": "RX",
                "source": "SERIAL_READ",
                "raw_hex": data.hex(" "),
                "frame_length": len(data),
            }
        )
        self.rx_buffer.extend(data)
        while len(self.rx_buffer) >= 5:
            length = self._frame_length(self.rx_buffer)
            if length is None:
                break
            if length < 0:
                del self.rx_buffer[0]
                continue
            frame = bytes(self.rx_buffer[:length])
            del self.rx_buffer[:length]
            echo_reason = None
            echo_delta_ns = None
            for tx_ns, tx_frame, reason in reversed(self.recent_tx):
                delta = monotonic_ns - tx_ns
                if delta > 100_000_000:
                    break
                if tx_frame == frame:
                    echo_reason = reason
                    echo_delta_ns = delta
                    break
            self.records.put(
                {
                    "record_type": "frame",
                    "monotonic_ns": monotonic_ns,
                    "wall_clock": wall,
                    "direction": "RX",
                    "source": "SERIAL_READ",
                    "echo_candidate": echo_reason is not None,
                    "echo_of_source": echo_reason,
                    "echo_delta_ns": echo_delta_ns,
                    **self._fields(frame),
                }
            )


class ReadOnlyTcpMirror:
    """Mirror inbound serial bytes to TCP clients, never TCP back to RS485."""

    def __init__(self, host: str, port: int, max_clients: int = 4):
        self.host = host
        self.port = port
        self.max_clients = max_clients
        self.selector = selectors.DefaultSelector()
        self.clients: set[socket.socket] = set()
        self.lock = threading.Lock()
        self.running = False
        self.listener: socket.socket | None = None
        self.thread: threading.Thread | None = None

    def start(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self.host, self.port))
        listener.listen(self.max_clients)
        listener.setblocking(False)
        self.listener = listener
        self.selector.register(listener, selectors.EVENT_READ)
        self.running = True
        self.thread = threading.Thread(
            target=self._serve, name="rs485-read-only-tcp", daemon=True
        )
        self.thread.start()
        LOG.info("Read-only RS485 TCP-spejl lytter på %s:%s", self.host, self.port)

    def _drop(self, client: socket.socket):
        with self.lock:
            self.clients.discard(client)
        try:
            self.selector.unregister(client)
        except Exception:
            pass
        try:
            client.close()
        except OSError:
            pass

    def _serve(self):
        while self.running:
            try:
                events = self.selector.select(timeout=0.5)
            except (OSError, ValueError):
                break
            for key, _ in events:
                if key.fileobj is self.listener:
                    try:
                        client, address = self.listener.accept()
                        client.setblocking(False)
                    except OSError:
                        continue
                    with self.lock:
                        if len(self.clients) >= self.max_clients:
                            client.close()
                            continue
                        self.clients.add(client)
                    self.selector.register(client, selectors.EVENT_READ)
                    LOG.info("TCP-læser tilsluttet fra %s", address[0])
                    continue

                client = key.fileobj
                try:
                    received = client.recv(1024)
                except BlockingIOError:
                    continue
                except OSError:
                    received = b""
                if received:
                    # This service has deliberately no path to serial.write().
                    LOG.warning("Afviser data fra TCP-klient; forbindelsen lukkes")
                self._drop(client)

    def broadcast(self, data: bytes):
        if not data:
            return
        with self.lock:
            clients = tuple(self.clients)
        for client in clients:
            try:
                client.sendall(data)
            except (BlockingIOError, BrokenPipeError, ConnectionResetError, OSError):
                self._drop(client)

    def stop(self):
        self.running = False
        with self.lock:
            clients = tuple(self.clients)
        for client in clients:
            self._drop(client)
        if self.listener is not None:
            try:
                self.selector.unregister(self.listener)
            except Exception:
                pass
            self.listener.close()
            self.listener = None
        if self.thread is not None:
            self.thread.join(timeout=2)
        self.selector.close()


class DashboardHttpServer:
    """Serve one merged, human-readable status page for the whole gateway.

    Combines the decoded RS485 state (self.state, populated regardless of
    whether MQTT is enabled) with a live fetch of the optional Pi/water
    diagnostics endpoint, so everything is visible on a single port instead
    of being split across 4196 (raw RS485 TCP) and 4197 (onewire JSON).
    """

    def __init__(
        self,
        host: str,
        port: int,
        state: dict[str, object],
        device_name: str,
        preheater_url: str | None,
    ):
        self.host = host
        self.port = port
        self.state = state
        self.device_name = device_name
        self.preheater_url = preheater_url
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def start(self):
        dashboard = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path in ("/", "/index.html"):
                    body = dashboard.render_html().encode("utf-8")
                    content_type = "text/html; charset=utf-8"
                elif self.path in ("/state.json", "/api"):
                    body = json.dumps(
                        dashboard.snapshot(), separators=(",", ":")
                    ).encode("utf-8")
                    content_type = "application/json"
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format_: str, *args) -> None:
                LOG.debug(format_, *args)

        server = ThreadingHTTPServer((self.host, self.port), Handler)
        self.server = server
        self.thread = threading.Thread(
            target=server.serve_forever, name="dashboard-http", daemon=True
        )
        self.thread.start()
        LOG.info("Web-dashboard lytter på %s:%s", self.host, self.port)

    def stop(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.thread is not None:
            self.thread.join(timeout=2)
            self.thread = None

    def _fetch_preheater(self) -> dict[str, object]:
        if not self.preheater_url:
            return {}
        try:
            with urllib.request.urlopen(self.preheater_url, timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError, urllib.error.URLError):
            return {"preheater_diagnostics_reachable": False}
        if not isinstance(payload, dict):
            return {"preheater_diagnostics_reachable": False}
        payload["preheater_diagnostics_reachable"] = True
        return payload

    def snapshot(self) -> dict[str, object]:
        merged = dict(self.state)
        merged.update(self._fetch_preheater())
        return merged

    @staticmethod
    def _label(key: str) -> str:
        return key.replace("_", " ").capitalize()

    @staticmethod
    def _format(value: object) -> str:
        if isinstance(value, bool):
            return "Ja" if value else "Nej"
        if value is None:
            return "-"
        return html.escape(str(value))

    def render_html(self) -> str:
        data = self.snapshot()
        rows = "\n".join(
            f"<tr><td>{html.escape(self._label(key))}</td><td>{self._format(value)}</td></tr>"
            for key, value in sorted(data.items())
        )
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        return f"""<!DOCTYPE html>
<html lang="da">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="5">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(self.device_name)} - status</title>
<style>
  body {{ font-family: system-ui, sans-serif; background: #111; color: #eee; margin: 2rem; }}
  h1 {{ font-weight: 600; }}
  table {{ border-collapse: collapse; width: 100%; max-width: 720px; }}
  td {{ padding: 0.4rem 0.8rem; border-bottom: 1px solid #333; }}
  td:first-child {{ color: #9ad; white-space: nowrap; }}
  caption {{ text-align: left; color: #888; margin-bottom: 0.5rem; font-weight: normal; }}
  a {{ color: #9ad; }}
</style>
</head>
<body>
<h1>{html.escape(self.device_name)}</h1>
<table>
<caption>Opdateres automatisk hvert 5. sekund &mdash; {timestamp} &mdash; <a href="/state.json">rå JSON</a></caption>
{rows}
</table>
</body>
</html>
"""


class RtuSniffer:
    def __init__(self, port: str, baudrate: int, parity: str, deduplicate_ms: int):
        self.port = port
        self.baudrate = baudrate
        self.parity = parity
        self.dedupe_s = deduplicate_ms / 1000.0
        self.buffer = bytearray()
        self.last_seen: dict[bytes, float] = {}

    def open(self) -> serial.Serial:
        ser = serial.Serial(
            self.port,
            self.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_EVEN if self.parity.upper() == "E" else serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.05,
            exclusive=True,
        )
        # FTDI control lines holdes passive. Der kaldes aldrig write().
        try:
            ser.rts = False
            ser.dtr = False
        except (AttributeError, OSError):
            pass
        return ser

    def feed(self, data: bytes):
        self.buffer.extend(data)
        offset = 0
        while offset + 5 <= len(self.buffer):
            if self.buffer[offset] not in KNOWN_SLAVES:
                offset += 1
                continue
            fn = self.buffer[offset + 1]
            lengths: list[int] = []
            if fn in (3, 4):
                lengths.append(8)  # request
                byte_count = self.buffer[offset + 2]
                if byte_count and byte_count <= 250 and byte_count % 2 == 0:
                    lengths.insert(0, 5 + byte_count)  # response
            elif fn in (6, 16):
                lengths.append(8)
            else:
                offset += 1
                continue

            frame = None
            for length in lengths:
                if offset + length > len(self.buffer):
                    continue
                candidate = bytes(self.buffer[offset : offset + length])
                if crc16(candidate[:-2]) == int.from_bytes(candidate[-2:], "little"):
                    frame = candidate
                    break
            if frame is None:
                offset += 1
                continue
            offset += len(frame)
            now = time.monotonic()
            previous = self.last_seen.get(frame, 0.0)
            self.last_seen[frame] = now
            if now - previous >= self.dedupe_s:
                yield frame

        if offset:
            del self.buffer[:offset]
        if len(self.buffer) > 1024:
            del self.buffer[:-16]


class Gateway:
    def __init__(self, config: dict):
        self.cfg = config
        self.mqtt_enabled = bool(config.get("mqtt", {}).get("enabled", True))
        self.prefix = config["mqtt"].get("topic_prefix", "dantherm").rstrip("/")
        self.discovery = config["mqtt"].get("discovery_prefix", "homeassistant").rstrip("/")
        self.device_id = config["device"].get("id", "dantherm_hch5")
        self.device_name = config["device"].get("name", "Dantherm HCH5")
        self.retain = bool(config["mqtt"].get("retain", True))
        self.state: dict[str, object] = {}
        self.running = True
        self.last_manual_write = 0.0
        self.control_enabled = bool(config.get("control", {}).get("enabled", False))
        self.fireplace_enabled = bool(
            config.get("control", {}).get("fireplace_enabled", False)
        )
        self.active_reads_enabled = bool(
            config.get("serial", {}).get("active_reads_enabled", False)
        )
        self.master_mode = bool(config.get("serial", {}).get("master_mode", False))
        capture_cfg = config.get("diagnostic_capture", {})
        self.direction_capture = DirectionCapture(
            Path(capture_cfg.get("directory", "/var/lib/dantherm-hch5-ha/direction-captures"))
        )
        self.capture_toggle_requested = False
        self.controller_reload_requested = False
        self.control_queue: queue.SimpleQueue[str] = queue.SimpleQueue()
        self.controller_hardware_queue: queue.SimpleQueue[tuple[str, object, threading.Event, dict]] = queue.SimpleQueue()
        self.fireplace_queue: queue.SimpleQueue[bool] = queue.SimpleQueue()
        self.filter_reset_queue: queue.SimpleQueue[bool] = queue.SimpleQueue()
        self.filter_interval_queue: queue.SimpleQueue[int] = queue.SimpleQueue()
        self.override_mode: str | None = None
        self.restore_pair: tuple[int, int] | None = None
        self.startup_mode: str | None = None
        self.external_mode: str | None = None
        self.pending_external_auto_until = 0.0
        self.pending_external_manual3_until = 0.0
        self.auto_command_pending = False
        self.auto_command_until = 0.0
        self.auto_command_start_pair: tuple[int, int] | None = None
        self.control_state_path = Path(
            config.get("control", {}).get(
                "state_file", "/var/lib/dantherm-hch5-ha/control-state.json"
            )
        )
        self.fireplace_state_path = Path(
            config.get("control", {}).get(
                "fireplace_state_file",
                "/var/lib/dantherm-hch5-ha/fireplace-state.json",
            )
        )
        self.external_mode_state_path = Path(
            config.get("control", {}).get(
                "external_mode_state_file",
                "/var/lib/dantherm-hch5-ha/external-mode-state.json",
            )
        )
        self.fireplace_gateway_active = False
        self.fireplace_restore: tuple[int, int, int, int] | None = None
        self.fireplace_until_monotonic = 0.0
        self.fireplace_until_epoch = 0.0
        self.startup_fireplace: dict | None = None
        self.last_fireplace_write = 0.0
        self.special_mode_flag: int | None = None
        self.filter_enabled = bool(config.get("filter", {}).get("enabled", False))
        self.filter_state_path = Path(
            config.get("filter", {}).get(
                "state_file", "/var/lib/dantherm-hch5-ha/filter-state.json"
            )
        )
        self.filter_reset_epoch = time.time()
        self.filter_interval_days = FILTER_INTERVAL_MAX_DAYS
        self.last_filter_publish = 0.0
        self.last_override_write = 0.0
        self.last_control_verify = 0.0
        self.last_afterheat_poll = 0.0
        self.last_afterheat_temperature_refresh = 0.0
        self.last_afterheat_block_at: float | None = None
        self.last_hrc2_t5_poll = 0.0
        self.last_temperature_snapshot_poll = 0.0
        self.last_bypass_request_poll = 0.0
        self.last_bus_frame = 0.0
        self.reader_started_at = 0.0
        self.last_bus_health_publish = 0.0
        self.last_master_poll = 0.0
        self.filter_command_until = 0.0
        self.last_explicit_mode_command = 0.0
        self.pending_night_transition_until = 0.0
        self.night_mode_state_path = Path(
            config.get("state", {}).get(
                "night_mode_file",
                "/var/lib/dantherm-hch5-ha/night-mode-state.json",
            )
        )
        self.night_mode_active: bool | None = None
        self.hold_interval = float(config.get("control", {}).get("hold_interval_seconds", 0.8))
        self.load_control_state()
        self.load_external_mode_state()
        self.load_fireplace_state()
        self.load_filter_state()
        self.load_night_mode_state()

        controller_cfg = config.get("controller", {})
        self.controller = ControllerRuntime(
            gateway_state=self.state,
            hardware=HardwareAdapter(
                write_fan_pair=lambda extract, supply: self.queue_controller_hardware("fan_pair", (extract, supply)),
                set_bypass=lambda value: self.queue_controller_hardware("bypass", str(value)),
                set_fireplace=lambda enabled: self.queue_controller_hardware("fireplace", bool(enabled)),
                set_afterheat_setpoint=lambda value: self.queue_controller_hardware("afterheat_setpoint", value),
            ),
            state_path=controller_cfg.get("state_file", "/var/lib/dantherm-hch5-ha/controller.json"),
            tick_seconds=float(controller_cfg.get("tick_seconds", 2.0)),
        )

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"{self.device_id}_gateway")
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        user = os.getenv("MQTT_USER") or config["mqtt"].get("username")
        if user:
            password = os.getenv("MQTT_PASS") or config["mqtt"].get("password")
            self.client.username_pw_set(user, password)
        self.client.will_set(f"{self.prefix}/availability", "offline", retain=True)

    def queue_controller_hardware(self, action: str, value: object):
        """Serialize controller writes onto the gateway's sole RS485 thread."""
        done = threading.Event()
        result: dict[str, object] = {}
        self.controller_hardware_queue.put((action, value, done, result))
        if not done.wait(4.0):
            raise TimeoutError(f"controller hardware timeout: {action}")
        if result.get("error"):
            raise RuntimeError(str(result["error"]))
        return result.get("value")

    def process_controller_hardware(self, ser: serial.Serial):
        while not self.controller_hardware_queue.empty():
            action, value, done, result = self.controller_hardware_queue.get()
            try:
                if action == "fan_pair":
                    extract, supply = value
                    self.write_pair(ser, int(extract), int(supply))
                    actual = self.read_fan_pair(ser)
                    if actual != (int(extract), int(supply)):
                        raise RuntimeError(f"fan readback mismatch: {actual}")
                    self.publish("fan_extract_percent", actual[0])
                    self.publish("fan_supply_percent", actual[1])
                    result["value"] = actual
                elif action == "fireplace":
                    if value and not self.fireplace_gateway_active:
                        self.start_fireplace(ser)
                        if not self.fireplace_gateway_active:
                            raise RuntimeError("verified fireplace sequence rejected")
                    elif not value and self.fireplace_gateway_active:
                        self.stop_fireplace(ser)
                    result["value"] = self.fireplace_gateway_active
                elif action == "bypass":
                    result["value"] = self.write_bypass_request(ser, str(value))
                elif action == "afterheat_setpoint":
                    result["value"] = self.write_afterheat_setpoint(
                        ser, None if value is None else int(value)
                    )
                else:
                    raise RuntimeError(f"unknown controller hardware action: {action}")
            except Exception as error:
                LOG.exception("Controller hardware action failed: %s", action)
                result["error"] = str(error)
            finally:
                done.set()

    def load_night_mode_state(self):
        try:
            saved = json.loads(self.night_mode_state_path.read_text(encoding="utf-8"))
            if isinstance(saved.get("active"), bool):
                self.night_mode_active = saved["active"]
        except (OSError, ValueError, TypeError):
            self.night_mode_active = None

    def save_night_mode_state(self):
        if self.night_mode_active is None:
            return
        try:
            self.night_mode_state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.night_mode_state_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps({"active": self.night_mode_active}), encoding="utf-8"
            )
            temporary.replace(self.night_mode_state_path)
        except OSError as exc:
            LOG.error("Kunne ikke gemme natdriftstilstand: %s", exc)

    def load_control_state(self):
        try:
            saved = json.loads(self.control_state_path.read_text(encoding="utf-8"))
            mode = saved.get("mode")
            pair = saved.get("restore_pair")
            if mode not in CONTROL_STEPS or not isinstance(pair, list) or len(pair) != 2:
                raise ValueError("ugyldig gemt styringstilstand")
            restore_pair = tuple(int(value) for value in pair)
            if any(value < 0 or value > 100 for value in restore_pair):
                raise ValueError("ugyldigt gemt AUTO-sætpunkt")
            self.startup_mode = mode
            self.restore_pair = restore_pair
            LOG.info("Indlæste gemt mode %s med AUTO-værdier %s/%s", mode, *restore_pair)
        except FileNotFoundError:
            return
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            LOG.warning("Ignorerer ugyldig gemt styringstilstand: %s", exc)

    def save_control_state(self):
        if self.override_mode is None or self.restore_pair is None:
            try:
                self.control_state_path.unlink(missing_ok=True)
            except OSError as exc:
                LOG.warning("Kunne ikke rydde gemt styringstilstand: %s", exc)
            return
        try:
            self.control_state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.control_state_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(
                    {"mode": self.override_mode, "restore_pair": list(self.restore_pair)},
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            temporary.replace(self.control_state_path)
        except OSError as exc:
            LOG.error("Kunne ikke gemme styringstilstand: %s", exc)

    def load_external_mode_state(self):
        try:
            saved = json.loads(self.external_mode_state_path.read_text(encoding="utf-8"))
            mode = saved.get("mode")
            if mode not in {"auto", "manual_3"}:
                raise ValueError("ukendt ekstern mode")
            self.external_mode = mode
        except FileNotFoundError:
            return
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            LOG.warning("Ignorerer ugyldig gemt HRC-mode: %s", exc)

    def save_external_mode_state(self):
        if self.external_mode not in {"auto", "manual_3"}:
            return
        try:
            self.external_mode_state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.external_mode_state_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps({"mode": self.external_mode}), encoding="utf-8"
            )
            temporary.replace(self.external_mode_state_path)
        except OSError as exc:
            LOG.error("Kunne ikke gemme observeret HRC-mode: %s", exc)

    def load_fireplace_state(self):
        try:
            saved = json.loads(self.fireplace_state_path.read_text(encoding="utf-8"))
            restore = saved.get("restore")
            until = float(saved.get("until", 0))
            if not isinstance(restore, list) or len(restore) != 4:
                raise ValueError("ugyldig gemt Pejs-gendannelse")
            restore_values = tuple(int(value) for value in restore)
            if any(value < 0 or value > 100 for value in restore_values):
                raise ValueError("ugyldige gemte Pejs-værdier")
            if until <= time.time():
                self.fireplace_state_path.unlink(missing_ok=True)
                return
            self.startup_fireplace = {"restore": restore_values, "until": until}
            if self.startup_mode is not None:
                LOG.warning("Pejs-genoptagelse har prioritet over gemt ventilatortrin")
                self.startup_mode = None
                self.restore_pair = None
        except FileNotFoundError:
            return
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            LOG.warning("Ignorerer ugyldig gemt Pejs-tilstand: %s", exc)

    def save_fireplace_state(self):
        if not self.fireplace_gateway_active or self.fireplace_restore is None:
            try:
                self.fireplace_state_path.unlink(missing_ok=True)
            except OSError as exc:
                LOG.warning("Kunne ikke rydde gemt Pejs-tilstand: %s", exc)
            return
        try:
            self.fireplace_state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.fireplace_state_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(
                    {
                        "restore": list(self.fireplace_restore),
                        "until": self.fireplace_until_epoch,
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            temporary.replace(self.fireplace_state_path)
        except OSError as exc:
            LOG.error("Kunne ikke gemme Pejs-tilstand: %s", exc)

    def load_filter_state(self):
        try:
            saved = json.loads(self.filter_state_path.read_text(encoding="utf-8"))
            self.filter_reset_epoch = float(saved["reset_epoch"])
            self.filter_interval_days = max(
                FILTER_INTERVAL_MIN_DAYS,
                min(FILTER_INTERVAL_MAX_DAYS, int(saved.get("interval_days", 360))),
            )
        except FileNotFoundError:
            self.save_filter_state()
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            LOG.warning("Nulstiller ugyldig gateway-filtertimer: %s", exc)
            self.filter_reset_epoch = time.time()
            self.save_filter_state()

    def save_filter_state(self):
        try:
            self.filter_state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.filter_state_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(
                    {
                        "reset_epoch": self.filter_reset_epoch,
                        "interval_days": self.filter_interval_days,
                    }
                ),
                encoding="utf-8",
            )
            temporary.replace(self.filter_state_path)
        except OSError as exc:
            LOG.error("Kunne ikke gemme gateway-filtertimer: %s", exc)

    def on_connect(self, client, _userdata, _flags, reason_code, _properties):
        if reason_code != 0:
            LOG.error("MQTT-forbindelse afvist: %s", reason_code)
            return
        LOG.info("MQTT forbundet; publicerer availability og seneste tilstand igen")
        client.publish(f"{self.prefix}/availability", "online", retain=True)
        self.publish_discovery()
        for key, value in list(self.state.items()):
            client.publish(
                f"{self.prefix}/{key}", self.format_payload(value), retain=self.retain
            )
        client.subscribe(f"{self.prefix}/restart_gateway/set")
        client.subscribe(f"{self.prefix}/bypass_request/set")
        if self.control_enabled:
            client.subscribe(f"{self.prefix}/mode/set")
            if self.fireplace_enabled:
                client.subscribe(f"{self.prefix}/fireplace_gateway/set")

    def on_disconnect(
        self, _client, _userdata, _disconnect_flags, reason_code, _properties
    ):
        if self.running:
            LOG.warning("MQTT afbrudt (%s); Paho genforbinder automatisk", reason_code)

    def on_message(self, _client, _userdata, message):
        if message.topic not in {
            f"{self.prefix}/mode/set",
            f"{self.prefix}/fireplace_gateway/set",
            f"{self.prefix}/filter_reset/set",
            f"{self.prefix}/filter_interval/set",
            f"{self.prefix}/restart_gateway/set",
            f"{self.prefix}/bypass_request/set",
        }:
            return
        if message.retain:
            LOG.warning("Ignorerer retained modekommando af hensyn til genstartssikkerhed")
            return
        command = message.payload.decode("utf-8", errors="replace").strip().lower()
        if not command:
            return
        if message.topic == f"{self.prefix}/restart_gateway/set":
            LOG.warning("MQTT-genstart anmodet")
            self.running = False
            return
        if message.topic == f"{self.prefix}/bypass_request/set":
            if command not in {"on", "off"}:
                LOG.warning("Afviser ukendt bypasskommando: %r", command)
                return
            try:
                self.controller.configure({"bypass": command})
            except Exception as error:
                LOG.error("Bypasskommando mislykkedes: %s", error)
            return
        if message.topic == f"{self.prefix}/filter_reset/set":
            self.filter_reset_queue.put(True)
            return
        if message.topic == f"{self.prefix}/filter_interval/set":
            try:
                interval = int(round(float(command)))
            except ValueError:
                LOG.warning("Afviser ugyldigt filterinterval: %r", command)
                return
            if FILTER_INTERVAL_MIN_DAYS <= interval <= FILTER_INTERVAL_MAX_DAYS:
                self.filter_interval_queue.put(interval)
            else:
                LOG.warning("Afviser filterinterval uden for 90-360 dage: %s", interval)
            return
        if message.topic == f"{self.prefix}/fireplace_gateway/set":
            if command in {"on", "1", "true"}:
                self.fireplace_queue.put(True)
            elif command in {"off", "0", "false"}:
                self.fireplace_queue.put(False)
            else:
                LOG.warning("Afviser ukendt pejsekommando: %r", command)
            return
        mode = MODE_COMMANDS.get(command)
        if mode is not None:
            self.control_queue.put(mode)
        else:
            LOG.warning("Afviser ukendt modekommando: %r", command)

    def connect(self):
        if not self.mqtt_enabled:
            LOG.info("MQTT-publicering er deaktiveret; rå RS485-TCP-spejl fortsætter")
            return
        m = self.cfg["mqtt"]
        host = os.getenv("MQTT_HOST") or m["host"]
        port = int(os.getenv("MQTT_PORT") or m.get("port", 1883))
        self.client.connect(host, port, 60)
        self.client.loop_start()

    def publish_discovery(self):
        device = {
            "identifiers": [self.device_id],
            "name": self.device_name,
            "manufacturer": "Dantherm",
            "model": "HCH5 MK1 + HAC1",
        }
        entities = {
            "outdoor_temp": ("sensor", "Temperatur – Udeluft", "°C", "temperature", "measurement"),
            "supply_temp": ("sensor", "Temperatur – Indblæsning", "°C", "temperature", "measurement"),
            "extract_temp": ("sensor", "Temperatur – Udsugning", "°C", "temperature", "measurement"),
            "exhaust_temp": ("sensor", "Temperatur – Afkast", "°C", "temperature", "measurement"),
            "co2": ("sensor", "Luftkvalitet – CO₂", "ppm", "carbon_dioxide", "measurement"),
            "afterheat_setpoint": ("sensor", "Eftervarme – Setpunkt", "°C", "temperature", "measurement"),
            "afterheat_active": ("binary_sensor", "Eftervarme – Aktiv", None, "heat", None),
            "fan_extract_rpm": ("sensor", "Ventilator – Udsugning RPM", "rpm", None, "measurement"),
            "fan_supply_rpm": ("sensor", "Ventilator – Indblæsning RPM", "rpm", None, "measurement"),
            "fan_extract_percent": ("sensor", "Ventilator – Udsugning styring", "%", None, "measurement"),
            "fan_supply_percent": ("sensor", "Ventilator – Indblæsning styring", "%", None, "measurement"),
            # Registerets betydning/skala er endnu ikke verificeret. Værdier
            # over 100 er observeret, så den må ikke vises som en procent.
            "heat_recovery_efficiency": ("sensor", "Diagnostik – Varmegenvinding råværdi", None, None, None),
            "bypass_active": ("binary_sensor", "Drift – Bypass aktiv", None, "opening", None),
            "bypass_raw": ("sensor", "Diagnostik – Bypass råstatus", None, None, None),
            "bypass_request_raw": ("sensor", "Diagnostik – Bypass-request råværdi", None, None, None),
            "status_code": ("sensor", "Diagnostik – Statuskode", None, None, None),
            "operating_mode": ("sensor", "Drift – Registreret tilstand", None, None, None),
            "current_level": ("sensor", "Drift – Aktuelt trin", None, None, None),
            "fireplace_remaining": ("sensor", "Pejs-ventilation – Resterende tid", "min", None, "measurement"),
            "filter_days_remaining": ("sensor", "Filter – Resterende tid", "d", "duration", "measurement"),
            "filter_life_percent": ("sensor", "Filter – Levetid", "%", None, "measurement"),
            "filter_status": ("sensor", "Filter – Status", None, None, None),
            "filter_source": ("sensor", "Filter – Datakilde", None, None, None),
            "filter_alarm": ("binary_sensor", "Filter – Alarm", None, "problem", None),
            "hac1_connected": ("binary_sensor", "Diagnostik – HAC1 forbindelse", None, "connectivity", None),
            "fireplace": ("binary_sensor", "Drift – Pejsefunktion", None, None, None),
            "standby": ("binary_sensor", "Drift – Standby", None, None, None),
            "night_mode": ("binary_sensor", "Drift – Natdrift", None, None, None),
            "command_raw": ("sensor", "Diagnostik – Betjeningskommando rå", None, None, None),
            "control_status": ("sensor", "Diagnostik – Styringsstatus", None, None, None),
            "gateway_mode": ("sensor", "Diagnostik – Gatewaytilstand", None, None, None),
            "bus_last_frame_age": ("sensor", "Diagnostik – Seneste bustrafik", "s", "duration", "measurement"),
            "bus_traffic": ("binary_sensor", "Diagnostik – Bustrafik", None, "connectivity", None),
        }
        diagnostic_entities = {
            "hac1_connected",
            "bypass_raw",
            "bypass_request_raw",
            "status_code",
            "command_raw",
            "control_status",
            "gateway_mode",
            "bus_last_frame_age",
            "bus_traffic",
        }
        disabled_raw_entities = {"bypass_raw", "bypass_request_raw", "status_code", "command_raw"}
        for key, (component, name, unit, device_class, state_class) in entities.items():
            payload = {
                "name": name,
                "unique_id": f"{self.device_id}_{key}",
                "state_topic": f"{self.prefix}/{key}",
                "availability_topic": f"{self.prefix}/availability",
                "device": device,
            }
            if component == "binary_sensor":
                payload.update({"payload_on": "ON", "payload_off": "OFF"})
            if unit:
                payload["unit_of_measurement"] = unit
            if device_class:
                payload["device_class"] = device_class
            if state_class:
                payload["state_class"] = state_class
            if key in diagnostic_entities:
                payload["entity_category"] = "diagnostic"
            if key in disabled_raw_entities:
                payload["enabled_by_default"] = False
            topic = f"{self.discovery}/{component}/{self.device_id}/{key}/config"
            self.client.publish(topic, json.dumps(payload), retain=True)
        # Discovery describes permanent device capabilities. A temporary
        # fallback or missing RS485 value must never delete an HA entity.
        payload = {
            "name": "Drift – Styring",
            "unique_id": f"{self.device_id}_mode",
            "command_topic": f"{self.prefix}/mode/set",
            "state_topic": f"{self.prefix}/mode",
            "availability_topic": f"{self.prefix}/availability",
            "options": list(MODE_LABELS.values()),
            "icon": "mdi:fan-auto",
            "device": device,
        }
        topic = f"{self.discovery}/select/{self.device_id}/mode/config"
        self.client.publish(topic, json.dumps(payload), retain=True)
        fireplace_payload = {
            "name": "Drift – Pejs-ventilation (15 min)",
            "unique_id": f"{self.device_id}_fireplace_gateway",
            "command_topic": f"{self.prefix}/fireplace_gateway/set",
            "state_topic": f"{self.prefix}/fireplace_gateway",
            "availability_topic": f"{self.prefix}/availability",
            "payload_on": "ON",
            "payload_off": "OFF",
            "icon": "mdi:fireplace",
            "device": device,
        }
        topic = f"{self.discovery}/switch/{self.device_id}/fireplace_gateway/config"
        self.client.publish(topic, json.dumps(fireplace_payload), retain=True)
        bypass_payload = {
            "name": "Drift – Bypass-request",
            "unique_id": f"{self.device_id}_bypass_request",
            "command_topic": f"{self.prefix}/bypass_request/set",
            "state_topic": f"{self.prefix}/bypass_request",
            "availability_topic": f"{self.prefix}/availability",
            "payload_on": "ON",
            "payload_off": "OFF",
            "icon": "mdi:valve",
            "device": device,
        }
        topic = f"{self.discovery}/switch/{self.device_id}/bypass_request/config"
        self.client.publish(topic, json.dumps(bypass_payload), retain=True)

        filter_interval_payload = {
            "name": "Filter – Interval",
            "unique_id": f"{self.device_id}_filter_interval",
            "command_topic": f"{self.prefix}/filter_interval/set",
            "state_topic": f"{self.prefix}/filter_interval",
            "availability_topic": f"{self.prefix}/availability",
            "min": FILTER_INTERVAL_MIN_DAYS,
            "max": FILTER_INTERVAL_MAX_DAYS,
            "step": 1,
            "unit_of_measurement": "d",
            "mode": "box",
            "icon": "mdi:calendar-range",
            "device": device,
        }
        topic = f"{self.discovery}/number/{self.device_id}/filter_interval/config"
        self.client.publish(topic, json.dumps(filter_interval_payload), retain=True)

        filter_reset_payload = {
            "name": "Filter – Synkroniser nulstilling",
            "unique_id": f"{self.device_id}_filter_reset",
            "command_topic": f"{self.prefix}/filter_reset/set",
            "payload_press": "PRESS",
            "availability_topic": f"{self.prefix}/availability",
            "icon": "mdi:air-filter",
            "device": device,
        }
        topic = f"{self.discovery}/button/{self.device_id}/filter_reset/config"
        self.client.publish(topic, json.dumps(filter_reset_payload), retain=True)
        restart_payload = {
            "name": "Gateway – Genstart",
            "unique_id": f"{self.device_id}_restart_gateway",
            "command_topic": f"{self.prefix}/restart_gateway/set",
            "payload_press": "PRESS",
            "availability_topic": f"{self.prefix}/availability",
            "icon": "mdi:restart",
            "entity_category": "diagnostic",
            "device": device,
        }
        restart_topic = (
            f"{self.discovery}/button/{self.device_id}/restart_gateway/config"
        )
        self.client.publish(
            restart_topic, json.dumps(restart_payload), retain=True
        )

    @staticmethod
    def format_payload(value: object) -> str:
        if isinstance(value, bool):
            return "ON" if value else "OFF"
        if isinstance(value, float):
            return f"{value:.2f}"
        return str(value)

    def publish(self, key: str, value: object, *, source: str | None = None):
        if self.state.get(key) == value:
            return
        self.state[key] = value
        if source:
            self.state[f"{key}_source"] = source
            self.state[f"{key}_updated_at"] = time.time()
        payload = self.format_payload(value)
        if self.mqtt_enabled:
            self.client.publish(f"{self.prefix}/{key}", payload, retain=self.retain)
        log = LOG.info if key in INFO_STATE_KEYS else LOG.debug
        log("%s=%s", key, payload)

    def publish_temperature(self, key: str, value: object, *, source: str | None = None):
        self.publish(key, value, source=source)
        timestamp_keys = SENSOR_SAMPLE_TIMESTAMPS.get(key)
        if (
            timestamp_keys
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and -35 <= float(value) <= 100
        ):
            self.state[timestamp_keys[0]] = time.monotonic()
            if key in {"supply_temp", "supply_temperature"}:
                self.state["temperature_sample_monotonic"] = time.monotonic()

    def publish_bypass_raw(self, raw: int):
        """Publish the damper status and remember when a travel started.

        A travel only has a known start when the damper was seen leaving an
        end position; after a restart mid-travel the elapsed time is unknown.
        """
        previous = self.state.get("bypass_raw")
        self.publish("bypass_raw", raw)
        self.publish("bypass_active", raw == 255)
        if raw == previous:
            return
        if raw in (0, 255):
            self.state["bypass_travel_started_monotonic"] = None
            self.publish("bypass_travel_direction", None)
        elif previous in (0, 255):
            self.state["bypass_travel_started_monotonic"] = time.monotonic()
            self.publish("bypass_travel_direction", "opening" if previous == 0 else "closing")
        else:
            self.state["bypass_travel_started_monotonic"] = None
            self.publish("bypass_travel_direction", BYPASS_TRAVEL_CODES.get(raw))

    def publish_filter_status(self):
        if not self.filter_enabled:
            return
        elapsed_days = max(0.0, (time.time() - self.filter_reset_epoch) / 86400.0)
        remaining = max(0, math.ceil(self.filter_interval_days - elapsed_days))
        percent = max(
            0,
            min(100, round(remaining / self.filter_interval_days * 100)),
        )
        if remaining <= 0:
            status = "overskredet"
        elif remaining <= 30:
            status = "skift_snart"
        else:
            status = "ok"
        self.publish("filter_interval", self.filter_interval_days)
        self.publish("filter_days_remaining", remaining)
        self.publish("filter_life_percent", percent)
        self.publish("filter_status", status)
        self.publish("filter_alarm", remaining <= 0)
        self.publish("filter_source", "HCP4 synkroniseret")
        self.last_filter_publish = time.monotonic()

    def decode(self, frame: bytes):
        self.last_bus_frame = time.monotonic()
        slave = frame[0]
        fn = frame[1]
        if fn in (3, 4) and len(frame) == 8:
            return  # request, no data payload
        if slave == 0x40 and fn == 16 and len(frame) >= 19:
            register = int.from_bytes(frame[2:4], "big")
            count = int.from_bytes(frame[4:6], "big")
            byte_count = frame[6]
            if register == 180 and count == 5 and byte_count == 10:
                values = [
                    int.from_bytes(frame[index:index + 2], "big")
                    for index in range(7, 17, 2)
                ]
                for key, raw in zip(
                    (
                        "outdoor_temp", "supply_temp", "extract_temp",
                        "exhaust_temp", "hrc2_t5_temperature",
                    ),
                    values,
                ):
                    if 500 <= raw <= 4000:
                        self.publish_temperature(
                            key, raw / 100.0,
                            source="passive_hcp4_hac1_register_180",
                        )
                self.publish_temperature(
                    "supply_temperature", values[1] / 100.0,
                    source="passive_hcp4_hac1_register_181",
                )
            elif register == 185 and count == 5 and byte_count == 10:
                values = [
                    int.from_bytes(frame[index:index + 2], "big")
                    for index in range(7, 17, 2)
                ]
                if (
                    values[0] & 1 == 1
                    and values[2:] == [15, 0x17FE, 0xFF03]
                    and values[1] % 256 == 0
                    and 0 <= values[1] // 256 <= 35
                ):
                    selection = values[1] // 256
                    self.publish(
                        "afterheat_selection",
                        "off" if selection == 0 else selection,
                        source="passive_hcp4_hac1_register_186",
                    )
                    if selection:
                        self.publish(
                            "afterheat_setpoint", selection,
                            source="passive_hcp4_hac1_register_186",
                        )
            return
        if slave == 0x40 and fn == 3 and len(frame) == 15 and frame[2] == 10:
            values = [int.from_bytes(frame[i : i + 2], "big") for i in range(3, 13, 2)]
            # Verificeret mod HRC2-displayet 2026-07-15:
            # 2008/2010 -> 970 -> 710 ppm under naturligt CO2-fald.
            if values[:3] == [0x3000, 0x1100, 0] and 300 <= values[3] <= 10000:
                self.publish("co2", values[3])
            # Registerblok 185-189. Register 186 er verificeret med
            # 20 °C=5120 og 21 °C=5376, altså heltal °C * 256. Register 185
            # er kun verificeret på bit 0 (=1); resten af ordet er ustabile
            # HAC1-statusflag (fx 8193 = 0x2001 observeret i drift), så kun
            # bit 0 kontrolleres.
            elif (
                values[0] & 1 == 1
                and values[2] == 15
                and values[1] % 256 == 0
                and 0 <= values[1] // 256 <= 40
            ):
                selection = values[1] // 256
                self.publish(
                    "afterheat_selection",
                    "off" if selection == 0 else selection,
                    source="passive_hcp4_hac1_register_186",
                )
                if selection:
                    self.publish(
                        "afterheat_setpoint", selection,
                        source="passive_hcp4_hac1_register_186",
                    )
            elif values[2] == 32768 and values[3] == 32768 and values[4] in (0, 16):
                # Registerblok 205-209. Register 209 skifter mellem 0 og 16 og
                # matcher taendt/slukket eftervarme-kald 1:1 i observerede
                # manuelle test (2026-08-31, aabn/luk/setpunkt-test). Det er
                # IKKE en glidende positionsvaerdi -- kun to stabile tilstande
                # er nogensinde set trods gentagne delvise fysiske aabninger.
                if 500 <= values[0] <= 4000:
                    self.publish_temperature(
                        "heating_coil_after_temperature", values[0] / 100.0,
                        source="passive_hcp4_hac1_register_205",
                    )
                if 500 <= values[1] <= 6000:
                    self.publish_temperature(
                        "heating_coil_frost_temperature", values[1] / 100.0,
                        source="passive_hcp4_hac1_register_206",
                    )
                self.publish(
                    "afterheat_active", values[4] == 16,
                    source="passive_hcp4_hac1_register_209",
                )
            return
        if slave != 1:
            return
        if fn == 4:
            values = [int.from_bytes(frame[i : i + 2], "big") for i in range(3, len(frame) - 2, 2)]
            if len(values) == 4:
                # Eksperimentelt matchet mod HRC2-displayet 2026-07-15.
                for legacy_key, canonical_key, raw in zip(
                    ("outdoor_temp", "supply_temp", "extract_temp", "exhaust_temp"),
                    ("outdoor_temperature", "supply_temperature", "extract_temperature", "exhaust_temperature"),
                    values,
                ):
                    value = raw / 100.0
                    self.publish_temperature(legacy_key, value)
                    self.publish_temperature(canonical_key, value)
                self.state["temperature_sample_monotonic"] = time.monotonic()
                self.state["temperature_source"] = "hch5_fc04"
            elif len(values) == 5:
                efficiency, extract_rpm, supply_rpm, bypass_raw, status = values
                self.publish("heat_recovery_efficiency", efficiency)
                self.publish("fan_extract_rpm", extract_rpm)
                self.publish("fan_supply_rpm", supply_rpm)
                # Verificeret 2026-07-17 mod fysisk auto-bypass: 0 = lukket,
                # 255 = helt åben; 64/32 = åbner/lukker (målt 2026-09-23).
                self.publish_bypass_raw(bypass_raw)
                self.publish("status_code", status)
        elif fn == 6:
            register = int.from_bytes(frame[2:4], "big")
            value = int.from_bytes(frame[4:6], "big")
            if register == 66:
                # HAC1 fortsætter med at udsende sit AUTO-sætpunkt, selv når
                # hovedprintet er verificeret på en aktiv gateway-override.
                # Under override publiceres derfor kun den aktive tilbagemåling.
                if self.override_mode is None and not self.fireplace_gateway_active:
                    self.publish("fan_extract_percent", value)
                self.last_manual_write = time.monotonic()
                if time.monotonic() <= self.pending_night_transition_until:
                    extract = self.state.get("fan_extract_percent")
                    supply = self.state.get("fan_supply_percent")
                    if isinstance(extract, int) and isinstance(supply, int):
                        self.night_mode_active = (extract, supply) == (25, 13)
                        self.save_night_mode_state()
                        self.publish("night_mode", self.night_mode_active)
                        self.pending_night_transition_until = 0.0
            elif register == 67:
                if self.override_mode is None and not self.fireplace_gateway_active:
                    self.publish("fan_supply_percent", value)
                self.last_manual_write = time.monotonic()
            elif register == 68:
                self.publish("bypass_request_raw", value)
                if value in (0, 255):
                    self.publish("bypass_request", "ON" if value == 255 else "OFF")
            elif register == 76:
                self.special_mode_flag = value
            elif register == 143 and value:
                self.publish("command_raw", value)
                now = time.monotonic()
                # 176 er kun en generisk afslutning og må ikke blokere en
                # efterfølgende, ægte natdriftskommando. Auto-bypass viste
                # derimod live 205 -> 172 den 2026-07-15 og må ikke
                # fejlklassificeres som natdrift.
                if value in (189, 200, 205):
                    self.last_explicit_mode_command = now
                elif value == 172 and now - self.last_explicit_mode_command > 10.0:
                    # Controlled HCP4 test: a bare 172 followed by 25/13
                    # enabled night mode; the next bare 172 restored 51/39.
                    self.pending_night_transition_until = now + 2.0
                if value == 168:
                    self.filter_command_until = time.monotonic() + 2.0
                # Verificeret i komplette live-overgange 2026-07-15:
                # AUTO indeholder 172 før fanparret forlader manuel trin 3;
                # manuel trin 3 indeholder 189 før fanparret bliver 85/73.
                # 176 er en generisk afslutning og ignoreres som modeflag.
                if value == 172 and self.override_mode is None:
                    self.pending_external_auto_until = time.monotonic() + 5.0
                    self.pending_external_manual3_until = 0.0
                elif value == 189 and self.override_mode is None:
                    self.pending_external_manual3_until = time.monotonic() + 5.0
                    self.pending_external_auto_until = 0.0
            elif register == 168:
                # Verified live: HCP4 writes 3 for 90 days and 12 for 360
                # days, bracketed by command register 143=168.
                if (
                    self.filter_enabled
                    and time.monotonic() <= self.filter_command_until
                    and 3 <= value <= 12
                ):
                    self.filter_interval_days = value * 30
                    self.filter_reset_epoch = time.time()
                    self.save_filter_state()
                    self.publish_filter_status()
                    LOG.info(
                        "HCP4 filter reset observed: %s days",
                        self.filter_interval_days,
                    )
            elif register == 146:
                self.publish("hac1_connected", value == 1)
            self.update_mode()

    def update_mode(self):
        extract = self.state.get("fan_extract_percent")
        supply = self.state.get("fan_supply_percent")
        if isinstance(extract, int) and isinstance(supply, int):
            if self.auto_command_pending and self.auto_command_start_pair is not None:
                start_extract, start_supply = self.auto_command_start_pair
                changed = (
                    (extract - start_extract) ** 2 + (supply - start_supply) ** 2
                    > 16
                )
                if changed:
                    self.auto_command_pending = False
                    self.auto_command_start_pair = None
                    self.external_mode = "auto"
                    self.save_external_mode_state()
                    self.publish("control_status", "idle")
                    LOG.info("HRC-AUTO bekræftet af HAC1 fanpar-readback")
                elif time.monotonic() > self.auto_command_until:
                    self.auto_command_pending = False
                    self.auto_command_start_pair = None
                    self.publish("control_status", "auto_readback_failed")
                    LOG.error("HRC-AUTO blev ikke bekræftet af ændret fanpar")
            manual3_distance = (extract - 85) ** 2 + (supply - 73) ** 2
            if (
                time.monotonic() <= self.pending_external_manual3_until
                and manual3_distance <= 100
            ):
                self.external_mode = "manual_3"
                self.pending_external_manual3_until = 0.0
                self.save_external_mode_state()
                LOG.info("Ekstern manuel trin 3 verificeret af kommando og fanpar")
            if (
                self.external_mode == "manual_3"
                and time.monotonic() <= self.pending_external_auto_until
                and manual3_distance > 100
            ):
                self.external_mode = "auto"
                self.pending_external_auto_until = 0.0
                self.save_external_mode_state()
                LOG.info("Ekstern AUTO verificeret af kommando og ændret fanpar")
            if self.fireplace_gateway_active:
                self.publish("fireplace", True)
                self.publish("standby", False)
                self.publish("operating_mode", "fireplace_gateway")
                return
            current_level = min(
                LEVEL_TARGETS,
                key=lambda label: (
                    (extract - LEVEL_TARGETS[label][0]) ** 2
                    + (supply - LEVEL_TARGETS[label][1]) ** 2
                ),
            )
            self.publish("current_level", current_level)
            if self.auto_command_pending:
                return
        pairs = {
            (25, 13): "manual_1",
            (55, 43): "manual_2",
            (85, 73): "manual_3",
        }
        fireplace = extract == 0 and supply > 0 and self.special_mode_flag == 1
        standby = extract == 0 and supply == 0 and self.special_mode_flag == 1
        if self.fireplace_gateway_active:
            fireplace = True
        self.publish("fireplace", fireplace)
        self.publish("standby", standby)
        if fireplace:
            mode = "fireplace"
        elif standby:
            mode = "standby"
        elif (extract, supply) == (100, 88):
            # AUTO kan nå samme maksimale setpunkt som manuelt boost.
            mode = "boost" if self.override_mode == "boost" else "auto_or_boost"
        elif self.override_mode is not None:
            mode = self.override_mode
        elif self.external_mode == "manual_3":
            mode = "manual_3"
        elif self.external_mode == "auto":
            mode = "auto_or_scheduled"
        else:
            mode = pairs.get((extract, supply), "auto_or_scheduled")
        self.publish("operating_mode", mode)
        if self.override_mode is None:
            if mode == "standby":
                selected = "auto"
            else:
                selected = mode if mode in CONTROL_STEPS else "auto"
            self.publish("mode", MODE_LABELS[selected])

    @staticmethod
    def write_frame(register: int, value: int) -> bytes:
        body = bytes([1, 6, register >> 8, register & 0xFF, value >> 8, value & 0xFF])
        return body + crc16(body).to_bytes(2, "little")

    @staticmethod
    def read_frame(start: int, count: int, slave: int = 1, function: int = 3) -> bytes:
        body = bytes([slave, function, start >> 8, start & 0xFF, count >> 8, count & 0xFF])
        return body + crc16(body).to_bytes(2, "little")

    @staticmethod
    def write_multiple_frame(slave: int, start: int, values: list[int]) -> bytes:
        payload = b"".join(int(value).to_bytes(2, "big") for value in values)
        body = bytes([
            slave, 16, start >> 8, start & 0xFF,
            len(values) >> 8, len(values) & 0xFF, len(payload),
        ]) + payload
        return body + crc16(body).to_bytes(2, "little")

    def request_capture_toggle(self) -> None:
        self.capture_toggle_requested = True

    def request_controller_reload(self) -> None:
        self.controller_reload_requested = True

    def serial_read(self, ser: serial.Serial, size: int) -> bytes:
        data = ser.read(size)
        self.direction_capture.record_rx(data)
        return data

    def serial_write(self, ser: serial.Serial, data: bytes, reason: str) -> int:
        written = ser.write(data)
        if written:
            self.direction_capture.record_tx(data[:written], reason)
        return written

    def wait_quiet(self, ser: serial.Serial, seconds: float = 0.015) -> bool:
        deadline = time.monotonic() + 0.3
        quiet_since = time.monotonic()
        while time.monotonic() < deadline:
            waiting = ser.in_waiting
            if waiting:
                self.serial_read(ser, waiting)
                quiet_since = time.monotonic()
            elif time.monotonic() - quiet_since >= seconds:
                return True
            time.sleep(0.001)
        return False

    def write_one(self, ser: serial.Serial, register: int, value: int):
        if not self.wait_quiet(ser):
            raise RuntimeError("RS485-bussen blev ikke stille")
        self.serial_write(ser, self.write_frame(register, value), "CONTROL")
        ser.flush()
        time.sleep(0.035)
        if ser.in_waiting:
            self.serial_read(ser, ser.in_waiting)

    def write_pair(self, ser: serial.Serial, extract: int, supply: int):
        # Samme rækkefølge som observeret fra HAC1.
        self.write_one(ser, 67, supply)
        self.write_one(ser, 66, extract)

    def _write_afterheat_block(
        self, ser: serial.Serial, start: int, values: list[int], reason: str
    ) -> None:
        last_block_at = getattr(self, "last_afterheat_block_at", None)
        if last_block_at is not None:
            remaining = 0.8 - (time.monotonic() - last_block_at)
            if remaining > 0:
                time.sleep(remaining)
        frame = self.write_multiple_frame(0x40, start, values)
        # HAC1 answers ~50 ms later with the standard 8-byte FC16 ack
        # (40 10 00 B4 00 05 4F 3D). Captures 2026-09-23 showed its last CRC
        # byte intermittently garbled (4F FF / 4F CF) or missing entirely,
        # so the six header bytes identify the ack. The ack must be read
        # immediately: read later, a valid ack falls outside the own-echo
        # window and master arbitration mistakes it for an HCP4 write and
        # releases the bus. After the header, one more read collects the
        # CRC bytes so they are never left in the buffer.
        header = frame[:6]
        for _attempt in range(2):
            if not self.wait_quiet(ser):
                raise RuntimeError("RS485 bus did not become quiet")
            self.serial_write(ser, frame, reason)
            ser.flush()
            deadline = time.monotonic() + 0.5
            received = bytearray()
            header_seen = False
            while time.monotonic() < deadline:
                received.extend(self.serial_read(ser, 256))
                index = received.find(header)
                if index >= 0 and (header_seen or len(received) >= index + 8):
                    self.last_afterheat_block_at = time.monotonic()
                    return
                header_seen = index >= 0
        raise RuntimeError(f"missing FC16 acknowledgement for register {start}")

    def _afterheat_temperature_words(self) -> list[int]:
        def valid(key: str) -> bool:
            value = self.state.get(key)
            return isinstance(value, (int, float)) and -35 <= float(value) <= 100

        # Register 184 is T5, the room sensor in the HRC2 remote. It is not
        # live once Pi replaces HCP4, and HAC1 regulates afterheat on its own
        # T2AH (register 205), so T5 must never block the chain: keep the
        # value HAC1 already holds and fall back to T3 extract air, the other
        # room reference selectable on the HRC2 remote.
        t5_key = "hrc2_t5_temperature" if valid("hrc2_t5_temperature") else "extract_temp"
        keys = (
            "outdoor_temp", "supply_temp", "extract_temp", "exhaust_temp",
            t5_key,
        )
        words: list[int] = []
        for key in keys:
            if not valid(key):
                raise RuntimeError(f"afterheat temperature unavailable: {key}")
            words.append(round(float(self.state[key]) * 100))
        return words

    def write_afterheat_temperature_block(self, ser: serial.Serial) -> list[int]:
        """Refresh the verified live T1..T5 telemetry block independently."""
        temperatures = self._afterheat_temperature_words()
        self._write_afterheat_block(
            ser, 180, temperatures, "CONTROL_AFTERHEAT_TEMPERATURES"
        )
        return temperatures

    def refresh_afterheat_temperature_block_if_due(
        self, ser: serial.Serial, *, now: float | None = None
    ) -> bool:
        now = time.monotonic() if now is None else now
        if now - self.last_afterheat_temperature_refresh < 4.0:
            return False
        if not self.controller.hardware_writes_allowed():
            return False
        self.last_afterheat_temperature_refresh = now
        try:
            self.write_afterheat_temperature_block(ser)
        except Exception as error:
            LOG.error("Afterheat temperature refresh failed: %s", error)
            return False
        return True

    def write_afterheat_setpoint(self, ser: serial.Serial, value: int | None) -> int | None:
        """Write only the verified HAC1 thermostat block.

        HCP4 refreshes FC16 blocks 180..184 and 185..189 every four seconds.
        The 180..184 telemetry block is refreshed separately so a setpoint
        update cannot rewrite temperature data. Register 180 carries the live
        outdoor temperature used by HAC1's 15 C afterheat lockout.
        The enabled 185 block is CRC-verified at 10 C. OFF uses the same
        verified constants with register 186 set to zero; repeated OFF
        captures reconstructed the complete frame including CRC E5 E1.
        """
        if value is not None and not 10 <= value <= 35:
            raise ValueError("afterheat setpoint must be 10..35 C or OFF")
        command = [1, 0 if value is None else value * 256, 15, 0x17FE, 0xFF03]
        self._write_afterheat_block(
            ser, 185, command, "CONTROL_AFTERHEAT_THERMOSTAT"
        )
        if value is None:
            self.publish("afterheat_selection", "off", source="pi_active_hac1_off_command")
        else:
            self.publish("afterheat_selection", value, source="pi_active_hac1_command")
            self.publish("afterheat_setpoint", value, source="pi_active_hac1_command")
        return value

    def write_hrc_auto_sequence(
        self, ser: serial.Serial, restore_pair: tuple[int, int]
    ):
        # To komplette passive HRC2-optagelser viste samme afslutning:
        # register 143=200 gentages, derefter 143=172, hvorefter HAC1 selv
        # overtager register 66/67. Ingen fanværdier antages her.
        for _ in range(3):
            self.write_one(ser, 143, 200)
        for _ in range(3):
            self.write_one(ser, 143, 172)
        self.write_pair(ser, *restore_pair)
        time.sleep(0.15)
        self.write_pair(ser, *restore_pair)
        self.auto_command_start_pair = CONTROL_STEPS.get(
            self.override_mode or "", self.read_fan_pair(ser) or restore_pair
        )
        self.auto_command_pending = True
        self.auto_command_until = time.monotonic() + 8.0

    def write_hrc_manual_sequence(
        self, ser: serial.Serial, target: tuple[int, int], entering_manual: bool
    ):
        # Den komplette HRC2-optagelse viste 176 før hvert manuelt valg,
        # derefter 172 ved indgang til manuel og 189 ved det valgte trin.
        self.write_one(ser, 143, 176)
        time.sleep(0.35)
        if entering_manual:
            self.write_one(ser, 143, 172)
        self.write_one(ser, 143, 189)
        self.write_pair(ser, *target)
        time.sleep(0.15)
        self.write_pair(ser, *target)

    def read_fan_pair(self, ser: serial.Serial) -> tuple[int, int] | None:
        request = self.read_frame(66, 2)
        for _attempt in range(4):
            if not self.wait_quiet(ser):
                continue
            self.serial_write(ser, request, "ACTIVE_READ")
            ser.flush()
            deadline = time.monotonic() + 0.4
            received = bytearray()
            while time.monotonic() < deadline:
                received.extend(self.serial_read(ser, 256))
                for offset in range(max(0, len(received) - 256), len(received) - 8):
                    frame = bytes(received[offset : offset + 9])
                    if frame[:3] != b"\x01\x03\x04":
                        continue
                    if crc16(frame[:-2]) != int.from_bytes(frame[-2:], "little"):
                        continue
                    return (
                        int.from_bytes(frame[3:5], "big"),
                        int.from_bytes(frame[5:7], "big"),
                    )
        return None

    def read_register_block(
        self, ser: serial.Serial, slave: int, start: int, count: int, function: int = 3
    ) -> list[int] | None:
        request = self.read_frame(start, count, slave=slave, function=function)
        expected_length = 5 + count * 2
        for _attempt in range(4):
            if not self.wait_quiet(ser):
                continue
            self.serial_write(ser, request, "ACTIVE_READ")
            ser.flush()
            deadline = time.monotonic() + 0.18
            received = bytearray()
            while time.monotonic() < deadline:
                received.extend(self.serial_read(ser, 256))
                for offset in range(
                    max(0, len(received) - 256),
                    len(received) - expected_length + 1,
                ):
                    frame = bytes(received[offset : offset + expected_length])
                    if frame[:3] != bytes([slave, function, count * 2]):
                        continue
                    if crc16(frame[:-2]) != int.from_bytes(frame[-2:], "little"):
                        continue
                    # A CRC-valid response to an active read also proves that the
                    # RS485 bus is alive. Without this, installations with no
                    # unsolicited frames are restarted by the watchdog every 60 s.
                    self.last_bus_frame = time.monotonic()
                    return [
                        int.from_bytes(frame[index : index + 2], "big")
                        for index in range(3, len(frame) - 2, 2)
                    ]
        return None

    def _mirror_active_block(self, slave: int, function: int, start: int, values: list[int]) -> None:
        """Re-broadcast a successful active read so HA's passive parser still
        sees it, exactly as it would have from HCP4's own polling traffic.

        Without this, Home Assistant's receive-only integration loses these
        fields the moment Pi becomes bus master, because it decodes the raw
        RS485 stream itself and never calls this gateway's own state/API.
        """
        if getattr(self, "tcp_mirror", None) is None:
            return
        request = self.read_frame(start, len(values), slave=slave, function=function)
        body = bytes([slave, function, len(values) * 2]) + b"".join(
            value.to_bytes(2, "big") for value in values
        )
        self.tcp_mirror.broadcast(request + body + crc16(body).to_bytes(2, "little"))

    def poll_master_blocks(self, ser: serial.Serial):
        """Poll only blocks verified on HCH5 MK1 with HCP4 disconnected."""
        fan_pair = self.read_fan_pair(ser)
        temperatures = self.read_register_block(ser, 1, 0, 4, function=4)
        if temperatures is not None:
            self._mirror_active_block(1, 4, 0, temperatures)
        status = self.read_register_block(ser, 1, 4, 5, function=4)
        if status is not None:
            self._mirror_active_block(1, 4, 4, status)
        hac200 = self.read_register_block(ser, 0x40, 200, 5)
        if hac200 is not None:
            self._mirror_active_block(0x40, 3, 200, hac200)
        # Keep the two remaining native HCP4 blocks alive even though their
        # individual fields are not named yet.
        main1024 = self.read_register_block(ser, 1, 1024, 6)
        if main1024 is not None:
            self._mirror_active_block(1, 3, 1024, main1024)
        main1032 = self.read_register_block(ser, 1, 1032, 4)
        if main1032 is not None:
            self._mirror_active_block(1, 3, 1032, main1032)
        hac205 = self.read_register_block(ser, 0x40, 205, 5)
        if hac205 is not None:
            self._mirror_active_block(0x40, 3, 205, hac205)
        if fan_pair is not None:
            self.publish("fan_extract_percent", fan_pair[0])
            self.publish("fan_supply_percent", fan_pair[1])
        if temperatures is not None:
            for legacy_key, canonical_key, raw in zip(
                ("outdoor_temp", "supply_temp", "extract_temp", "exhaust_temp"),
                ("outdoor_temperature", "supply_temperature", "extract_temperature", "exhaust_temperature"),
                temperatures,
            ):
                value = raw / 100.0
                self.publish_temperature(legacy_key, value)
                self.publish_temperature(canonical_key, value)
            self.state["temperature_sample_monotonic"] = time.monotonic()
            self.state["temperature_source"] = "hch5_fc04_active"
        if status is not None:
            humidity_raw, extract_rpm, supply_rpm, bypass_raw, status_code = status
            self.publish("heat_recovery_efficiency", humidity_raw)
            self.publish("fan_extract_rpm", extract_rpm)
            self.publish("fan_supply_rpm", supply_rpm)
            self.publish_bypass_raw(bypass_raw)
            self.publish("status_code", status_code)
            measured_rh = round(humidity_raw * 100 / 255, 1) if 0 < humidity_raw <= 255 else None
            extract_temp = self.state.get("extract_temp")
            exhaust_temp = self.state.get("exhaust_temp")
            relative_rh = None
            if measured_rh is not None and isinstance(extract_temp, (int, float)) and isinstance(exhaust_temp, (int, float)):
                saturation = lambda temperature: 6.112 * math.exp(17.62 * temperature / (243.12 + temperature))
                relative_rh = round(measured_rh * saturation(exhaust_temp) / saturation(extract_temp), 1)
            self.publish("measured_relative_humidity", measured_rh)
            self.publish("relative_humidity", relative_rh)
            self.publish("humidity", relative_rh)
        if hac200 is not None and hac200[:3] == [0x3000, 0x1100, 0]:
            if 300 <= hac200[3] <= 10000:
                self.publish("co2", hac200[3])
            self.publish("hac1_connected", True)
        elif hac200 is None:
            self.publish("hac1_connected", False)
        if main1024 is not None:
            self.publish("mk1_block_1024", ",".join(map(str, main1024)))
        if main1032 is not None:
            self.publish("mk1_block_1032", ",".join(map(str, main1032)))
        if hac205 is not None:
            self.publish("hac1_block_205", ",".join(map(str, hac205)))
            # Register 205 is T2AH: air temperature after the HAC1 heating
            # coil. Ordinary unit T2 (supply_temp) is the temperature before
            # the coil, so together they form the valid air-side delta.
            if len(hac205) == 5 and 500 <= hac205[0] <= 4000:
                self.publish_temperature("heating_coil_after_temperature", hac205[0] / 100.0)
            if len(hac205) == 5 and 500 <= hac205[1] <= 6000:
                self.publish_temperature("heating_coil_frost_temperature", hac205[1] / 100.0)
            # Same verified register-209 semantics as decode(): 0 is inactive
            # and 16 is active when words 207/208 contain the HAC1 markers.
            if len(hac205) == 5 and hac205[2:4] == [0x8000, 0x8000]:
                self.publish("afterheat_active", hac205[4] == 16)
        if any(value is not None for value in (temperatures, status, hac200)):
            self.last_bus_frame = time.monotonic()
        self.last_master_poll = time.monotonic()

    def poll_afterheat_setpoint(self, ser: serial.Serial):
        values = self.read_register_block(ser, 0x40, 185, 5)
        if values is None:
            return
        # read_register_block consumes the response internally. Reconstruct
        # the same valid RTU response for receive-only raw-TCP consumers.
        if getattr(self, "tcp_mirror", None) is not None:
            body = bytes([0x40, 0x03, len(values) * 2]) + b"".join(
                value.to_bytes(2, "big") for value in values
            )
            self.tcp_mirror.broadcast(body + crc16(body).to_bytes(2, "little"))
        if (
            values[0] & 1 == 1
            and values[2] == 15
            and values[1] % 256 == 0
            and 0 <= values[1] <= 40 * 256
        ):
            selection = values[1] // 256
            self.publish(
                "afterheat_selection",
                "off" if selection == 0 else selection,
                source="pi_active_hac1_register_186",
            )
            if selection:
                self.publish(
                    "afterheat_setpoint", selection,
                    source="pi_active_hac1_register_186",
                )

    def poll_hrc2_t5(self, ser: serial.Serial):
        # Register 184 on slave 0x40 er HRC2-fjernbetjeningens egen
        # temperaturføler (T5). Verificeret 2026-08-28 mod HRC2-displayet
        # (rå 2190 = 21.90 stemte med skærmens 21 grader). Bussen
        # udsender aldrig dette register af sig selv, så det skal
        # forespørges aktivt her og genudsendes til raw-TCP-lytterne.
        values = self.read_register_block(ser, 0x40, 184, 1)
        if values is None:
            return
        if getattr(self, "tcp_mirror", None) is not None:
            body = bytes([0x40, 0x03, len(values) * 2]) + b"".join(
                value.to_bytes(2, "big") for value in values
            )
            self.tcp_mirror.broadcast(body + crc16(body).to_bytes(2, "little"))
        raw = values[0]
        if 500 <= raw <= 4000:
            self.publish_temperature("hrc2_t5_temperature", raw / 100.0)

    def poll_temperature_snapshot(self, ser: serial.Serial):
        """Read all seven temperatures in one FC03 transaction, without writes."""
        values = self.read_register_block(ser, 0x40, 180, 30)
        if values is None:
            return
        if getattr(self, "tcp_mirror", None) is not None:
            # Pair the request and response for unambiguous decoder routing.
            request = self.read_frame(180, 30, slave=0x40)
            body = bytes([0x40, 3, 60]) + b"".join(
                value.to_bytes(2, "big") for value in values
            )
            self.tcp_mirror.broadcast(request + body + crc16(body).to_bytes(2, "little"))

        def temperature(raw: int):
            if raw in (0x7FFF, 0x8000):
                return None
            signed = raw - 65536 if raw >= 32768 else raw
            result = signed / 100.0
            return result if -35 <= result <= 100 else None

        # 180=T1, 181=T2 before the external afterheater, 182=T3, 183=T4,
        # 184=T5, 205=T2AH after the coil, 206=frost/water-side sensor.
        snapshot = {
            "outdoor_temperature": temperature(values[0]),
            "supply_temperature": temperature(values[1]),
            "extract_temperature": temperature(values[2]),
            "exhaust_temperature": temperature(values[3]),
            "room_temperature": temperature(values[4]),
            "heating_coil_after_temperature": temperature(values[25]),
            "heating_coil_frost_temperature": temperature(values[26]),
        }
        aliases = {
            "outdoor_temperature": "outdoor_temp",
            "supply_temperature": "supply_temp",
            "extract_temperature": "extract_temp",
            "exhaust_temperature": "exhaust_temp",
            "room_temperature": "hrc2_t5_temperature",
        }
        for key, value in snapshot.items():
            if value is None:
                continue
            self.publish_temperature(key, value)
            if key in aliases:
                self.publish_temperature(aliases[key], value)
        if snapshot["supply_temperature"] is not None:
            self.state["temperature_sample_monotonic"] = time.monotonic()
            self.state["temperature_source"] = "hac1_snapshot_180_209"
        if len(values) >= 30:
            self.publish("afterheat_active", values[29] == 16)

    def poll_bypass_request(self, ser: serial.Serial):
        # Physical HCP4 capture: slave 1, register 68, 0=OFF and 255=ON.
        # This request is separate from the physical damper readback.
        values = self.read_register_block(ser, 1, 68, 1)
        if values is None:
            return
        if getattr(self, "tcp_mirror", None) is not None:
            body = bytes([1, 0x03, len(values) * 2]) + b"".join(
                value.to_bytes(2, "big") for value in values
            )
            self.tcp_mirror.broadcast(body + crc16(body).to_bytes(2, "little"))
        raw = values[0]
        self.publish("bypass_request_raw", raw)
        if raw in (0, 255):
            self.publish("bypass_request", "ON" if raw == 255 else "OFF")
        else:
            LOG.error("Ugyldig bypass-request readback fra register 68: %s", raw)

    def write_bypass_request(self, ser: serial.Serial, requested: str):
        requested = requested.lower()
        if requested not in {"off", "on"}:
            raise ValueError("bypass request must be off or on")
        if requested == "on" and self.fireplace_gateway_active:
            raise RuntimeError("bypass cannot be enabled during fireplace mode")
        desired = 255 if requested == "on" else 0
        current_values = self.read_register_block(ser, 1, 68, 1)
        if current_values is None or current_values[0] not in (0, 255):
            raise RuntimeError(f"unsafe bypass pre-read: {current_values}")
        if current_values[0] != desired:
            self.write_one(ser, 68, desired)
        actual = None
        for _attempt in range(3):
            values = self.read_register_block(ser, 1, 68, 1)
            if values is not None:
                actual = values[0]
                if actual == desired:
                    break
            time.sleep(0.1)
        if actual != desired:
            self.publish("control_status", "bypass_readback_mismatch")
            raise RuntimeError(f"bypass readback mismatch: {actual}, expected {desired}")
        self.publish("bypass_request_raw", actual)
        self.publish("bypass_request", "ON" if actual == 255 else "OFF")
        return requested

    def verify_control_pair(self, ser: serial.Serial):
        if self.override_mode is None:
            return
        actual = self.read_fan_pair(ser)
        if actual is None:
            self.publish("control_status", "readback_failed")
            return
        extract, supply = actual
        self.publish("fan_extract_percent", extract)
        self.publish("fan_supply_percent", supply)
        self.update_mode()
        expected = CONTROL_STEPS[self.override_mode]
        self.publish("control_status", "active" if actual == expected else "readback_mismatch")
        LOG.info(
            "Kontrol læst tilbage: %s/%s (forventet %s/%s)",
            extract,
            supply,
            *expected,
        )

    def write_fireplace_pattern(
        self,
        ser: serial.Serial,
        bypass_request: int,
        reg76: int,
        extract: int,
        supply: int,
    ):
        # Nøjagtig rækkefølge fra den rene passive HRC2-optagelse.
        self.write_one(ser, 68, bypass_request)
        self.write_one(ser, 76, reg76)
        self.write_one(ser, 67, supply)
        self.write_one(ser, 66, extract)

    def publish_fireplace_timer(self):
        if not self.fireplace_gateway_active:
            self.publish("fireplace_remaining", 0)
            return
        remaining = max(0.0, self.fireplace_until_monotonic - time.monotonic())
        self.publish("fireplace_remaining", math.ceil(remaining / 60.0))

    def start_fireplace(self, ser: serial.Serial):
        if self.fireplace_gateway_active:
            return
        if self.override_mode is not None:
            self.publish("control_status", "fireplace_rejected_fan_override")
            return
        pair = self.read_fan_pair(ser)
        bypass_request_values = self.read_register_block(ser, 1, 68, 1)
        reg76_values = self.read_register_block(ser, 1, 76, 1)
        if pair is None or bypass_request_values is None or reg76_values is None:
            self.publish("control_status", "fireplace_read_failed")
            return
        bypass_request = bypass_request_values[0]
        reg76 = reg76_values[0]
        extract, supply = pair
        if bypass_request != 0 or reg76 != 0 or not (0 < supply <= 100):
            LOG.error(
                "Pejs afvist fra uventet tilstand: bypass_request=%s reg76=%s pair=%s/%s",
                bypass_request,
                reg76,
                extract,
                supply,
            )
            self.publish("control_status", "fireplace_invalid_start_state")
            return
        self.fireplace_restore = (bypass_request, reg76, extract, supply)
        self.fireplace_until_epoch = time.time() + FIREPLACE_DURATION_SECONDS
        self.fireplace_until_monotonic = time.monotonic() + FIREPLACE_DURATION_SECONDS
        try:
            self.write_fireplace_pattern(ser, 0, 1, 0, supply)
        except Exception:
            LOG.exception("Pejs kunne ikke startes; gendanner")
            self.write_fireplace_pattern(ser, bypass_request, reg76, extract, supply)
            self.fireplace_restore = None
            self.publish("control_status", "fireplace_write_failed")
            return
        self.fireplace_gateway_active = True
        self.last_fireplace_write = time.monotonic()
        self.special_mode_flag = 1
        self.save_fireplace_state()
        self.publish("fireplace_gateway", "ON")
        self.publish("fireplace", True)
        self.publish("fan_extract_percent", 0)
        self.publish("fan_supply_percent", supply)
        self.publish("operating_mode", "fireplace_gateway")
        self.publish("control_status", "fireplace_active")
        self.publish_fireplace_timer()
        LOG.info("Pejs-ventilation startet i 15 minutter med indblæsning %s", supply)

    def resume_fireplace(self, ser: serial.Serial):
        if self.startup_fireplace is None:
            return
        saved = self.startup_fireplace
        self.startup_fireplace = None
        remaining = float(saved["until"]) - time.time()
        if remaining <= 0:
            self.save_fireplace_state()
            return
        self.fireplace_restore = tuple(saved["restore"])
        bypass_request, reg76, _extract, supply = self.fireplace_restore
        self.fireplace_gateway_active = True
        self.fireplace_until_epoch = float(saved["until"])
        self.fireplace_until_monotonic = time.monotonic() + remaining
        self.write_fireplace_pattern(ser, 0, 1, 0, supply)
        self.last_fireplace_write = time.monotonic()
        self.special_mode_flag = 1
        self.publish("fireplace_gateway", "ON")
        self.publish("fireplace", True)
        self.publish("fan_extract_percent", 0)
        self.publish("fan_supply_percent", supply)
        self.publish("operating_mode", "fireplace_gateway")
        self.publish("control_status", "fireplace_active")
        self.publish_fireplace_timer()
        LOG.info("Gemt Pejs-ventilation genoptaget efter opstart")

    def stop_fireplace(self, ser: serial.Serial, clear_saved_state: bool = True):
        restored_pair: tuple[int, int] | None = None
        if self.fireplace_restore is not None:
            bypass_request, reg76, extract, supply = self.fireplace_restore
            restored_pair = (extract, supply)
            self.write_fireplace_pattern(ser, bypass_request, reg76, extract, supply)
            time.sleep(0.15)
            self.write_fireplace_pattern(ser, bypass_request, reg76, extract, supply)
        self.fireplace_gateway_active = False
        self.fireplace_restore = None
        self.special_mode_flag = 0
        if clear_saved_state:
            self.save_fireplace_state()
        self.publish("fireplace_gateway", "OFF")
        self.publish("fireplace", False)
        self.publish("fireplace_remaining", 0)
        if restored_pair is not None:
            self.publish("fan_extract_percent", restored_pair[0])
            self.publish("fan_supply_percent", restored_pair[1])
            self.update_mode()
        self.publish("mode", MODE_LABELS["auto"])
        self.publish("control_status", "idle")
        LOG.info("Pejs-ventilation stoppet og AUTO-værdier gendannet")

    def apply_control_command(self, ser: serial.Serial, mode: str):
        if self.fireplace_gateway_active:
            if mode == "auto":
                self.stop_fireplace(ser)
            else:
                self.publish("control_status", "fan_mode_rejected_fireplace_active")
            return
        if mode == "auto":
            restore_pair = self.restore_pair
            previous_override = self.override_mode
            if restore_pair is None or previous_override is None:
                self.publish("control_status", "auto_no_saved_pair")
                self.update_mode()
                LOG.error("HRC-AUTO afvist: intet gemt AUTO-fanpar")
                return
            self.override_mode = None
            try:
                # write_hrc_auto_sequence bruger previous_override som
                # readback-startpunkt, så sæt det kortvarigt under kaldet.
                self.override_mode = previous_override
                self.write_hrc_auto_sequence(ser, restore_pair)
            except Exception:
                self.override_mode = previous_override
                LOG.exception("HRC-AUTO-sekvens kunne ikke sendes")
                self.publish("control_status", "auto_command_failed")
                self.update_mode()
                return
            self.override_mode = None
            self.restore_pair = None
            self.save_control_state()
            self.publish("fan_extract_percent", restore_pair[0])
            self.publish("fan_supply_percent", restore_pair[1])
            self.publish("control_status", "auto_command_sent")
            self.update_mode()
            LOG.info("Verificeret HRC-AUTO-sekvens sendt; afventer fysisk readback")
            return
        if self.restore_pair is None:
            self.restore_pair = self.read_fan_pair(ser)
            if self.restore_pair is None:
                LOG.error("Mode %s afvist: aktuelle AUTO-værdier kunne ikke læses", mode)
                self.publish("control_status", "read_failed")
                return
            LOG.info("Gemmer værdier til AUTO-gendannelse: %s/%s", *self.restore_pair)
        self.override_mode = mode
        self.write_pair(ser, *CONTROL_STEPS[mode])
        self.last_override_write = time.monotonic()
        self.save_control_state()
        self.publish("mode", MODE_LABELS[mode])
        self.verify_control_pair(ser)
        self.last_control_verify = time.monotonic()
        LOG.info("Mode aktiveret: %s", mode)

    def restore_on_exit(self, ser: serial.Serial):
        if not self.control_enabled:
            return
        if self.fireplace_gateway_active:
            try:
                self.stop_fireplace(ser, clear_saved_state=False)
            except Exception:
                LOG.exception("Kunne ikke gendanne Pejs-værdier ved stop")
        if self.restore_pair is None:
            return
        try:
            self.write_pair(ser, *self.restore_pair)
            time.sleep(0.15)
            self.write_pair(ser, *self.restore_pair)
            LOG.info("Værdier gendannet ved stop: %s/%s", *self.restore_pair)
        except Exception:
            LOG.exception("Kunne ikke gendanne værdier ved stop")

    def run(self):
        serial_cfg = self.cfg["serial"]
        tcp_cfg = self.cfg.get("raw_tcp", {})
        tcp_mirror = None
        if bool(tcp_cfg.get("enabled", False)):
            tcp_mirror = ReadOnlyTcpMirror(
                str(tcp_cfg.get("bind", "127.0.0.1")),
                int(tcp_cfg.get("port", 4196)),
                int(tcp_cfg.get("max_clients", 4)),
            )
            tcp_mirror.start()
        self.tcp_mirror = tcp_mirror
        dashboard_cfg = self.cfg.get("dashboard", {})
        dashboard = None
        if bool(dashboard_cfg.get("enabled", False)):
            dashboard = ControllerDashboardHttpServer(
                str(dashboard_cfg.get("bind", "0.0.0.0")),
                int(dashboard_cfg.get("port", 8080)),
                self.state,
                self.device_name,
                dashboard_cfg.get("preheater_url", "http://127.0.0.1:4197/temperatures"),
                controller_runtime=self.controller,
            )
            dashboard.start()
        self.dashboard = dashboard
        sniffer = RtuSniffer(
            serial_cfg["port"],
            int(serial_cfg.get("baudrate", 19200)),
            serial_cfg.get("parity", "E"),
            int(serial_cfg.get("deduplicate_ms", 250)),
        )
        self.connect()
        if self.master_mode:
            gateway_mode = "hcp4_replacement_test"
        else:
            gateway_mode = "experimental_control" if self.control_enabled else "passive_listener"
        self.publish("gateway_mode", gateway_mode)
        self.publish("control_status", "idle" if self.control_enabled else "read_only")
        self.publish_filter_status()
        if self.night_mode_active is not None:
            self.publish("night_mode", self.night_mode_active)
        if self.startup_fireplace is None:
            self.publish("fireplace_gateway", "OFF")
            self.publish("fireplace_remaining", 0)
        with sniffer.open() as ser:
            self.reader_started_at = time.monotonic()
            LOG.info("Aflæsning startet på %s", serial_cfg["port"])
            self.controller.start()
            try:
                if self.control_enabled and self.startup_mode is not None:
                    startup_mode = self.startup_mode
                    self.startup_mode = None
                    self.apply_control_command(ser, startup_mode)
                    LOG.info("Gemt mode genanvendt efter opstart: %s", startup_mode)
                if self.control_enabled:
                    self.resume_fireplace(ser)
                while self.running:
                    if self.controller_reload_requested:
                        self.controller_reload_requested = False
                        with self.controller.config.lock:
                            self.controller.config.load()
                        LOG.info("Controller configuration reloaded")
                    self.process_controller_hardware(ser)
                    if self.capture_toggle_requested:
                        self.capture_toggle_requested = False
                        if self.direction_capture.running:
                            self.direction_capture.stop()
                        else:
                            self.direction_capture.start()
                    while not self.filter_interval_queue.empty():
                        self.filter_interval_days = self.filter_interval_queue.get()
                        self.save_filter_state()
                        self.publish_filter_status()
                        LOG.info("Filterinterval sat til %s dage", self.filter_interval_days)
                    while not self.filter_reset_queue.empty():
                        self.filter_reset_queue.get()
                        self.filter_reset_epoch = time.time()
                        self.save_filter_state()
                        self.publish_filter_status()
                        LOG.info(
                            "Gateway-filtertimer synkroniseret til %s dage",
                            self.filter_interval_days,
                        )
                    while self.control_enabled and not self.fireplace_queue.empty():
                        requested = self.fireplace_queue.get()
                        if requested:
                            self.start_fireplace(ser)
                        elif self.fireplace_gateway_active:
                            self.stop_fireplace(ser)
                    while self.control_enabled and not self.control_queue.empty():
                        self.apply_control_command(ser, self.control_queue.get())
                    data = self.serial_read(ser, 4096)
                    if data:
                        if tcp_mirror is not None:
                            tcp_mirror.broadcast(data)
                        for frame in sniffer.feed(data):
                            self.decode(frame)
                    if (self.master_mode or bool(self.cfg.get("controller"))) and time.monotonic() - self.last_master_poll >= 3.0:
                        self.poll_master_blocks(ser)
                    if (
                        self.override_mode is not None
                        and time.monotonic() - self.last_override_write >= self.hold_interval
                    ):
                        self.write_pair(ser, *CONTROL_STEPS[self.override_mode])
                        self.last_override_write = time.monotonic()
                    if (
                        self.override_mode is not None
                        and time.monotonic() - self.last_control_verify >= 5.0
                    ):
                        self.verify_control_pair(ser)
                        self.last_control_verify = time.monotonic()
                    if self.fireplace_gateway_active:
                        if time.monotonic() >= self.fireplace_until_monotonic:
                            self.stop_fireplace(ser)
                        elif time.monotonic() - self.last_fireplace_write >= 1.0:
                            assert self.fireplace_restore is not None
                            supply = self.fireplace_restore[3]
                            self.write_fireplace_pattern(ser, 0, 1, 0, supply)
                            self.last_fireplace_write = time.monotonic()
                            self.publish_fireplace_timer()
                    self.refresh_afterheat_temperature_block_if_due(ser)
                    if (
                        self.active_reads_enabled
                        and time.monotonic() - self.last_afterheat_poll >= 15.0
                    ):
                        self.poll_afterheat_setpoint(ser)
                        self.last_afterheat_poll = time.monotonic()
                    if (
                        self.active_reads_enabled
                        and time.monotonic() - self.last_hrc2_t5_poll >= 15.0
                    ):
                        self.poll_hrc2_t5(ser)
                        self.last_hrc2_t5_poll = time.monotonic()
                    if (
                        self.active_reads_enabled
                        and time.monotonic() - self.last_temperature_snapshot_poll >= 10.0
                    ):
                        self.poll_temperature_snapshot(ser)
                        self.last_temperature_snapshot_poll = time.monotonic()
                    if (
                        self.active_reads_enabled
                        and time.monotonic() - self.last_bypass_request_poll >= 10.0
                    ):
                        self.poll_bypass_request(ser)
                        self.last_bypass_request_poll = time.monotonic()
                    if time.monotonic() - self.last_bus_health_publish >= 5.0:
                        now = time.monotonic()
                        age = round(now - self.last_bus_frame, 1) if self.last_bus_frame else 9999
                        self.publish("bus_last_frame_age", age)
                        self.publish("bus_traffic", age < 10)
                        self.last_bus_health_publish = now
                        if now - self.reader_started_at >= 60 and age >= 60:
                            raise RuntimeError(
                                f"Ingen RS485-frames i {age:.1f} sekunder; genstarter gateway"
                            )
                    if time.monotonic() - self.last_filter_publish >= 60.0:
                        self.publish_filter_status()
            finally:
                self.controller.stop()
                self.direction_capture.stop()
                self.restore_on_exit(ser)
                if tcp_mirror is not None:
                    tcp_mirror.stop()
                if dashboard is not None:
                    dashboard.stop()
        if self.mqtt_enabled:
            self.client.publish(f"{self.prefix}/availability", "offline", retain=True)
            self.client.loop_stop()
            self.client.disconnect()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", default="config.yaml")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper()), format="%(asctime)s %(levelname)s %(message)s")
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    gateway = Gateway(config)
    signal.signal(signal.SIGTERM, lambda *_: setattr(gateway, "running", False))
    signal.signal(signal.SIGINT, lambda *_: setattr(gateway, "running", False))
    signal.signal(signal.SIGUSR1, lambda *_: gateway.request_capture_toggle())
    signal.signal(signal.SIGHUP, lambda *_: gateway.request_controller_reload())
    gateway.run()


if __name__ == "__main__":
    main()
