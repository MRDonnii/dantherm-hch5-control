import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from controller_core import ControllerError, HardwareAdapter
from controller_runtime import ControllerRuntime
from onewire_extras import OneWireExtras, clean_roles, read_ds18b20


def fake_bus(root: Path, sensors: dict[str, str]) -> Path:
    for sensor_id, raw in sensors.items():
        (root / sensor_id).mkdir(parents=True)
        (root / sensor_id / "w1_slave").write_text(raw, encoding="ascii")
    return root


def reading(millidegrees: int, crc_ok: bool = True) -> str:
    return f"4b 01 4b 46 7f ff 05 10 e1 : crc=e1 {'YES' if crc_ok else 'NO'}\n4b 01 4b 46 7f ff 05 10 e1 t={millidegrees}\n"


class OneWireExtrasTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.bus = fake_bus(Path(temp.name), {
            "28-000000cb29ab": reading(27100),   # water return, owned by the 1-Wire service
            "28-000000cc2944": reading(34000),   # water flow
            "28-0000000a0001": reading(19450),   # new: supply duct before the coil
            "28-0000000a0002": reading(-3250),   # new: loft
            "28-0000000a0003": reading(85000),   # power-on value, not a reading
        })

    def test_reads_values_and_rejects_bad_ones(self):
        self.assertEqual(read_ds18b20("28-0000000a0001", self.bus), 19.45)
        self.assertEqual(read_ds18b20("28-0000000a0002", self.bus), -3.25)
        self.assertIsNone(read_ds18b20("28-0000000a0003", self.bus))
        self.assertIsNone(read_ds18b20("28-missing", self.bus))

    def test_leaves_the_water_sensors_alone_and_applies_roles(self):
        roles = {"28-0000000a0001": {"role": "t2", "name": ""}, "28-0000000a0002": {"role": "attic", "name": "Loft"}}
        extras = OneWireExtras(lambda: roles, devices=self.bus, service_url=None)
        extras._water_sensor_ids = lambda: {"28-000000cb29ab", "28-000000cc2944"}
        extras.read_once(now=100.0)
        sensors = extras.sensors(now=110.0)
        self.assertEqual([s["id"] for s in sensors], ["28-0000000a0001", "28-0000000a0002", "28-0000000a0003"])
        self.assertEqual(sensors[0]["name"], "T2 · før eftervarme")
        self.assertEqual(sensors[1]["name"], "Loft")
        self.assertEqual(extras.by_role("t2", now=110.0), 19.45)
        self.assertEqual(extras.by_role("attic", now=110.0), -3.25)
        self.assertIsNone(extras.by_role("t2", now=100.0 + 91))  # stale

    def test_role_validation(self):
        self.assertEqual(clean_roles({"28-0000000A0001": {"role": "attic", "name": " Loft "}}), {"28-0000000a0001": {"role": "attic", "name": "Loft"}})
        for bad in ({"x": {"role": "t2"}}, {"28-01": {"role": "boss"}}, {"28-0000000a0001": {"role": "t2"}, "28-0000000a0002": {"role": "t2"}}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                clean_roles(bad)


class MeasuredT2Tests(unittest.TestCase):
    def make_runtime(self, state):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        runtime = ControllerRuntime(gateway_state=state, hardware=HardwareAdapter(), state_path=Path(temp.name) / "c.json")
        runtime.hardware_writes_allowed = lambda: False
        return runtime

    def test_unit_t2_copy_is_not_reported_as_before_coil(self):
        runtime = self.make_runtime({"supply_temp": 27.5, "outdoor_temp": 0.0, "extract_temp": 22.0, "exhaust_temp": 2.2})
        snapshot = runtime.snapshot()
        self.assertIsNone(snapshot["actual_supply_before_heater_temperature"])
        self.assertAlmostEqual(snapshot["actual_supply_before_heater_estimate"], 19.8, places=1)

    def test_measured_t2_from_onewire_role(self):
        runtime = self.make_runtime({})
        runtime.onewire.by_role = lambda role, now=None: 19.4 if role == "t2" else (-2.0 if role == "attic" else None)
        runtime.onewire.sensors = lambda now=None: [{"id": "28-0000000a0001", "temperature": 19.4, "role": "t2", "name": "T2 · før eftervarme"}]
        snapshot = runtime.snapshot()
        self.assertEqual(snapshot["actual_supply_before_heater_temperature"], 19.4)
        self.assertEqual(snapshot["actual_supply_before_heater_temperature_source"], "onewire_t2")
        self.assertEqual(snapshot["attic_temperature"], -2.0)

    def test_roles_are_saved_and_validated_through_configure(self):
        runtime = self.make_runtime({})
        snapshot = runtime.configure({"onewire_roles": {"28-0000000a0002": {"role": "attic", "name": "Loft"}}})
        self.assertEqual(snapshot["onewire_roles"], {"28-0000000a0002": {"role": "attic", "name": "Loft"}})
        with self.assertRaises(ControllerError):
            runtime.configure({"onewire_roles": {"nope": {"role": "t2"}}})


if __name__ == "__main__":
    unittest.main()
