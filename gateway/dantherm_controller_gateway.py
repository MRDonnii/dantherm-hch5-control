#!/usr/bin/env python3
"""Controller-aware entry point for the monolithic Dantherm gateway.

This subclasses the hardware-verified gateway and adds fail-safe master
arbitration. HCP4 always wins. Normal Pi active reads are also suppressed while
HCP4 is active so the RS485 segment never has two routine masters.
"""
from __future__ import annotations

import argparse
import logging
import signal
import time
from pathlib import Path

import serial
import yaml

from dantherm_gateway import Gateway as BaseGateway
from master_arbitration import MasterArbitrator

LOG = logging.getLogger("dantherm_controller_gateway")


class Gateway(BaseGateway):
    """Base gateway plus immediate HCP4 detection and hard bus-master gate."""

    def __init__(self, config: dict):
        # HCH5 Control owns the local maintenance timer when it runs as the
        # replacement controller. Passive installations keep the legacy
        # opt-in behaviour because they use the base gateway entry point.
        filter_cfg = config.get("filter")
        if not isinstance(filter_cfg, dict):
            filter_cfg = {}
            config["filter"] = filter_cfg
        filter_cfg["enabled"] = True

        super().__init__(config)
        master_cfg = config.get("controller", {}).get("master_arbitration", {})
        self.controller.configure_master(master_cfg)

        # ControllerRuntime is the only Pi-side controller in this entrypoint.
        # Disable the older experimental MQTT/manual loop so it can never
        # compete with ControllerRuntime or HCP4. The verified low-level
        # functions remain available through controller_hardware_queue.
        self.control_enabled = False
        self.fireplace_enabled = False
        self.override_mode = None
        self.startup_mode = None
        LOG.info("Legacy gateway control loop disabled; ControllerRuntime owns Pi control")
        LOG.info("HCH5 Control local filter tracking enabled")

    def serial_read(self, ser: serial.Serial, size: int) -> bytes:
        data = super().serial_read(ser, size)
        # Feed every received frame into arbitration, including traffic seen
        # while a control sequence is in progress. This lets HCP4 pre-empt Pi
        # between individual writes.
        self.controller.observe_serial_bytes(data)
        return data

    def _active_read_allowed(self) -> bool:
        """Allow active reads only when Pi owns the bus or a takeover probe is due.

        During startup Pi listens passively for the complete observation
        window. While HCP4 is active Pi remains passive. Once HCP4 has been
        quiet for the configured release timeout, one normal read transaction
        may probe that the unit still answers; the response makes bus health
        true and allows arbitration to promote Pi to master.
        """
        master = self.controller.master
        now = time.monotonic()
        if master.master == MasterArbitrator.PI:
            return True
        if master.master == MasterArbitrator.UNKNOWN:
            if now - master.started_monotonic < master.startup_observation:
                return False
            age = None if master.last_foreign_write is None else now - master.last_foreign_write
            return age is None or age > master.release_timeout
        if master.master == MasterArbitrator.HCP4:
            age = None if master.last_foreign_write is None else now - master.last_foreign_write
            return age is not None and age > master.release_timeout
        return False

    def serial_write(self, ser: serial.Serial, data: bytes, reason: str) -> int:
        is_control = str(reason).startswith("CONTROL")
        is_active_read = str(reason) == "ACTIVE_READ"

        if is_control and not self.controller.hardware_writes_allowed():
            state = self.controller.master.snapshot()
            raise RuntimeError(
                f"RS485 control write blocked: active_master={state['active_master']} "
                f"reason={state['hcp4_detection_reason']}"
            )

        if is_active_read and not self._active_read_allowed():
            # Returning zero makes the existing bounded read helpers time out
            # harmlessly without putting a request on the wire. Passive RX and
            # HCP4 detection continue through serial_read().
            return 0

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
