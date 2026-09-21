#!/usr/bin/env python3
"""Fail-safe RS485 master arbitration between HCP4 and Raspberry Pi.

The Raspberry Pi may write only while PI_MASTER is established. Any valid
foreign FC06/FC16 write immediately yields the bus when Pi is master. HCP4 is
released only after a quiet timeout while the bus remains healthy.
"""
from __future__ import annotations

import logging
import time
from collections import deque

LOG = logging.getLogger("passivelink-master")
KNOWN_SLAVES = {1, 0x40}
WRITE_FUNCTIONS = {6, 16}


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def valid_crc(frame: bytes) -> bool:
    return len(frame) >= 4 and crc16(frame[:-2]) == int.from_bytes(frame[-2:], "little")


def write_signature(frame: bytes):
    if len(frame) < 8 or frame[0] not in KNOWN_SLAVES or not valid_crc(frame):
        return None
    fn = frame[1]
    if fn == 6 and len(frame) == 8:
        return (6, frame[0], int.from_bytes(frame[2:4], "big"), int.from_bytes(frame[4:6], "big"))
    if fn == 16:
        # FC16 request and response share slave/start/count. This deliberately
        # treats the response echo as the same transaction signature.
        return (16, frame[0], int.from_bytes(frame[2:4], "big"), int.from_bytes(frame[4:6], "big"))
    return None


class RtuFrameStream:
    """Small RTU stream parser used only for master detection."""

    def __init__(self):
        self.buffer = bytearray()

    @staticmethod
    def _candidates(buffer: bytearray) -> list[int]:
        if len(buffer) < 5:
            return []
        fn = buffer[1]
        lengths: list[int] = []
        if fn in (3, 4):
            byte_count = buffer[2]
            if 0 < byte_count <= 250 and byte_count % 2 == 0:
                lengths.append(5 + byte_count)
            lengths.append(8)
        elif fn == 6:
            lengths.append(8)
        elif fn == 16:
            if len(buffer) >= 7:
                count = int.from_bytes(buffer[4:6], "big")
                byte_count = buffer[6]
                if byte_count == count * 2 and 0 < byte_count <= 246:
                    lengths.append(9 + byte_count)
            lengths.append(8)
        return lengths

    def feed(self, data: bytes) -> list[bytes]:
        if data:
            self.buffer.extend(data)
        frames: list[bytes] = []
        while len(self.buffer) >= 5:
            if self.buffer[0] not in KNOWN_SLAVES:
                del self.buffer[0]
                continue
            candidates = self._candidates(self.buffer)
            if not candidates:
                del self.buffer[0]
                continue
            matched = None
            need_more = False
            for length in candidates:
                if len(self.buffer) < length:
                    need_more = True
                    continue
                candidate = bytes(self.buffer[:length])
                if valid_crc(candidate):
                    matched = candidate
                    break
            if matched is not None:
                frames.append(matched)
                del self.buffer[:len(matched)]
                continue
            if need_more:
                break
            del self.buffer[0]
        if len(self.buffer) > 2048:
            del self.buffer[:-32]
        return frames


