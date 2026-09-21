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
{"bypass":"open"}
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
    "bathroom":{"temperature":22.8,"humidity":68.4},
    "bedroom":{"co2":1180},
    "kitchen":{"co2":920}
  }
}
```

Pi derives the Smart Auto demand. Current beta rules use worst-room CO2/RH and a 10-minute RH rise trigger. Stale inputs automatically fall back to Local Auto.

## Master rule

There is no normal controller ON/OFF. Pi becomes master automatically whenever the RS485 bus is healthy and HCP4 is absent. Any detected HCP4 FC06/FC16 activity immediately pauses Pi writes. During `unknown` arbitration state writes are blocked.
