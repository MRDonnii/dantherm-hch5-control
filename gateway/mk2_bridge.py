"""HCH5 Control on an HCH5 MKII: the gateway's measurements and hardware actions over Modbus.

On an MK1 the Pi listens to the RS485 bus and writes HAC1 blocks. An MKII has
its own controller and a Modbus slave (Dantherm Residential register map), so
the Pi polls it and translates the controller's five hardware actions into
MKII commands:

- fan_pair (extract, supply gear) -> the nearest of the controller's steps -> MKII step 1..4 (0 = off)
- standby on/off                  -> fan step 0 / back to the last step
- fireplace on/off                -> the unit's own fireplace mode
- bypass "on"/"off"               -> manual bypass open / closed ("auto" leaves it to the unit)
- afterheat_setpoint              -> not available on the MKII (reported, not an error loop)

Everything else (Smart Auto, rooms, schedules, the WebUI) runs unchanged.
"""
from __future__ import annotations

import logging
import socketserver
import struct
import threading
from typing import Callable

import mk2

LOG = logging.getLogger("dantherm_mk2_bridge")

# MKII snapshot key -> gateway state key (what the controller and the WebUI read).
KEY_MAP = {
    "outdoor_temperature": "outdoor_temp",
    "supply_temperature": "supply_temp",
    "extract_temperature": "extract_temp",
    "exhaust_temperature": "exhaust_temp",
    "room_temperature": "hrc2_t5_temperature",
    "supply_fan_rpm": "fan_supply_rpm",
    "extract_fan_rpm": "fan_extract_rpm",
}
# Published under the same name on both sides.
SAME_KEYS = (
    "relative_humidity", "bypass_raw", "bypass_active", "current_level", "operating_mode",
    "fireplace", "standby", "night_mode", "status_code", "filter_alarm", "filter_days_remaining",
    "filter_life_percent", "filter_source", "unit_model", "unit_generation", "unit_firmware",
    "mk2_mode", "mk2_level", "alarm", "air_quality_index", "air_quality_raw", "operating_hours",
)


def level_for_pair(extract: int, supply: int, profiles: dict) -> int:
    """MKII step for the controller's gear pair, via the controller's own step table."""
    if extract <= 0 and supply <= 0:
        return 0
    levels = sorted(int(level) for level in profiles) if profiles else []
    if not levels:
        return mk2.level_from_percent(max(extract, supply), [])
    nearest = min(levels, key=lambda level: (
        (int(profiles[level]["extract"]) - extract) ** 2 + (int(profiles[level]["supply"]) - supply) ** 2,
        level,
    ))
    if len(levels) == 4:
        return levels.index(nearest) + 1
    # Six free steps: spread evenly over the unit's four.
    return max(1, min(4, 1 + round(levels.index(nearest) * 3 / (len(levels) - 1))))


class Mk2Bridge:
    """Poll the MKII into the gateway state and carry out controller actions on it."""

    def __init__(
        self,
        unit: mk2.Mk2Unit,
        publish: Callable[[str, object], None],
        profiles: Callable[[], dict] = lambda: {},
    ) -> None:
        self.unit = unit
        self.publish = publish
        self.profiles = profiles
        self.connected = False
        self.last_level = 3
        self.last_pair: tuple[int, int] | None = None
        self.standby = False
        self._afterheat_warned = False

    def poll(self) -> bool:
        try:
            data = self.unit.snapshot()
        except (mk2.ModbusError, OSError) as error:
            if self.connected:
                LOG.warning("HCH5 MKII stopped answering: %s", error)
            self.connected = False
            self.publish("bus_traffic", False)
            return False
        if not self.connected:
            LOG.info("HCH5 MKII answers: %s firmware %s", data.get("unit_model"), data.get("unit_firmware"))
        self.connected = True
        for source, target in KEY_MAP.items():
            if source in data:
                self.publish(target, data[source])
        for key in SAME_KEYS:
            if key in data:
                self.publish(key, data[key])
        if "relative_humidity" in data:
            self.publish("humidity", data["relative_humidity"])
        level = data.get("mk2_level")
        if isinstance(level, int) and level > 0:
            self.last_level = level
        if self.last_pair is not None:
            # The MKII reports no gear percentages; show what the controller asked for.
            self.publish("fan_extract_percent", self.last_pair[0])
            self.publish("fan_supply_percent", self.last_pair[1])
        self.publish("hac1_connected", True)
        self.publish("bus_traffic", True)
        self.publish("bus_last_frame_age", 0)
        return True

    def apply(self, action: str, value: object) -> object:
        if action == "fan_pair":
            extract, supply = (int(v) for v in value)  # type: ignore[union-attr]
            level = level_for_pair(extract, supply, self.profiles())
            if not self.standby:
                self.unit.set_level(level)
            if level > 0:
                self.last_level = level
            self.last_pair = (extract, supply)
            self.publish("fan_extract_percent", extract)
            self.publish("fan_supply_percent", supply)
            return (extract, supply)
        if action == "standby":
            self.standby = bool(value)
            self.unit.set_level(0 if self.standby else self.last_level)
            return self.standby
        if action == "fireplace":
            self.unit.set_fireplace(bool(value))
            return bool(value)
        if action == "bypass":
            request = str(value).lower()
            if request in ("on", "open", "1", "true"):
                self.unit.set_bypass(True)
                self.publish("bypass_request", "ON")
            elif request in ("off", "closed", "close", "0", "false"):
                self.unit.set_bypass(False)
                self.publish("bypass_request", "OFF")
            return request
        if action == "afterheat_setpoint":
            if not self._afterheat_warned:
                LOG.info("HCH5 MKII: afterheat setpoint is not available over Modbus; ignored")
                self._afterheat_warned = True
            return None
        raise RuntimeError(f"unknown controller hardware action: {action}")


class ReadOnlyModbusProxy:
    """Modbus TCP on the Pi that forwards reads (FC03) to the MKII; every write is refused.

    Lets Home Assistant read an MKII that is only wired to the Pi's RS485,
    while all control goes through the controller API.
    """

    def __init__(self, transport, bind: str = "0.0.0.0", port: int = 5020) -> None:
        proxy = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                while True:
                    header = self.request.recv(7)
                    if len(header) < 7:
                        return
                    tid, proto, length, unit_id = struct.unpack(">HHHB", header)
                    pdu = self.request.recv(length - 1)
                    reply = proxy.answer(pdu)
                    self.request.sendall(struct.pack(">HHHB", tid, proto, len(reply) + 1, unit_id) + reply)

        self.transport = transport
        self.server = socketserver.ThreadingTCPServer((bind, int(port)), Handler, bind_and_activate=False)
        self.server.allow_reuse_address = True
        self.server.daemon_threads = True
        self.port = int(port)

    def answer(self, pdu: bytes) -> bytes:
        if not pdu or pdu[0] != 3 or len(pdu) < 5:
            return bytes([(pdu[0] if pdu else 0) | 0x80, 1])  # illegal function: read only
        address, count = struct.unpack(">HH", pdu[1:5])
        if not 1 <= count <= 64:
            return bytes([0x83, 3])
        try:
            registers = self.transport.read(address, count)
        except (mk2.ModbusError, OSError):
            return bytes([0x83, 4])
        return bytes([3, 2 * count]) + b"".join(struct.pack(">H", r) for r in registers)

    def start(self) -> None:
        self.server.server_bind()
        self.server.server_activate()
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, name="mk2-proxy", daemon=True).start()
        LOG.info("Read-only Modbus TCP proxy for the MKII on port %s", self.port)

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
