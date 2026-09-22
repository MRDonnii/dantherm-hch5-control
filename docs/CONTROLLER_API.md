# Controller API

The Raspberry Pi controller is the source of truth. Home Assistant and WebUI are clients only.

All machine endpoints require `Authorization: Bearer <DANTHERM_CONTROLLER_TOKEN>`.

## GET /api/controller/state

Returns persistent controller configuration, desired/effective state, actual HCH/HAC1 state, master arbitration and smart-room diagnostics.

## POST /api/controller/command

Accepts the same persistent configuration fields as the WebUI, except `enabled` is forbidden because the Pi controller cannot be user-disabled.

Examples:

```json
{"mode":"manual","manual_level":4}
```

```json
{"mode":"smart_auto"}
```

```json
{"afterheat_setpoint":22}
```

```json
{"fireplace":true}
```

## POST /api/controller/inputs

Leased Home Assistant room measurements. They are never written directly to Modbus.

```json
{
  "source":"home_assistant",
  "valid_for_s":180,
  "rooms":{
    "bathroom":{"temperature":22.8,"humidity":68.4,"enabled":true,"control":true,"priority":"high"},
    "bedroom":{"co2":1180,"enabled":true,"control":true,"priority":"auto"},
    "kitchen":{"co2":920,"enabled":true,"control":false,"priority":"low"}
  }
}
```

Pi derives levels 1–6 from worst-room CO2/RH and a 10-minute RH rise trigger. Priority changes how early a room reacts, but a severe normal-priority measurement still beats a mild high-priority measurement. Disabled and monitor-only rooms never control ventilation. The HCH5/HAC1 local CO2/RH sensors remain part of the decision. Stale leased input automatically falls back to Local Auto with the configured downshift/boost protection.

At most 32 rooms are accepted. Invalid metadata or out-of-range measurements return HTTP 400 instead of being silently used. Bypass is status-only in this beta; non-`auto` commands are rejected because the verified hardware sequence is not documented.

## Master rule

There is no normal controller ON/OFF. Pi becomes master automatically whenever the RS485 bus is healthy and HCP4 is absent. Any detected HCP4 FC06/FC16 activity immediately pauses Pi writes. During `unknown` arbitration state writes are blocked.
