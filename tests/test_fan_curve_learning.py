import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway"))
from controller_core import HardwareAdapter  # noqa: E402
from controller_runtime import ControllerRuntime  # noqa: E402


def test_runtime_learns_the_fan_curve_from_steady_readings(tmp_path):
    gateway = {"bus_traffic": False}
    runtime = ControllerRuntime(gateway_state=gateway, hardware=HardwareAdapter(), state_path=tmp_path / "c.json")
    t = 1_000.0
    for extract, supply, extract_rpm, supply_rpm in ((40, 28, 1516, 1228), (70, 58, 2235, 1947), (100, 88, 2954, 2668)):
        gateway.update(fan_extract_percent=extract, fan_supply_percent=supply,
                       fan_extract_rpm=extract_rpm, fan_supply_rpm=supply_rpm)
        runtime._learn_fan_curve(t)          # first sight of a new percentage
        runtime._learn_fan_curve(t + 5)      # still ramping: ignored
        runtime._learn_fan_curve(t + 40)     # steady for 30 s: learned
        t += 100
    assert runtime.config.data["fan_curve"] is None
    runtime._learn_fan_curve(t + 700)        # the fit is checked every 10 minutes
    curve = runtime.config.data["fan_curve"]
    assert abs(curve["rpm_at_0"] - 557) < 5 and abs(curve["rpm_per_percent"] - 24) < 0.2
    assert runtime.config.airflow_plan()["fan_curve"]["learned"] is True
