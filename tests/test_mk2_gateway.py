"""HCH5 Control on an HCH5 MKII: bridge, read-only proxy and the gateway's MKII loop against a simulator."""

import importlib.util
import queue
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway"))
sys.path.insert(0, str(Path(__file__).parent))

import fan_steps  # noqa: E402
import mk2  # noqa: E402
from mk2_bridge import Mk2Bridge, ReadOnlyModbusProxy, level_for_pair  # noqa: E402
from mk2_sim import FakeSerial, Mk2Simulator  # noqa: E402

FOUR_STEPS = fan_steps.ladder(fan_steps.DEFAULT_FAN_SETTINGS)


def _bridge(sim):
    published: dict[str, object] = {}
    unit = mk2.Mk2Unit(mk2.ModbusRtu(FakeSerial(sim), 1, timeout=0.2))
    return Mk2Bridge(unit, lambda key, value: published.__setitem__(key, value), lambda: FOUR_STEPS), published


def test_poll_publishes_gateway_keys():
    sim = Mk2Simulator()
    bridge, state = _bridge(sim)
    assert bridge.poll() is True
    assert state["outdoor_temp"] == 6.5 and state["supply_temp"] == 19.8
    assert state["extract_temp"] == 22.1 and state["exhaust_temp"] == 8.9
    assert state["hrc2_t5_temperature"] == 21.6 and state["fan_supply_rpm"] == 1420
    assert state["humidity"] == 46 and state["relative_humidity"] == 46
    assert state["bus_traffic"] is True and state["unit_generation"] == "mk2"
    assert state["current_level"] == "level_2" and state["filter_days_remaining"] == 45


def test_poll_without_answer_marks_bus_unhealthy():
    sim = Mk2Simulator()
    published = {}
    unit = mk2.Mk2Unit(mk2.ModbusRtu(FakeSerial(sim, unit_id=9), 1, timeout=0.05))
    bridge = Mk2Bridge(unit, published.__setitem__)
    assert bridge.poll() is False and published["bus_traffic"] is False


def test_fan_pair_follows_the_controllers_steps():
    for level, profile in FOUR_STEPS.items():
        assert level_for_pair(int(profile["extract"]), int(profile["supply"]), FOUR_STEPS) == level
    assert level_for_pair(0, 0, FOUR_STEPS) == 0
    six = fan_steps.SIX_DEFAULT_PROFILES
    assert level_for_pair(25, 13, six) == 1 and level_for_pair(100, 88, six) == 4
    sim = Mk2Simulator()
    bridge, state = _bridge(sim)
    top = FOUR_STEPS[4]
    bridge.apply("fan_pair", (top["extract"], top["supply"]))
    assert sim.u32(mk2.REG_FAN_LEVEL) == 4 and sim.u32(mk2.REG_CURRENT_MODE) == mk2.MODE_MANUAL
    assert state["fan_extract_percent"] == top["extract"]


def test_standby_fireplace_bypass_and_afterheat():
    sim = Mk2Simulator()
    bridge, state = _bridge(sim)
    one = FOUR_STEPS[1]
    bridge.apply("fan_pair", (one["extract"], one["supply"]))
    bridge.apply("standby", True)
    assert sim.u32(mk2.REG_FAN_LEVEL) == 0
    nominal = FOUR_STEPS[3]
    bridge.apply("fan_pair", (nominal["extract"], nominal["supply"]))  # held while in standby
    assert sim.u32(mk2.REG_FAN_LEVEL) == 0
    bridge.apply("standby", False)
    assert sim.u32(mk2.REG_FAN_LEVEL) == 3
    bridge.apply("fireplace", True)
    assert sim.u32(mk2.REG_CURRENT_MODE) == mk2.MODE_FIREPLACE
    bridge.apply("fireplace", False)
    bridge.apply("bypass", "on")
    assert sim.u32(mk2.REG_BYPASS_DAMPER) == mk2.BYPASS_OPENED and state["bypass_request"] == "ON"
    bridge.apply("bypass", "off")
    assert sim.u32(mk2.REG_BYPASS_DAMPER) == mk2.BYPASS_CLOSED
    assert bridge.apply("afterheat_setpoint", 20) is None
    with pytest.raises(RuntimeError):
        bridge.apply("teleport", 1)


def test_read_only_proxy_forwards_reads_and_refuses_writes():
    sim = Mk2Simulator()
    proxy = ReadOnlyModbusProxy(mk2.ModbusRtu(FakeSerial(sim), 1, timeout=0.2), "127.0.0.1", 0)
    proxy.start()
    try:
        client = mk2.Mk2Unit(mk2.ModbusTcp("127.0.0.1", proxy.port, timeout=2))
        assert client.identify().model == "HCH 5 MKII"
        assert client.snapshot()["outdoor_temperature"] == 6.5
        with pytest.raises(mk2.ModbusError):
            client.set_level(4)
        assert sim.u32(mk2.REG_FAN_LEVEL) == 2
        client.transport.close()
    finally:
        proxy.stop()


@pytest.mark.skipif(importlib.util.find_spec("paho.mqtt.client") is None, reason="paho-mqtt is installed by the installer/CI")
def test_gateway_runs_the_controller_on_an_mk2():
    from dantherm_gateway import Gateway

    sim = Mk2Simulator()
    server, port = sim.serve_tcp()
    gateway = Gateway.__new__(Gateway)
    gateway.cfg = {"unit": {"generation": "mk2", "transport": "tcp", "host": "127.0.0.1", "port": port}}
    gateway.state = {}
    gateway.running = True
    gateway.mqtt_enabled = False
    gateway.controller_reload_requested = False
    gateway.controller_hardware_queue = queue.SimpleQueue()
    gateway.connect = lambda: None
    gateway.publish = lambda key, value, source=None: gateway.state.__setitem__(key, value)

    class FakeController:
        class config:
            data = {"profiles": FOUR_STEPS}
            lock = threading.Lock()

        def start(self):
            pass

        def stop(self):
            pass

    gateway.controller = FakeController()
    assert gateway.unit_generation() == "mk2"
    thread = threading.Thread(target=gateway.run, daemon=True)
    thread.start()
    try:
        for _ in range(50):
            if gateway.state.get("outdoor_temp") is not None:
                break
            time.sleep(0.1)
        assert gateway.state["outdoor_temp"] == 6.5 and gateway.state["gateway_mode"] == "mk2_controller"
        top = FOUR_STEPS[4]
        assert gateway.queue_controller_hardware("fan_pair", (top["extract"], top["supply"])) == (top["extract"], top["supply"])
        assert sim.u32(mk2.REG_FAN_LEVEL) == 4
        assert gateway.queue_controller_hardware("fireplace", True) is True
        assert sim.u32(mk2.REG_CURRENT_MODE) == mk2.MODE_FIREPLACE
    finally:
        gateway.running = False
        thread.join(5)
        server.shutdown()
    assert not thread.is_alive()
