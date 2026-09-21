#!/usr/bin/env python3
"""Controller-aware entry point for the monolithic Dantherm gateway.

This subclasses the hardware-verified gateway committed by Codex and adds only
master arbitration hooks. The large gateway implementation stays untouched.
"""
from __future__ import annotations

import argparse
import logging
import signal
from pathlib import Path

import serial
import yaml

from dantherm_gateway import Gateway as BaseGateway

LOG = logging.getLogger("dantherm_controller_gateway")


class Gateway(BaseGateway):
    """Base gateway plus immediate HCP4 detection and hard CONTROL write gate."""

    def __init__(self, config: dict):
        super().__init__(config)
        master_cfg = config.get("controller", {}).get("master_arbitration", {})
        self.controller.configure_master(master_cfg)

    def serial_read(self, ser: serial.Serial, size: int) -> bytes:
        data = super().serial_read(ser, size)
        # Feed all bus traffic immediately, including reads performed inside
        # control sequences. This lets HCP4 pre-empt Pi between two writes.
        self.controller.observe_serial_bytes(data)
        return data

    def serial_write(self, ser: serial.Serial, data: bytes, reason: str) -> int:
        is_control = str(reason).startswith("CONTROL")
        if is_control and not self.controller.hardware_writes_allowed():
            state = self.controller.master.snapshot()
            raise RuntimeError(
                f"RS485 control write blocked: active_master={state['active_master']} "
                f"reason={state['hcp4_detection_reason']}"
            )
        written = super().serial_write(ser, data, reason)
        if is_control and written:
            # FC06 echoes and FC16 acknowledgements are consumed as our own
            # transaction and therefore never count as HCP4 activity.
            self.controller.note_own_frame(data[:written])
        return written

    def queue_controller_hardware(self, action: str, value: object):
        if not self.controller.hardware_writes_allowed():
            state = self.controller.master.snapshot()
            raise RuntimeError(
                f"Controller paused by master arbitration: {state['active_master']}"
            )
        return super().queue_controller_hardware(action, value)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", default="config.yaml")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    gateway = Gateway(config)
    signal.signal(signal.SIGTERM, lambda *_: setattr(gateway, "running", False))
    signal.signal(signal.SIGINT, lambda *_: setattr(gateway, "running", False))
    signal.signal(signal.SIGUSR1, lambda *_: gateway.request_capture_toggle())
    signal.signal(signal.SIGHUP, lambda *_: gateway.request_controller_reload())
    gateway.run()


if __name__ == "__main__":
    main()
