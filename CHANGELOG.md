# Changelog

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