class MasterArbitrator:
    UNKNOWN = "unknown"
    HCP4 = "hcp4"
    PI = "pi"

    def __init__(
        self,
        *,
        detection_window: float = 2.0,
        detection_min_foreign_writes: int = 2,
        release_timeout: float = 10.0,
        startup_observation: float = 10.0,
        own_echo_ttl: float = 2.0,
        foreign_echo_dedupe: float = 0.12,
    ):
        self.detection_window = max(0.5, float(detection_window))
        self.detection_min_foreign_writes = max(1, int(detection_min_foreign_writes))
        self.release_timeout = max(3.0, float(release_timeout))
        self.startup_observation = max(3.0, float(startup_observation))
        self.own_echo_ttl = max(0.1, float(own_echo_ttl))
        self.foreign_echo_dedupe = max(0.02, float(foreign_echo_dedupe))
        self.started_monotonic = time.monotonic()
        self.master = self.UNKNOWN
        self.master_since_monotonic = self.started_monotonic
        self.master_since_epoch = time.time()
        self.reason = "startup_observation"
        self.last_bus_frame: float | None = None
        self.last_foreign_write: float | None = None
        self.foreign_events: deque[tuple[float, tuple]] = deque()
        self.pending_own: deque[tuple[float, tuple]] = deque()
        self.own_write_count = 0
        self.own_echo_count = 0
        self.foreign_write_count = 0
        self._last_foreign_signature: tuple | None = None
        self._last_foreign_signature_at = 0.0

    def configure(self, cfg: dict | None) -> None:
        cfg = cfg or {}
        for attr, key, minimum in (
            ("detection_window", "detection_window_seconds", 0.5),
            ("release_timeout", "release_timeout_seconds", 3.0),
            ("startup_observation", "startup_observation_seconds", 3.0),
            ("own_echo_ttl", "own_echo_ttl_seconds", 0.1),
        ):
            if key in cfg:
                setattr(self, attr, max(minimum, float(cfg[key])))
        if "detection_min_foreign_writes" in cfg:
            self.detection_min_foreign_writes = max(1, int(cfg["detection_min_foreign_writes"]))

    def _transition(self, master: str, reason: str, now: float) -> bool:
        if master == self.master:
            self.reason = reason
            return False
        old = self.master
        self.master = master
        self.master_since_monotonic = now
        self.master_since_epoch = time.time()
        self.reason = reason
        LOG.warning("MASTER %s -> %s reason=%s", old.upper(), master.upper(), reason)
        return True

    def note_own_frame(self, frame: bytes, now: float | None = None) -> None:
        signature = write_signature(frame)
        if signature is None:
            return
        now = time.monotonic() if now is None else float(now)
        self.pending_own.append((now + self.own_echo_ttl, signature))
        self.own_write_count += 1
        self._purge(now)

    def _purge(self, now: float) -> None:
        while self.pending_own and self.pending_own[0][0] < now:
            self.pending_own.popleft()
        while self.foreign_events and now - self.foreign_events[0][0] > 60.0:
            self.foreign_events.popleft()

    def _consume_own(self, signature: tuple, now: float) -> bool:
        self._purge(now)
        for index, (expires, candidate) in enumerate(self.pending_own):
            if expires >= now and candidate == signature:
                del self.pending_own[index]
                self.own_echo_count += 1
                return True
        return False

    def observe_frame(self, frame: bytes, now: float | None = None) -> str:
        now = time.monotonic() if now is None else float(now)
        if not valid_crc(frame):
            return "invalid"
        self.last_bus_frame = now
        signature = write_signature(frame)
        if signature is None:
            return "read_or_response"
        if self._consume_own(signature, now):
            return "own"

        # External request and its Modbus response look identical for FC06 and
        # share the same signature for FC16. Count that pair as one transaction.
        if signature == self._last_foreign_signature and now - self._last_foreign_signature_at <= self.foreign_echo_dedupe:
            self.last_foreign_write = now
            return "foreign_echo"

        self._last_foreign_signature = signature
        self._last_foreign_signature_at = now
        self.last_foreign_write = now
        self.foreign_write_count += 1
        self.foreign_events.append((now, signature))
        self._purge(now)

        # Once Pi owns the bus, one valid foreign write is enough to fail safe
        # immediately. During startup we debounce to avoid one stray transaction.
        if self.master == self.PI:
            self._transition(self.HCP4, "foreign_write_while_pi_master", now)
        else:
            recent = [event for event in self.foreign_events if now - event[0] <= self.detection_window]
            if len(recent) >= self.detection_min_foreign_writes:
                self._transition(self.HCP4, "foreign_write_activity", now)
        return "foreign"

    def evaluate(self, *, controller_enabled: bool, bus_healthy: bool, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else float(now)
        self._purge(now)
        if not bus_healthy:
            return self._transition(self.UNKNOWN, "bus_unhealthy", now)

        foreign_age = None if self.last_foreign_write is None else now - self.last_foreign_write
        if foreign_age is not None and foreign_age <= self.release_timeout:
            if self.master == self.HCP4:
                self.reason = "hcp4_recent_foreign_writes"
            return False

        if not controller_enabled:
            return self._transition(self.UNKNOWN, "controller_disabled", now)

        if now - self.started_monotonic < self.startup_observation:
            return self._transition(self.UNKNOWN, "startup_observation", now)

        if self.master == self.HCP4:
            return self._transition(self.PI, "hcp4_quiet_timeout_bus_healthy", now)
        if self.master == self.UNKNOWN:
            return self._transition(self.PI, "no_foreign_writes_bus_healthy", now)
        self.reason = "pi_master_bus_healthy"
        return False

    def writes_allowed(self, controller_enabled: bool) -> bool:
        return bool(controller_enabled and self.master == self.PI)

    def bus_age(self, now: float | None = None):
        now = time.monotonic() if now is None else float(now)
        return None if self.last_bus_frame is None else max(0.0, now - self.last_bus_frame)

    def snapshot(self, now: float | None = None) -> dict[str, object]:
        now = time.monotonic() if now is None else float(now)
        self._purge(now)
        age = None if self.last_foreign_write is None else max(0.0, now - self.last_foreign_write)
        foreign_10 = sum(1 for when, _ in self.foreign_events if now - when <= 10.0)
        foreign_60 = sum(1 for when, _ in self.foreign_events if now - when <= 60.0)
        return {
            "active_master": self.master,
            "hcp4_detected": self.master == self.HCP4,
            "hcp4_active": self.master == self.HCP4,
            "hcp4_last_foreign_write_age": round(age, 2) if age is not None else None,
            "hcp4_foreign_writes_10s": foreign_10,
            "hcp4_foreign_writes_60s": foreign_60,
            "hcp4_detection_reason": self.reason,
            "hcp4_release_timeout_seconds": self.release_timeout,
            "hcp4_detection_window_seconds": self.detection_window,
            "hcp4_detection_min_foreign_writes": self.detection_min_foreign_writes,
            "own_write_count": self.own_write_count,
            "own_echo_count": self.own_echo_count,
            "foreign_write_count": self.foreign_write_count,
            "master_since_epoch": self.master_since_epoch,
            "master_age_seconds": round(max(0.0, now - self.master_since_monotonic), 1),
            "master_bus_frame_age": round(self.bus_age(now), 2) if self.bus_age(now) is not None else None,
        }
