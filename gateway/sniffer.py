"""Read-only Modbus RTU sniffer that consumes a TCP mirror and stores captures.

This module intentionally never transmits on the bus. It connects to a TCP mirror
(e.g. 127.0.0.1:4196), writes raw.bin, frames.jsonl and markers.jsonl into a
timestamped capture directory under /var/lib/dantherm-hch5-ha/sniffer-captures/.
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from passivelink_parser import RtuStreamParser


class SnifferManager:
    def __init__(self, base_dir: str = "/var/lib/dantherm-hch5-ha/sniffer-captures", host: str = "127.0.0.1", port: int = 4196):
        self.base_dir = Path(base_dir)
        self.host = host
        self.port = int(port)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._connected = False
        self._bytes = 0
        self._frames = 0
        self._last_frame_at = None
        self._capture_dir: Path | None = None
        self._raw_fh = None
        self._frames_fh = None
        self._markers_fh = None
        self._byte_offset = 0
        self._frame_index = 0
        self._recent = deque(maxlen=500)
        self.parser = RtuStreamParser(self._on_frame)

    def _ensure_capture_dir(self) -> None:
        if self._capture_dir is not None:
            return
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        self._capture_dir = (self.base_dir / ts)
        self._capture_dir.mkdir(parents=True, exist_ok=False)
        self._raw_fh = open(self._capture_dir / "raw.bin", "ab")
        self._frames_fh = open(self._capture_dir / "frames.jsonl", "ab")
        self._markers_fh = open(self._capture_dir / "markers.jsonl", "ab")

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return {"ok": True, "running": True}
            self._stop.clear()
            self._ensure_capture_dir()
            self._thread = threading.Thread(target=self._run, name="sniffer-thread", daemon=True)
            self._thread.start()
            return {"ok": True, "running": True}

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if not self._thread:
                return {"ok": True, "running": False}
            self._stop.set()
            self._thread.join(timeout=5)
            self._thread = None
            self._connected = False
            # close files
            if self._raw_fh:
                try:
                    self._raw_fh.flush(); self._raw_fh.close()
                except Exception:
                    pass
                self._raw_fh = None
            if self._frames_fh:
                try:
                    self._frames_fh.flush(); self._frames_fh.close()
                except Exception:
                    pass
                self._frames_fh = None
            if self._markers_fh:
                try:
                    self._markers_fh.flush(); self._markers_fh.close()
                except Exception:
                    pass
                self._markers_fh = None
            return {"ok": True, "running": False}

    def marker(self, name: str) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            marker = {
                "timestamp": now,
                "frame_index": self._frame_index,
                "byte_offset": self._byte_offset,
                "marker": name,
            }
            if self._markers_fh:
                self._markers_fh.write((json.dumps(marker) + "\n").encode("utf-8"))
                self._markers_fh.flush()
            return marker

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": bool(self._thread and self._thread.is_alive()),
                "connected": self._connected,
                "bytes": self._bytes,
                "frames": self._frames,
                "last_frame": self._last_frame_at,
                "capture_dir": str(self._capture_dir) if self._capture_dir else None,
            }

    def recent_frames(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._recent)[-limit:]

    def _on_frame(self, frame: bytes) -> None:
        """Called from RtuStreamParser in sniffer thread when a frame is reassembled."""
        now = time.time()
        with self._lock:
            self._frame_index += 1
            self._frames += 1
            self._last_frame_at = now
            # store frame record
            record = {
                "timestamp": now,
                "index": self._frame_index,
                "byte_offset": max(0, self._byte_offset - len(frame)),
                "length": len(frame),
                "hex": frame.hex(),
            }
            # parse minimal FC06/FC16
            try:
                fn = frame[1]
                if fn == 6 and len(frame) >= 8:
                    record.update({
                        "fc": 6,
                        "slave": frame[0],
                        "register": int.from_bytes(frame[2:4], "big"),
                        "value_decimal": int.from_bytes(frame[4:6], "big"),
                        "value_hex": frame[4:6].hex(),
                    })
                elif fn == 16 and len(frame) >= 8:
                    register = int.from_bytes(frame[2:4], "big")
                    count = int.from_bytes(frame[4:6], "big")
                    words = []
                    if len(frame) >= 7 and frame[6] and len(frame) >= 9 + frame[6]:
                        byte_count = frame[6]
                        words = [int.from_bytes(frame[i:i+2], "big") for i in range(7, 7+byte_count, 2)]
                    record.update({
                        "fc": 16,
                        "slave": frame[0],
                        "start_register": register,
                        "register_count": count,
                        "words_decimal": words,
                        "words_hex": [f"{w:04x}" for w in words],
                    })
            except Exception:
                # never fail the sniffer on parse error
                pass
            if self._frames_fh:
                self._frames_fh.write((json.dumps(record) + "\n").encode("utf-8"))
                self._frames_fh.flush()
            self._recent.append(record)

    def _run(self) -> None:
        sock = None
        while not self._stop.is_set():
            try:
                sock = socket.create_connection((self.host, self.port), timeout=5)
                sock.settimeout(1.0)
                self._connected = True
                # Read loop
                while not self._stop.is_set():
                    try:
                        data = sock.recv(4096)
                    except socket.timeout:
                        continue
                    if not data:
                        # remote closed
                        break
                    # write raw
                    with self._lock:
                        self._ensure_capture_dir()
                        self._raw_fh.write(data)
                        self._raw_fh.flush()
                        self._bytes += len(data)
                        self._byte_offset += len(data)
                    # feed parser
                    self.parser.feed(data)
                self._connected = False
            except Exception:
                self._connected = False
                time.sleep(1)
            finally:
                try:
                    if sock:
                        sock.close()
                except Exception:
                    pass
                sock = None
        # thread exit: ensure files closed by stop()
        return
