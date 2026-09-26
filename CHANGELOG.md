# Changelog

## 1.2.0-beta.73

- With a measured T2 before the afterheat coil the controller now computes: recovery on the supply side, (T2 − T1) / (T3 − T1), which is where the heat ends up; the heat the exchanger hands to the supply air in W; the afterheat lift T2AH − T2; and the heat the afterheat coil adds to the air in W. Watts use the supply airflow of the running fan level (measured if entered under sizing, otherwise from the fan profile), which is reported as well. Without a T2 sensor these stay empty.
- The overview shows the four values under "Beregnet fra målt T2", and the loft temperature as a status pill when a sensor has the "Loftrum" role.
- Changes by Claude AI.

## 1.2.0-beta.72

- Extra 1-Wire sensors: any DS18B20 soldered onto the Pi's 1-Wire bus beyond the afterheat water flow/return pair appears under Indstillinger → Følere, where it gets a role and a name. "T2 · før eftervarme" becomes the measured T2 in the supply duct before the coil; "Loftrum" and own names are reported to Home Assistant through the controller state. The water flow/return sensors stay with the 1-Wire service.
- The drawing labels T2 on the duct between the unit and the afterheat coil: "T2 · målt" from the sensor, otherwise "T2 · beregnet" from T1, T3 and the recovery.
- "Luft før varmeflade" no longer shows the unit's T2 register, which only repeats T2AH; it is empty until a T2 sensor is fitted, and the estimate is reported separately.
- Changes by Claude AI.

## 1.2.0-beta.71

- Fix the light theme. The dashboard layer used fixed dark colours, so in light theme the page background, top bar, cards, status pills, active buttons and several panels stayed dark while the text turned dark. Every page now takes its colours from the light theme tokens, and the unit drawing uses the same light palette as the Home Assistant card. The sidebar stays dark on purpose; the dark theme is unchanged.
- Changes by Claude AI.

## 1.2.0-beta.70

- Fix the unit's T2 staying frozen with the Pi as master. With the external HAC1 afterheater the HCH5 has no live T2 of its own: HCP4 read HAC1's T2AH and wrote it to the unit (register 146=3, then 147=T2AH) every ~3 s, and the unit reported that as T2. The Pi now does the same, only as master and only with a fresh T2AH, so T2 on the unit, in the HAC1 temperature block and in Home Assistant follows the real supply air again. Found in the 2026-09-23 bus captures: 402 of 415 writes were read back as the next T2.
- Air colours follow temperature and are relative to the warmest and coldest air in the drawing, so the warm side of the exchanger is always redder than the cold side; they fade through the core and the afterheat coil. The supply between core and coil follows T2AH while the afterheat is off.
- The exchanger is drawn solid; tapping it shows the air passing through for a minute. Tapping the recovery value opens its 24-hour history.
- Changes by Claude AI.

## 1.2.0-beta.69

- The water coil shows the water flowing while the afterheat is active: light bands and small bubbles move from the flow pipe through the coil to the return, and the water stands still otherwise. When flow and return differ, the hotter end is red and the water fades through orange to blue at the colder end; equal temperatures give one colour from blue (cold) through orange to red (hot).
- Changes by Claude AI.

## 1.2.0-beta.68

- Water coil colours follow the water temperature from flow to return: the coil tube no longer sits on a fixed brown outline that made it look hot regardless of the readings, and the colour scale is finer between 15 and 35 °C where the coil normally runs. Equal flow and return temperatures give the same colour all the way round.
- Changes by Claude AI.

## 1.2.0-beta.67

- House and airflow: the base level is chosen with an Auto/Manuel switch instead of a checkbox. Auto uses the level calculated from the house size (shown next to the switch); Manuel shows the Normal level field right there so you can set it yourself.
- Changes by Claude AI.

## 1.2.0-beta.66

- House and airflow: the calculation (volume, requirement, base level, lowest level and the level table) now follows the fields while you type, so you can see what a different house size does before saving. Control still uses the saved values.
- The measured-airflow fields show the estimate for each level in grey, so the table is no longer a column of empty boxes; type a measured value to replace it.
- Changes by Claude AI.

## 1.2.0-beta.65

- CO₂ calibration: a new setting under Indstillinger → Air quality adds a fixed offset (−1000 to +1000 ppm) to the unit's own CO₂ sensor, so it can be matched to trusted room sensors. Smart Auto and Local Auto control on the corrected value, and the WebUI, MQTT and Home Assistant show it. The raw reading stays available as `co2_raw`, and the setting shows raw and corrected values side by side.
- Changes by Claude AI.

## 1.2.0-beta.64

- Afterheat room control defaults to Automatic: the average of the Home Assistant rooms that have a temperature, leaving out bathrooms and rooms used as stove or outdoor sensors, and T3 extract air only when no such room exists. Every installation adds its own rooms in the HCH PassiveLink integration; the WebUI explains where and shows which source is used right now.
- Changes by Claude AI.

