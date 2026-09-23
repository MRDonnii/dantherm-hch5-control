from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_gateway_feeds_canonical_t2_in_passive_and_active_paths():
    source = (ROOT / "gateway/dantherm_gateway.py").read_text()
    assert '"supply_temperature"' in source
    assert 'self.state["temperature_sample_monotonic"] = time.monotonic()' in source
    assert 'self.state["temperature_source"] = "hch5_fc04"' in source
    assert 'self.state["temperature_source"] = "hch5_fc04_active"' in source

def test_hac1_snapshot_maps_register_181_to_t2_and_205_to_t2ah():
    source = (ROOT / "gateway/dantherm_gateway.py").read_text()
    assert '"supply_temperature": temperature(values[1])' in source
    assert '"heating_coil_after_temperature": temperature(values[25])' in source
    assert '"heating_coil_frost_temperature": temperature(values[26])' in source
    assert 'self.state["temperature_source"] = "hac1_snapshot_180_209"' in source
