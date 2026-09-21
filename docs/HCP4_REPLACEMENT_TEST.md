# Experimental HCP4 replacement controller

Test controller for HCH5 MK1 + HAC1 with HCP4 physically disconnected.

## Architecture

The Raspberry Pi owns the controller. Home Assistant and the WebUI are clients only:

```text
WebUI ----\
           > ControllerEngine -> verified live-gateway write functions -> HCH5/HAC1
HA -------/
```

Home Assistant may improve demand calculation, but loss of HA must never stop local ventilation. `smart_auto` therefore falls back to `local_auto` after the configured heartbeat timeout.

## Six ventilation levels

The controller uses six editable profiles. Extract is always required to be greater than supply, and both fan percentages must rise monotonically through the levels.

Default test profiles:

| Level | Extract | Supply | Purpose |
|---|---:|---:|---|
| 1 | 25% | 13% | Low |
| 2 | 40% | 28% | Intermediate low |
| 3 | 55% | 43% | Normal |
| 4 | 70% | 58% | Intermediate high |
| 5 | 85% | 73% | High |
| 6 | 100% | 88% | Boost |

25/13, 55/43, 85/73 and 100/88 are observed HCP4 pairs. Levels 2 and 4 are conservative interpolated starting points, not claimed Dantherm factory values. All six profiles are editable in the controller WebUI so they can be balanced against the real installation.

## Local Auto without Home Assistant

`ControllerEngine` consumes the HCH/HAC1 values already decoded by the gateway:

- relative humidity
- CO2
- outdoor temperature (reserved for later bypass refinement)
- room/extract temperature (reserved for later bypass refinement)

Defaults:

- normal level: 3
- RH setpoint: 50%
- RH hysteresis: 3 percentage points
- CO2 setpoint: 800 ppm
- CO2 hysteresis: 100 ppm
- RH step: +1 ventilation level per 5 percentage points above setpoint
- CO2 step: +1 ventilation level per 200 ppm above setpoint
- ventilation increases immediately
- downshift is delayed 5 minutes and requires demand below hysteresis
- level 6/Boost is held for 10 minutes by default

All values are persistent and editable in the WebUI.

## Afterheat

The WebUI exposes the HAC1 supply-air afterheat setpoint. `None/Auto` means the controller does not force a value. An explicit value is restricted to 5..40 °C and is written only when changed.

The controller must reuse the physically observed/verified HAC1 FC16 setpoint write sequence from the local gateway/captures. It must not invent a new afterheat register write.

The HCH5/HAC1 remains responsible for the actual valve/frost/afterheat regulation. This controller does not implement or overwrite frost/defrost logic.

## Bypass and fireplace

Both must use the already hardware-tested functions in the installed monolithic Pi gateway. `bypass=auto` currently means preserve/native state; only explicit `open` or `closed` generates a command in the test controller.

## Safety

- Disabled by default on first deploy.
- HCP4 must be physically disconnected before active controller mode is enabled.
- WebUI/HA submit intent; neither writes Modbus directly.
- Persistent config is written atomically.
- Active writes are deduplicated; unchanged desired state does not create repeated traffic.
- Runtime applies at a bounded 2-second tick and survives hardware exceptions.
- No fan-off control is exposed in this test controller.
- No unknown register scanning.
- No invented frost/defrost/afterheat writes.
- HCH5/HAC1 native regulation remains authoritative.

## Existing verified evidence must be reused

Do **not** reverse-engineer already-known HRC2/HCP4 behaviour again. Before binding active control, inventory and cross-reference:

1. `MRDonnii/dantherm-hch-passivelink` current `tests/test_parser.py` and parser implementation.
2. Git history for parser/mode/afterheat work.
3. The deploy host's local checkout, especially any untracked `docs/captures/**`, `analysis.md`, JSONL/raw capture files and test scripts. Run `git status --untracked-files=all` before changing or cleaning anything.
4. The installed monolithic Pi gateway, whose hardware-tested write functions take precedence over reconstructed writes.

Concrete evidence already preserved in the main repo tests includes:

- fan pairs 25/13, 55/43, 85/73 and 100/88
- register 143 sequences used to distinguish manual/auto/night transitions, including 172, 189 and 200
- night transition with 143=172 followed by both fan registers
- HAC1 connected state on register 146 including value 3
- HAC1 FC16 blocks for optional thermostat states and supply-air afterheat setpoint

## Runtime/API integration contract

Instantiate one `ControllerRuntime` inside the actual gateway process and feed it the same shared decoded state dictionary used by the dashboard.

Bind `HardwareAdapter` only to functions proven on the real installation:

```python
HardwareAdapter(
    write_fan_pair=<existing verified write_pair wrapper>,
    set_bypass=<existing verified bypass function>,
    set_fireplace=<existing verified fireplace function>,
    set_afterheat_setpoint=<verified HAC1 setpoint function/capture implementation>,
)
```

Required authenticated WebUI endpoints:

- `GET /api/controller/state` -> `runtime.snapshot()`
- `POST /api/controller/config` -> `runtime.configure(json_body)`
- `POST /api/controller/heartbeat` -> `runtime.heartbeat(demand)` for HA

`POST /api/controller/config` must use the existing login + CSRF checks. The HA heartbeat endpoint must use a machine credential/token or an equally strict existing authenticated channel; do not expose an unauthenticated write endpoint.

Serve:

- `/controller` -> `gateway/webui/controller.html`
- `/assets/controller.js`
- `/assets/controller.css`

Add a Controller/Styring link or tab to the existing dashboard without changing the current visual design unnecessarily.

## WebUI controls

The test page already contains:

- controller on/off
- Local Auto / Smart Auto / Manual
- large level 1..6 buttons
- live RH + CO2
- RH setpoint/hysteresis
- CO2 setpoint/hysteresis
- normal local level and downshift delay
- afterheat setpoint Auto/18/20/22/24 and +/-
- bypass Auto/Open/Closed
- fireplace toggle
- editable extract/supply percentages for all six levels
- actual state, last write, error and uptime diagnostics

## Acceptance before multi-day testing

1. HCP4 physically disconnected.
2. Backup live gateway and WebUI.
3. Existing read/TCP/HA data path remains healthy.
4. Controller deployed disabled and WebUI loads.
5. Manual level 3 produces 55/43 and corresponding physical RPM change.
6. Verify levels 1..6 one at a time against actual percentages/RPM; abort on unexpected behaviour.
7. Explicit afterheat setpoint changes are observed correctly and HAC1 continues autonomous regulation.
8. Local Auto responds to safe RH/CO2 test conditions without write storms.
9. Smart Auto falls back to Local Auto after HA timeout.
10. Service restart restores persistent config and continues safe local operation.
11. RS485/write exceptions remain bounded and visible instead of looping aggressively.

Do not merge the draft PR until the physical multi-day test is complete.