## 1.2.0-beta.63

- Preserve HAC1 register 184 when refreshing T1–T5. A disconnected HRC2 room sensor is no longer replaced with T3 extract temperature in the T5 register. If HAC1's T5 word cannot be read, skip that temperature-block write.

## 1.2.0-beta.62

- The overview diagram shows a "Styring nu" panel below T4: what currently decides the ventilation (Smart Auto, Local Auto, night, vacation, Quick Boost, free cooling, dry-air protection, fireplace or HCP4), the level and the reason in plain Danish, e.g. "CO₂ 722 ppm ved anlæggets egen føler".
- Changes by Claude AI.

## 1.2.0-beta.61

- Afterheat room control now uses T3 extract air (the house average, always measured by the unit) by default. The HRC2 T5 sensor stays selectable but is marked unreliable, because it is not updated once the Pi replaces HCP4.
- Changes by Claude AI.

## 1.2.0-beta.60

- Split Indstillinger into sections (House and airflow, Air quality, Moisture and dry air, Night, Afterheat, Free cooling, Fireplace and stove, Interface, Security). Every field has an explanation, and the page follows a new Dansk/English language choice under Interface.
- House sizing: enter heated floor area, ceiling height, bathrooms and utility rooms. The controller calculates the BR18 requirement (0.3 l/s per m² plus wet-room extract), estimates airflow per level from the HCH5's 375 m³/h, accepts measured airflows from the commissioning report, and can set the base level and a reduced minimum that night, vacation and dry-air protection never go below.
- Humidity by absolute water content: with an outdoor humidity source, the humidity demand is ignored when outdoor air would not dry the house. Dry-air protection caps the level when indoor air is dry and CO₂ is fine.
- Afterheat can follow the room temperature (T3 extract air by default, the average of Home Assistant rooms, one room, or the HRC2 T5 sensor, which is unreliable without HCP4): the supply setpoint moves one degree at a time between a lowest and highest value. Only the existing afterheat setpoint write is used.
- Automatic fireplace mode held by a stove temperature (with start/stop hysteresis) or an external switch via `POST /api/controller/signals`, with afterrun and a maximum duration. Turning fireplace mode off manually waits until the signal clears.
- Home Assistant rooms used as stove or outdoor sensors never drive air-quality decisions.
- Changes by Claude AI.

## 1.2.0-beta.59

- Add a water afterheat coil drawing, chosen under Indstillinger → Eftervarme (Elvarmeflade / Vandbåren varmeflade). The copper coil and its flow and return pipes are tinted by the measured water temperatures, and the water only moves while the afterheat is active. The choice is stored in the controller config as `afterheat_coil` and never triggers RS485 writes.
- Move the HAC1 controller onto the RS485 line between the unit and the Raspberry Pi, clear of the coil, and reroute its frost and valve leads; with the water coil the valve sits on the return pipe.
- Changes by Claude AI.

## 1.2.0-beta.58

- Keep the admin service available when a saved CPU power profile is unsupported on another Raspberry Pi model.

## 1.2.0-beta.57

- Rework the System page with clearer resource and service status, selectable persistent Raspberry Pi power profiles, Wi-Fi scanning and secure Wi-Fi login from the authenticated WebUI.
- Detect network boot and local disk/SD boot separately. Keep Ethernet preferred when both Ethernet and Wi-Fi are connected.
- Persist Wi-Fi profiles for NFS boot where NetworkManager's plugin and profile directories require RAM-backed mounts; normal SD-card installations use NetworkManager's standard persistent storage.

## 1.2.0-beta.56

- Serve the branding images before login from the controller WebUI server used on the Raspberry Pi.

## 1.2.0-beta.55

- Add matching HCH PassiveLink branding to the WebUI navigation, login, favicon and touch icon. Make image assets available before and after login.

## 1.2.0-beta.54

- Remove the leftover dashed T2AH sensor lead to the removed marker beside the afterheat coil.

## 1.2.0-beta.53

- Remove the small duplicate T2AH temperature pin beside the afterheat coil; keep the large T2AH reading on the supply-air pipe.

## 1.2.0-beta.52

- Remove the T2-before-afterheat and HRC2 room T5 readouts from the HCH5 overview card and mobile summary while their readings are unreliable. This is display-only; the gateway values and controller measurements are unchanged.
- Keep T2AH, frost, T1, T3, T4, and afterheat-water readings on the card.

## 1.2.0-beta.51

- Enable read-only active temperature polling by default in the controller-aware gateway, while preserving `serial.active_reads_enabled: false` as an opt-out. Pause Pi polls when HCP4 sends valid FC03/FC04 reads or FC06/FC16 writes, and resume only after the configured quiet timeout.
- Track HCP4 read requests separately from response frames and ignore echoes of the Pi's own active reads, so automatic bus arbitration does not mistake the Pi's polling for HCP4 activity.
- Keep T3/T5 setpoints local-only until verified hardware write mappings are available.

