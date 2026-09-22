# HCH5 Control – modern controller roadmap

This roadmap tracks the controller features that turn the Raspberry Pi replacement controller into a modern, local-first ventilation controller while preserving the HCH5's verified safety behaviour and automatic HCP4/Pi arbitration.

## Design principles

- Local-first: core ventilation control must continue to work without Home Assistant or internet access.
- HCP4 always wins: `active_master != PI_MASTER` means zero controller writes.
- No speculative Modbus writes. New hardware functions require a repeatable capture/readback/physical validation first.
- Requested state and physical readback are separate concepts (especially bypass).
- Sensor loss must degrade to a safe local fallback, not freeze the last high/low demand forever.
- Every automatic decision should be explainable in the UI.
- Persistent settings survive reboot and software updates.

## Already present in the beta controller

- Local Auto based on RH and CO2.
- Smart Auto with leased Home Assistant room observations and Local Auto fallback.
- Per-room enable/control/priority metadata.
- Fast RH-rise detection for shower-like moisture events.
- Six configurable fan profiles.
- Automatic HCP4/Pi master arbitration.
- Manual operation.
- Timed fireplace mode.
- Bypass request plus separate physical bypass readback.
- Water afterheat setpoint control using the verified binding.
- Weekly schedule.
- Night reduction with air-quality override.
- Vacation mode.
- Free cooling using room/outdoor temperature and physical bypass feedback.
- Stable/Beta update channels.
- Local filter-service timer while native filter storage is being reverse engineered.

## Next controller features

### 1. Quick Boost

Add explicit 15/30/60 minute boost presets. The boost is an overlay rather than switching the base controller mode, so the controller automatically returns to Local Auto/Smart Auto/schedule afterwards.

Expose:
- active/inactive
- remaining time
- selected boost level
- reason/source = `quick_boost`

### 2. Vacation with automatic end

Use the existing `vacation_until` field as a real feature.

- Optional end date/time.
- Automatically return to the normal automation stack at expiry.
- Keep a manual "until I turn it off" option.
- Show the remaining duration in WebUI and Home Assistant.

### 3. Free-cooling anti-cycling and actuator awareness

The physical bypass actuator is slow. Add:

- configurable minimum ON time
- configurable minimum OFF time
- start qualification delay
- transition/pending state
- physical transition timeout used only as diagnostics, not as a reason to spam writes
- explicit reasons such as `qualifying`, `opening`, `active`, `minimum_on_hold`, `not_cooler_outside`, `outdoor_too_cold`

The request register confirms requested mode; `bypass_raw/bypass_active` remains the actual physical truth.

### 4. Sensor quality and stale-data guard

Track freshness for every measurement used by control logic.

- Local RH/CO2 freshness.
- HA room lease/freshness.
- Room temperature freshness.
- Outdoor temperature freshness.
- Reject impossible values.
- Surface `sensor_health` and the exact fallback reason.

Free cooling must stop/return to native AUTO if required temperature data becomes stale.

### 5. Humidity event control

The Smart Auto room engine already detects a rapid RH rise. Generalise it into a configurable moisture-event feature:

- rise threshold, e.g. +7 %RH / 10 min
- temporary boost floor
- configurable hold/clear time
- use absolute RH and RH slope together
- identify the controlling room

This should react to showers before an absolute RH limit is reached.

### 6. Occupancy / Away overlay

Home Assistant may supply a leased occupied/away signal. The Pi must never depend on it for basic operation.

When fresh and enabled:
- occupied: normal automation
- away: configurable minimum fan level
- air-quality and moisture events can still override Away
- stale occupancy input returns to normal local operation

### 7. Decision and event log

Create a persistent bounded event log for changes, not every controller tick.

Examples:
- `22:14 level 3 -> 4: CO2 Bedroom 1120 ppm`
- `22:21 level 4 -> 6: RH rise Bathroom +8.2 %/10m`
- `02:03 bypass AUTO -> ON: free cooling, room 24.1 C / outdoor 17.8 C`
- `02:04 bypass physical OPEN`
- `07:42 HA room lease expired -> Local Auto fallback`
- `08:12 HCP4 detected -> controller writes paused`

Show this in a dedicated WebUI activity view and include it in diagnostics/support exports.

### 8. Comfort/supply-air guard

Use existing verified temperature readbacks to avoid aggressive cooling/ventilation choices that would create uncomfortable supply air.

This is a policy layer only; it must not replace the HCH5's native frost/safety handling.

Potential settings:
- minimum preferred supply-air temperature during free cooling
- warning threshold
- optional free-cooling reduction before fully stopping bypass request

Do not implement new frost/heater writes without protocol proof.

### 9. Service and maintenance centre

Create a dedicated maintenance page:

- native filter state when reverse engineering is complete
- local filter estimate as fallback
- last filter replacement
- filter interval
- runtime/uptime
- fan RPM/status
- temperature sensor health
- RS485 health
- HCP4/Pi arbitration history
- update channel/version/build
- backup/export controller configuration

### 10. Presets/scenes

User-friendly presets built from existing safe controller functions:

- Home
- Away
- Sleep
- Party/Guests
- Shower boost
- Fireplace
- Vacation
- Free cooling

Presets are controller overlays and should show duration and return behaviour.

## UI architecture

The WebUI should present three layers clearly:

1. **What is happening now** – physical fans, temperatures, actual bypass, afterheat and air quality.
2. **Why** – active control source, controlling room/metric and decision reason.
3. **What will happen next** – timers, schedule boundary, minimum-on/off hold, vacation expiry and pending bypass movement.

All pages should use the same navigation shell, sidebar width, theme and page grid to avoid layout shifts between Overview, Technique, System, Diagnostics, Updates and Settings.

The application root should default to Overview. Deep links such as `/?tab=system` may open a requested page once, but the normal root remains Overview.

## Native filter discovery

The current local filter timer is temporary/fallback functionality. The HCH5 appears to have a physical filter-reset interaction on the unit, so the native filter state may live on the main controller PCB rather than only in HCP4.

The discovery task should determine:

- whether a direct unit reset generates RS485 traffic
- whether any readable register changes before/after reset
- whether the state survives HCP4 removal and unit power cycling
- the exact read register(s), scale and reset semantics
- whether HCP4 register 168 is only interval/configuration, a reset command, or both

Until this is proven, HCH5 Control must not invent a native filter-reset write.
