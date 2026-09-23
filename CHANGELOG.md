# Changelog

## 1.2.0-beta.28

- Mirrors the Overview unit diagram to match the real HCH5: outdoor air (T1) and exhaust (T4) connect on the right, where both fan motors sit (supply fan in the outdoor stream before the exchanger, extract fan in the exhaust stream after it); extract (T3) and supply connect on the left, where the supply duct feeds the external HAC1 afterheat coil.
- Duct stubs now leave the cabinet sideways as short horizontal pipes instead of round openings pointing at the viewer.
- Fixes the fog bands being cut off flat at the top and bottom: the fade mask used the default region of 120% of the fog group's geometric height, far smaller than the wide blurred bands.
- New fan impellers: seven backward-curved blades, metallic hub and a motion-blur disc while running, spinning around the hub without wobble.
- Adds the wiring: the RS485/Modbus RTU cable from the unit's control box to the HAC1 controller and the Raspberry Pi (data pulses while the bus is healthy), plus HAC1's signal wires to T2AH, the frost sensor and the valve.

## 1.2.0-beta.27

- Fixes Pi losing RS485 mastership every ~12 s while writing afterheat: HAC1 does acknowledge each FC16 block (~50 ms), but the ack was read 0.8 s late, fell outside the own-echo window and was mistaken for an HCP4 write, so the setpoint block was blocked. The ack is read immediately again and identified by its six header bytes, because HAC1 often garbles or drops its last CRC byte; a missing ack retries the block once.
- T5 (the HRC2 remote room sensor) never blocks afterheat any more: the value HAC1 holds is kept, falling back to T3 extract air.
- Documents and exposes HAC1's outdoor lockout: afterheat never switches on at 15 °C outdoor or above, whatever the setpoint. The controller state reports `actual_afterheat_outdoor_lockout`, and the Teknik page shows it as "Sommerstop", so a missing heat demand above 15 °C is not debugged as a fault.
- The afterheat +/- stepper now updates immediately and sends one command about 1.2 s after the last press, instead of saving and waiting for every single step.

## 1.2.0-beta.23

- Fixes the afterheat setpoint write failing with "missing FC16 afterheat echo": a missed echo on a live RS485 bus is now retried (fresh re-read + rewrite, up to 3 attempts) instead of failing on the first transient miss. The verified write frame and identity checks are unchanged.
- Fixes a CSS specificity bug where `overview.css` silently reintroduced a dashed pattern on top of the solid fog styling in `pro-dashboard.css`, which is exactly what made the airflow look thinner in some spots than others. Fog styling now lives solely in `pro-dashboard.css`.
- Redesigns the duct/temperature-port integration: normal-mode ducts extend further past the cabinet, and the four temperature readouts (T1/T3/T4/T2AH) are now semi-transparent duct-cap plates centred exactly on the flow centreline, so the fog visibly runs through them and fades out gradually afterwards via the existing mask, instead of the readouts floating separately from a flow that faded out well before reaching them.
- Investigated the "before heater" (T2) sensor: found that beta.22's `controller_runtime.py` already reads a canonical `supply_temperature` key (falling back to legacy `supply_temp`) for sensor identity independent of bus master, but `dantherm_gateway.py` never actually published that key — an incomplete migration, not a removed sensor. Completed it: both the passive (HCP4) and active (Pi-master) temperature-decode paths now publish `supply_temperature` plus a `temperature_source`/`temperature_sample_monotonic` pair, with a regression test covering it.

## 1.2.0-beta.17

- Reroutes the normal-mode supply/extract paths through the exact exchanger rotation center so they cross it as a clean X, matching real cross-flow.
- Removes the dash pattern from the fog layers so the smoke is one continuous, evenly solid band the whole way — no more thin/thick patches — using the previously densest opacity throughout.
- Enlarges the outdoor/exhaust/extract/supply duct ports, and fades the fog out with a mask as it approaches the ends of the flow paths instead of ending abruptly.

## 1.2.0-beta.16

- Builds the Teknik and System pages in the same visual style as Overview/Historik, both read-only: Teknik shows master arbitration, hardware-write safety state, the active decision and its reason, Smart Auto input freshness and hardware readbacks (from the existing `/api/controller/state`); System shows Pi CPU/memory/disk, network, service health (gateway/1-Wire/SSH) and version status (from the existing `/state.json` and update-check).

## 1.2.0-beta.15

- Fixes `update_check_failed: HTTP Error 403` from GitHub's unauthenticated API rate limit: `update_info()` now caches the version/build check for 5 minutes (shared across all WebUI tabs/sessions in the process) and falls back to the last known-good result instead of failing the request when GitHub is rate-limited or unreachable.

## 1.2.0-beta.14

- Replaces the thin dashed air-flow streaks in the Overview unit diagram with wide, heavily blurred, layered fog/mist bands that drift slowly through the whole heat-exchanger face, closer to how air actually spreads across it. A faint dashed guide line is kept for a clear sense of direction.

## 1.2.0-beta.13

- Builds the Historik page in the same visual style as Overview: range selector (1h/6h/24h/7d/30d), temperature, water, fan, CO₂ and heat-recovery charts backed by the existing `/history.json` sample store. Shows "Ingen data" instead of any fake values when a range has too few samples.

## 1.2.0-beta.12

- Fixes `unexpected afterheat source block` on real hardware: word 185 was only ever verified on bit 0, but live HAC1 traffic sets extra unrelated status bits (observed 8193 = 0x2001). The identity check, the passive parser and the setpoint poller now all check bit 0 instead of requiring an exact 1; word 187=15 stays a required constant and every other live word is preserved unchanged.

## 1.2.0-beta.11

- Slows the Overview air-flow and fan animations to a calm, subtle pace with less glow; direction stays clear, RPM still scales it moderately.
- Fixes afterheat setpoint writes (`unexpected afterheat source block`) by retrying the read/identity check instead of failing on the first transient bus mismatch; identity safety check unchanged.
- Splits bypass UI into requested (Auto/On) and actual (Lukket/Åben/Bevæger sig) state using reg68 request vs. the fn4 damper-position readback, and disables the buttons while the actuator is moving.

## 1.1.0-beta.1

- Makes the Pi an always-on controller candidate while HCP4 retains absolute priority.
- Enforces `master == PI_MASTER` at the serial-write boundary and shortens own-echo matching to 0.2 seconds.
- Adds dynamic Smart Auto metadata, priorities, monitor-only rooms, six-level demand and local-sensor combination.
- Adds a non-destructive `--beta` installer path for the controller-aware service and preserves controller/login state.
- Keeps bypass status read-only because no verified write sequence was found.

## 1.0.1 — 2026-09-21

- Added a one-click, single-file `.txt` debug report under Diagnostics.
- Bundled current PassiveLink state, service journals, seven days of system warnings, kernel warnings, Pi health, disk, memory and network status.
- Added bounded output, fixed read-only command allowlisting, concurrent-generation protection and automatic credential redaction.
- Added diagnostics tests and installation/privacy documentation.

## 1.0.0 — 2026-09-21

- Initial stable standalone WebUI release.
- Responsive live airflow, bypass, recovery and after-heater visualisation.
- Light/dark themes, history, diagnostics and state icons.
- First-user setup, login, account changes, logout and guarded login disable flow.
- Allowlisted Raspberry Pi power, service and CPU-profile controls.
- Home Assistant/HACS integration links.
- One-command Raspberry Pi OS, Debian and Ubuntu installer.
- Bundled receive-only 19200 8E1 gateway and RTU decoder with raw TCP mirroring for Home Assistant.
- Danish RS485 wiring, firewall, verification, upgrade and uninstall guide.