## 1.2.0-beta.50

- Hide T2, T2AH, HAC1 frost, and HRC2 T5 readings when no valid sample arrives for 45 seconds; stale and unverifiable historical readings appear as gaps.
- Prevent temperature diagram fallbacks from displaying T2 as T2AH or extract temperature as room/T5.
- T3/T5 setpoints remain local-only until verified hardware write mappings are available.

## 1.2.0-beta.49

- Click any temperature reading in the HCH5 unit overview to see its last 24 hours in a popup. The chart shows values and time at the hovered point; the popup works with mouse, touch and keyboard.
- The afterheat-water card is larger and shows Frem, Retur and Afkøl (Frem minus Retur). Each reading has its own history graph.
- Store the T2AH and frost readings in the existing bounded history database. Their graphs fill from the first sample after this update; older samples cannot be reconstructed.

## 1.2.0-beta.34

- The exchanger now says when the bypass damper travels: "Åbner bypass" or "Lukker bypass" with how far open it is in % (the damper's own 0-255 readback) and a bar that follows it, while the damper blade, fog cross-fade and actuator animation keep running. A forced-open request shows "Åbner bypass" from the moment it is read back, because the real damper is slow: on the live unit it took 181-189 s from On to fully open in four runs and about 3 minutes to close, and the reported position moves in coarse steps that can hold for over a minute. The Bypass-styring card and the Teknik page show the same %.
- Better 3D in the unit drawing: the far-end outdoor-air and exhaust ducts run off backwards, narrowing and fading out before their open ends come into view, with T1/T4 where the air fades out; the fans are seen slightly from behind at an angle, with drum and motor can; the core and the filters show their depth in the cabinet's projection, and the open front shows the cabinet's floor and right-hand wall.
- All labels and readings in the drawing are considerably larger, the drawing fills the card width without empty bands, and the readback row below it stacks its texts so they no longer wrap.
- Fixes the afterheat coil's pipes, which were never drawn since 1.2.0-beta.22 because their SVG path was malformed; they now glow when HAC1 heats.

## 1.2.0-beta.33

- Keeps the afterheat card compact during the summer stop: the lockout notice replaces the RS485 selection and the detail line instead of being added below them, and it is sized to the card. Temperatures keep their value and "°C" on one line.

## 1.2.0-beta.32

- Fixes the unit's left end panel looking like an open door: the top and the afterheat end are now drawn in one consistent oblique projection (depth going up-left) as closed metal faces, with the duct stubs leaving the end panel.
- The diagram is seen from the afterheat end: a slight perspective turns the exhaust end away from the viewer while the afterheat side stays in front.

## 1.2.0-beta.31

- The afterheat card on Overview now says plainly when HAC1 is locked by the 15 °C outdoor summer stop ("Spærret af HAC1: udetemperaturen er … Eftervarmen tænder først, når det er under 15 °C ude"), the status reads "Spærret af sommerstop" instead of "Inaktiv", and the diagram shows a "Sommerstop · ude ≥ 15 °C" badge on the HAC1 coil and "Spærret" in the readback row.
- Animated bypass damper: the blade on the lower fan motor turns with the damper position (`bypass_raw`/255), the extract fog cross-fades from the core route to the bottom channel as it opens and back as it closes, the channel lights up with the position, and the orange actuator pulses while it moves. The callout and readback show "Åbner…"/"Lukker…" during travel. Direction follows the position change (the unit opens the damper by itself in Auto), and a damper that jumps straight from closed to open is still shown travelling over 2.6 s.

## 1.2.0-beta.30

- Redraws the unit interior from photos and CAD of the real HCH5: the core is now the elongated hexagonal counter-flow exchanger with its P1-P4 ports (P1 outdoor in and P4 exhaust out on the right, P3 extract in and P2 supply out on the left), the filter cassettes stand slanted in the top corners, the supply fan sits between the outdoor filter and P1, and the extract fan sits after P4 at the bottom right. The old chamber grid is gone.
- The bypass damper now sits on the lower (extract) fan motor with its orange actuator at the bottom. In bypass, the extract air leaves the core out and runs along the highlighted channel beneath it, through the open damper and the extract fan to exhaust; supply always crosses the core.
- The bypass status callout sits by the damper, and the RS485 cable leaves the unit's control box at the bottom left.

## 1.2.0-beta.29

- Restores the 1.2.0-beta.23 updater hotfixes that the afterheat beta line (beta.26-28) was branched without: the admin service may write its state directory again, `update.sh` no longer write-probes `/var/lib/dantherm-hch5-ha` inside the admin sandbox (the cause of "install: cannot change owner ... Read-only file system" when updating from beta.27 to beta.28), and a manual update check bypasses the 5-minute cache so new betas appear immediately.
- Brings in beta.23's canonical T1-T4 publishing and HAC1 180-209 snapshot mapping (T2 before the coil, T2AH after it, frost sensor).

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
