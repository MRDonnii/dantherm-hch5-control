# Changelog

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
