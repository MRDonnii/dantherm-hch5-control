import sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"gateway"))
from controller_core import ControllerEngine,ControllerState,HardwareAdapter
from controller_runtime import ControllerRuntime

def test_bathroom_policy_and_night_air_quality_cap(tmp_path):
    state=ControllerState(tmp_path/"controller.json")
    state.configure({"mode":"smart_auto","bathroom_rh_setpoint":65,"bathroom_rh_hysteresis":5,"bathroom_max_level":4,"night_air_quality_max_level":4,"night_enabled":True,"night_start":"00:00","night_end":"23:59","night_level":2})
    runtime=ControllerRuntime(gateway_state={"bus_traffic":False},hardware=HardwareAdapter(),state_path=tmp_path/"runtime.json")
    runtime.config=state;runtime.engine=ControllerEngine(state,HardwareAdapter())
    runtime.room_inputs({"source":"home_assistant","valid_for_s":180,"rooms":{"Badeværelse":{"humidity":78,"temperature":22,"priority":"auto","control":True,"enabled":True,"room_type":"bathroom"}}})
    level,*_=runtime._derive_smart_decision()
    assert level<=4
    state.heartbeat("boost",requested_level=6,valid_for_s=180,reason="Badeværelse RH")
    resolved=runtime.engine.resolve()
    assert resolved["effective_level"]<=4
    assert resolved["night_active"] is True

def test_t2_prefers_canonical_temperature_and_stales(tmp_path):
    gateway={"supply_temperature":18.4,"supply_temp":21.5,"supply_temperature_sample_monotonic":time.monotonic(),"bus_traffic":False}
    runtime=ControllerRuntime(gateway_state=gateway,hardware=HardwareAdapter(),state_path=tmp_path/"controller.json")
    snap=runtime.snapshot();assert snap["actual_supply_before_heater_temperature"]==18.4;assert snap["actual_supply_before_heater_temperature_source"]=="canonical_t2"
    gateway["supply_temperature_sample_monotonic"]=time.monotonic()-60
    assert runtime.snapshot()["actual_supply_before_heater_temperature"] is None

def test_afterheat_ui_contract_is_setpoint_only():
    source=(ROOT/"frontend-v2/src/pages/OverviewPage.tsx").read_text()
    settings=(ROOT/"frontend-v2/src/pages/SettingsPage.tsx").read_text()
    assert "afterheat_setpoint" in source and "afterheat_valve" not in source
    assert "afterheat_setpoint" in settings and "actuator_position" not in settings
