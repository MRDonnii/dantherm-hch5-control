import json
import importlib.machinery
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "gateway"))

if "paho.mqtt.client" not in sys.modules:
    paho = types.ModuleType("paho")
    mqtt_package = types.ModuleType("paho.mqtt")
    mqtt_client = types.ModuleType("paho.mqtt.client")
    mqtt_client.__spec__ = importlib.machinery.ModuleSpec("paho.mqtt.client", loader=None)
    paho.mqtt = mqtt_package
    mqtt_package.client = mqtt_client
    sys.modules.update({
        "paho": paho,
        "paho.mqtt": mqtt_package,
        "paho.mqtt.client": mqtt_client,
    })

from dantherm_gateway import Gateway, crc16


class FakeMqtt:
    def __init__(self):
        self.messages = []

    def publish(self, topic, payload, retain=False):
        self.messages.append((topic, payload, retain))


def make_gateway():
    gateway = Gateway.__new__(Gateway)
    gateway.device_id = "dantherm_hch5"
    gateway.device_name = "Dantherm HCH5"
    gateway.prefix = "dantherm/hch5"
    gateway.discovery = "homeassistant"
    gateway.client = FakeMqtt()
    gateway.control_enabled = False
    gateway.fireplace_enabled = False
    gateway.filter_enabled = False
    gateway.fireplace_gateway_active = False
    gateway.state = {}
    gateway.retain = True
    gateway.mqtt_enabled = False
    return gateway


def discovery_map(gateway):
    gateway.publish_discovery()
    assert all(payload != "" for _topic, payload, _retain in gateway.client.messages)
    return {
        topic: json.loads(payload)
        for topic, payload, _retain in gateway.client.messages
        if topic.endswith("/config")
    }


class BypassAndDiscoveryTests(unittest.TestCase):
    def test_discovery_is_stable_during_fallback_and_never_deletes_entities(self):
        gateway = make_gateway()
        fallback = discovery_map(gateway)
        gateway.client.messages.clear()
        gateway.control_enabled = True
        gateway.fireplace_enabled = True
        gateway.filter_enabled = True
        controller = discovery_map(gateway)
        self.assertEqual(set(fallback), set(controller))
        self.assertEqual(
            {v["unique_id"] for v in fallback.values()},
            {v["unique_id"] for v in controller.values()},
        )
        bypass = fallback["homeassistant/switch/dantherm_hch5/bypass_request/config"]
        self.assertEqual(bypass["unique_id"], "dantherm_hch5_bypass_request")
        self.assertEqual(bypass["state_topic"], "dantherm/hch5/bypass_request")

    def test_bypass_write_reads_writes_and_verifies_register_68(self):
        gateway = make_gateway()
        reads = iter(([0], [255]))
        writes = []
        gateway.read_register_block = lambda _ser, slave, register, count: next(reads)
        gateway.write_one = lambda _ser, register, value: writes.append((register, value))
        self.assertEqual(gateway.write_bypass_request(object(), "on"), "on")
        self.assertEqual(writes, [(68, 255)])
        self.assertEqual(gateway.state["bypass_request_raw"], 255)
        self.assertEqual(gateway.state["bypass_request"], "ON")

    def test_bypass_write_fails_safe_on_invalid_pre_read(self):
        gateway = make_gateway()
        gateway.read_register_block = lambda *_args: [17]
        gateway.write_one = lambda *_args: self.fail("must not write from unknown state")
        with self.assertRaisesRegex(RuntimeError, "unsafe bypass pre-read"):
            gateway.write_bypass_request(object(), "on")

    def test_bypass_write_reports_readback_mismatch(self):
        gateway = make_gateway()
        gateway.read_register_block = lambda *_args: [0]
        writes = []
        gateway.write_one = lambda _ser, register, value: writes.append((register, value))
        with self.assertRaisesRegex(RuntimeError, "readback mismatch"):
            gateway.write_bypass_request(object(), "on")
        self.assertEqual(writes, [(68, 255)])
        self.assertEqual(gateway.state["control_status"], "bypass_readback_mismatch")

    def test_bypass_on_does_not_override_fireplace(self):
        gateway = make_gateway()
        gateway.fireplace_gateway_active = True
        gateway.read_register_block = lambda *_args: self.fail("must not touch register 68")
        with self.assertRaisesRegex(RuntimeError, "fireplace"):
            gateway.write_bypass_request(object(), "on")

    def test_passive_temperature_frame_publishes_canonical_before_heater_key(self):
        gateway = make_gateway()
        body = bytes.fromhex("010408" + "0576094c083705a2")
        frame = body + crc16(body).to_bytes(2, "little")
        gateway.decode(frame)
        self.assertEqual(gateway.state["outdoor_temp"], 13.98)
        self.assertEqual(gateway.state["supply_temp"], 23.80)
        self.assertEqual(gateway.state["extract_temp"], 21.03)
        self.assertEqual(gateway.state["exhaust_temp"], 14.42)
        # controller_runtime.py reads "supply_temperature" (falling back to
        # legacy "supply_temp") as the canonical "before heater" T2 sensor
        # identity, regardless of whether HCP4 or the Pi currently masters
        # the bus. Both paths in dantherm_gateway.py must publish it.
        self.assertEqual(gateway.state["supply_temperature"], 23.80)
        self.assertEqual(gateway.state["temperature_source"], "canonical_t2")
        self.assertIsInstance(gateway.state["temperature_sample_monotonic"], float)

    def test_fireplace_pattern_keeps_verified_register_sequence(self):
        gateway = make_gateway()
        writes = []
        gateway.write_one = lambda _ser, register, value: writes.append((register, value))
        gateway.write_fireplace_pattern(object(), 0, 1, 0, 43)
        self.assertEqual(writes, [(68, 0), (76, 1), (67, 43), (66, 0)])


if __name__ == "__main__":
    unittest.main()
