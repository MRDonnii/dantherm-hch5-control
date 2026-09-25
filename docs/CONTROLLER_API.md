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

The HAC1 afterheat setpoint writes only the verified FC16 block 185..189;
register 186 carries the requested setpoint in degrees Celsius multiplied by
256, with the other words kept to their captured values. No standalone
single-register write has been verified.
The live temperature block 180..184 is refreshed independently every four
seconds while the Pi is the permitted bus master, preserving the outdoor
temperature used by HAC1's afterheat lockout. `t3_setpoint` and `t5_setpoint`
are currently persisted locally only; no verified Modbus write mapping exists
for either setting.

Live T2, T2AH, HAC1 frost, and HRC2 T5 readings are hidden from state and
history when no valid sample has arrived for 45 seconds. Missing samples are
stored as gaps, not as repeated copies of the last value. Historical rows
without freshness markers from before this change are treated as unverifiable
and their affected temperature values are hidden.

The controller-aware gateway enables read-only active polling by default;
`serial.active_reads_enabled: false` remains an opt-out. Active polls run only
when Pi owns the bus or after the configured quiet-time takeover probe. Valid
HCP4 FC03/FC04 read requests and FC06/FC16 writes mark HCP4 active, pausing
Pi polls until the bus has been quiet for the master release timeout (10
seconds by default). The passive gateway entry point keeps active polling
disabled unless explicitly enabled.

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

## POST /api/controller/signals

Leased external switches, machine token required. Today only `fireplace`: while `true` and *Automatic fireplace mode* is enabled in the WebUI, the Pi holds the unit's fireplace mode (bypass closed) and keeps it for the configured afterrun after the signal ends. The lease (`valid_for_s`, 30–900 s, default 300) must be renewed; an expired lease counts as `false`.

```json
{"fireplace":true,"valid_for_s":300}
```

Rooms sent to `/api/controller/inputs` can also serve as measurement sources chosen in the WebUI: a stove temperature for automatic fireplace mode, outdoor humidity for absolute-humidity control, and a room temperature for afterheat. Rooms selected as stove or outdoor sources never take part in air-quality decisions; send them with `"control": false`.

## Master rule

There is no normal controller ON/OFF. Pi becomes master automatically whenever the RS485 bus is healthy and HCP4 is absent. Any detected HCP4 FC06/FC16 activity immediately pauses Pi writes. During `unknown` arbitration state writes are blocked.
