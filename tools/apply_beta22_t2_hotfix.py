from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def patch(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"marker not found in {path}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")

# Every verified FC04 0..3 temperature frame now refreshes both the legacy
# gateway keys and the canonical keys consumed by the controller diagnostics.
patch(
    "gateway/dantherm_gateway.py",
    '''                for key, raw in zip(("outdoor_temp", "supply_temp", "extract_temp", "exhaust_temp"), values):\n                    self.publish(key, raw / 100.0)\n''',
    '''                for legacy_key, canonical_key, raw in zip(\n                    ("outdoor_temp", "supply_temp", "extract_temp", "exhaust_temp"),\n                    ("outdoor_temperature", "supply_temperature", "extract_temperature", "exhaust_temperature"),\n                    values,\n                ):\n                    value = raw / 100.0\n                    self.publish(legacy_key, value)\n                    self.publish(canonical_key, value)\n                self.state["temperature_sample_monotonic"] = time.monotonic()\n                self.state["temperature_source"] = "hch5_fc04"\n''',
)

# Do the same when the Pi is the active poller. This prevents a master change
# from changing the meaning/identity of T2.
patch(
    "gateway/dantherm_gateway.py",
    '''        if temperatures is not None:\n            for key, raw in zip(\n                ("outdoor_temp", "supply_temp", "extract_temp", "exhaust_temp"),\n                temperatures,\n            ):\n                self.publish(key, raw / 100.0)\n''',
    '''        if temperatures is not None:\n            for legacy_key, canonical_key, raw in zip(\n                ("outdoor_temp", "supply_temp", "extract_temp", "exhaust_temp"),\n                ("outdoor_temperature", "supply_temperature", "extract_temperature", "exhaust_temperature"),\n                temperatures,\n            ):\n                value = raw / 100.0\n                self.publish(legacy_key, value)\n                self.publish(canonical_key, value)\n            self.state["temperature_sample_monotonic"] = time.monotonic()\n            self.state["temperature_source"] = "hch5_fc04_active"\n''',
)

# The verified HAC1 180..209 snapshot is the authoritative diagnostic view for
# T1..T5 + T2AH/frost while Pi is master. Previously it was mirrored to HA but
# not fed back into this gateway's own state, which could leave the WebUI on an
# old T2 value.
patch(
    "gateway/dantherm_gateway.py",
    '''    def poll_temperature_snapshot(self, ser: serial.Serial):\n        """Read all seven temperatures in one FC03 transaction, without writes."""\n        values = self.read_register_block(ser, 0x40, 180, 30)\n        if values is None:\n            return\n        if getattr(self, "tcp_mirror", None) is not None:\n            # Pair the request and response for unambiguous decoder routing.\n            request = self.read_frame(180, 30, slave=0x40)\n            body = bytes([0x40, 3, 60]) + b"".join(\n                value.to_bytes(2, "big") for value in values\n            )\n            self.tcp_mirror.broadcast(request + body + crc16(body).to_bytes(2, "little"))\n''',
    '''    def poll_temperature_snapshot(self, ser: serial.Serial):\n        """Read all seven temperatures in one FC03 transaction, without writes."""\n        values = self.read_register_block(ser, 0x40, 180, 30)\n        if values is None:\n            return\n        if getattr(self, "tcp_mirror", None) is not None:\n            # Pair the request and response for unambiguous decoder routing.\n            request = self.read_frame(180, 30, slave=0x40)\n            body = bytes([0x40, 3, 60]) + b"".join(\n                value.to_bytes(2, "big") for value in values\n            )\n            self.tcp_mirror.broadcast(request + body + crc16(body).to_bytes(2, "little"))\n\n        def temperature(raw: int):\n            if raw in (0x7FFF, 0x8000):\n                return None\n            signed = raw - 65536 if raw >= 32768 else raw\n            result = signed / 100.0\n            return result if -35 <= result <= 100 else None\n\n        # 180=T1, 181=T2 before the external afterheater, 182=T3, 183=T4,\n        # 184=T5, 205=T2AH after the coil, 206=frost/water-side sensor.\n        snapshot = {\n            "outdoor_temperature": temperature(values[0]),\n            "supply_temperature": temperature(values[1]),\n            "extract_temperature": temperature(values[2]),\n            "exhaust_temperature": temperature(values[3]),\n            "room_temperature": temperature(values[4]),\n            "heating_coil_after_temperature": temperature(values[25]),\n            "heating_coil_frost_temperature": temperature(values[26]),\n        }\n        aliases = {\n            "outdoor_temperature": "outdoor_temp",\n            "supply_temperature": "supply_temp",\n            "extract_temperature": "extract_temp",\n            "exhaust_temperature": "exhaust_temp",\n            "room_temperature": "hrc2_t5_temperature",\n        }\n        for key, value in snapshot.items():\n            if value is None:\n                continue\n            self.publish(key, value)\n            if key in aliases:\n                self.publish(aliases[key], value)\n        if snapshot["supply_temperature"] is not None:\n            self.state["temperature_sample_monotonic"] = time.monotonic()\n            self.state["temperature_source"] = "hac1_snapshot_180_209"\n        if len(values) >= 30:\n            self.publish("afterheat_active", values[29] == 16)\n''',
)

(ROOT / "tests/test_t2_gateway_mapping.py").write_text('''from pathlib import Path\n\nROOT = Path(__file__).resolve().parents[1]\n\ndef test_gateway_feeds_canonical_t2_in_passive_and_active_paths():\n    source = (ROOT / "gateway/dantherm_gateway.py").read_text()\n    assert '"supply_temperature"' in source\n    assert 'self.state["temperature_sample_monotonic"] = time.monotonic()' in source\n    assert 'self.state["temperature_source"] = "hch5_fc04"' in source\n    assert 'self.state["temperature_source"] = "hch5_fc04_active"' in source\n\ndef test_hac1_snapshot_maps_register_181_to_t2_and_205_to_t2ah():\n    source = (ROOT / "gateway/dantherm_gateway.py").read_text()\n    assert '"supply_temperature": temperature(values[1])' in source\n    assert '"heating_coil_after_temperature": temperature(values[25])' in source\n    assert '"heating_coil_frost_temperature": temperature(values[26])' in source\n    assert 'self.state["temperature_source"] = "hac1_snapshot_180_209"' in source\n''', encoding="utf-8")

print("beta.22 canonical T2 mapping applied")
