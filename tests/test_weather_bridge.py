import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "gateway"))

from weather_bridge import humidity_at_t1, validate_weather


def test_dew_point_is_adjusted_to_measured_t1():
    weather = validate_weather({"source": "weather.forecast_langaa", "condition": "cloudy",
                                "temperature_c": 16, "humidity_pct": 60, "dew_point_c": 8})
    humidity, method = humidity_at_t1(weather, 15)
    assert 61 < humidity < 66
    assert method == "Dugpunkt"


def test_wrong_place_or_stale_data_cannot_drive_humidity():
    weather = validate_weather({"source": "weather.other", "temperature_c": 22, "humidity_pct": 60})
    assert humidity_at_t1(weather, 15)[0] is None
    assert humidity_at_t1(None, 15)[0] is None


def test_invalid_weather_is_rejected():
    with pytest.raises(ValueError):
        validate_weather({"source": "sensor.outdoor", "condition": "sunny"})
    with pytest.raises(ValueError):
        validate_weather({"source": "weather.home", "humidity_pct": 150})


def test_humidity_fallback_uses_model_temperature_and_relative_humidity():
    weather = validate_weather({"source": "weather.home", "temperature_c": 15,
                                "humidity_pct": 70})
    assert humidity_at_t1(weather, 15)[0] == 70
