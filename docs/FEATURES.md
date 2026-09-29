# HCH5 Control: complete feature list

HCH5 Control adds a local Raspberry Pi controller, a responsive WebUI and an optional Home Assistant connection to a Dantherm HCH5 MK1 with HAC1. The [animated overview](images/1.3.3/overview-page-dark.gif) shows version 1.3.3 with example readings.

Features that depend on Home Assistant, a power meter or extra sensors are marked below. The Pi's normal control continues locally when Home Assistant is unavailable.

## Ventilation control

- **Local Auto:** adjusts the six configurable fan levels from the unit's own CO₂ and humidity readings.
- **Smart Auto:** combines local readings with fresh Home Assistant room readings. Rooms can have priorities or be monitored without controlling the fans. Stale room data expires, and control falls back to local inputs.
- **Manual:** holds the selected level from 1 to 6.
- **Fan profiles:** separate supply and extract percentages for each level, with feedback from actual fan RPM.
- **Temporary OFF:** stop with 1, 4 or 8 hour presets, until the next morning, or until manually restarted. The previous operating state returns when the timer ends.
- **Quick Boost:** a timed high level for 15, 30 or 60 minutes.
- **Current-decision display:** shows which mode or automation chose the running level and why.

## Air quality and comfort

- Adjustable CO₂ and humidity limits, step size and hysteresis; a calibration offset for the unit's CO₂ sensor.
- Bathroom drying reacts to high or rapidly rising humidity, can reach its own drying level even during night mode, and steps back down as the room dries.
- Outdoor humidity from an optional Home Assistant room sensor or selected weather entity can prevent a humidity boost when outdoor air would not dry the house. Dry-air protection can limit ventilation when indoor air is already dry and CO₂ is acceptable.
- Optional **indoor PM2.5** from Home Assistant rooms can raise Smart Auto's level. Its threshold, step size, hysteresis, maximum level and participating rooms are configurable. It does not lower a level requested for CO₂ or humidity.
- **Weather checked against T1:** the top bar shows measured T1; an optional HA weather entity adds conditions. Its humidity can inform the dry-air decision only when data and T1 are fresh and the weather temperature is within 6 °C of T1.
- **Free cooling:** requests bypass and a minimum fan level when indoor and outdoor temperatures make cooling useful. Thresholds, hysteresis, start delay and minimum on/off times are configurable.
- **Bypass Auto/On:** shows the requested setting separately from the actual damper position and travel. The animated diagram follows the physical readback.
- **Fireplace mode:** timed manual activation or automatic activation from a Home Assistant stove temperature or external switch, with hysteresis, afterrun and maximum duration.
- **Bål i haven:** temporarily stops the unit for 30 minutes to 3 hours, then restarts it automatically.

## Schedules and holidays

- Visual seven-day planner with multiple periods per day; click to add, drag to move or resize, and edit in 15-minute steps. Periods can cross midnight.
- *Grundtrin* periods replace the normal base level while air-quality demand can raise it; *Mindst* periods set a minimum. Copy periods or days and start from weekday/home-working templates.
- Planned holidays have a start, end and level; they begin and end automatically. Night reduction has its own hours and level, with air-quality demand still considered.
- The planner shows what is active now and what change comes next.

## Airflow design and balancing

- House-size settings use heated area, ceiling height and wet rooms to calculate a design airflow and suggested base level. Fan airflow estimates improve with measured fan RPM and commissioning data.
- Automatic air balance aims for a configurable extract-air share above supply air. Measured supply/extract airflow takes priority; otherwise the controller can learn a duct ratio from suitable heat-exchanger measurements when a T2 sensor is fitted.
- The **Indregulering** page records rooms, valve types, areas and design supply/extract airflow. A technician can hold a fan level while measuring each valve in l/s, compare deviations, store measured totals and produce a printable report saved on the Pi.
- An overpressure alarm can be raised when the known or learned duct balance shows excess supply outside fireplace mode.

**Measurement limit:** estimated airflow and learned duct balance are models. A commissioning measurement is still needed to establish actual room and valve airflow; this is not a constant-airflow or pressure-controlled retrofit.

## Afterheat and sensors

- HAC1 afterheat setpoint with a 10–35 °C dial, plus/minus controls and an explicit confirmation before a change is sent. OFF remembers the previous setting.
- Optional room-temperature following can adjust the supply setpoint within configured bounds. HAC1 continues to own its valve and frost protection.
- The controller stops afterheat demand while the ventilation unit is temporarily OFF and restores the previous setting when it restarts.
- Optional DS18B20 1-Wire sensors can measure T2 before the coil, afterheat-water flow and return, loft temperature and named additional points. The UI distinguishes measured T2 from an estimate.
- Air temperatures, water temperature difference, heat-recovery efficiency, recovered heat and air-side afterheat lift/power are shown when their required readings exist.

## Monitoring, energy and history

- Animated airflow through the exchanger, fans, bypass and afterheat coil; live temperatures, fan RPM, CO₂, humidity, filter remaining life and controller/bus status.
- Graphs for air and water temperatures, fans, CO₂ and heat recovery, with selectable history ranges and 24-hour popups from the diagram.
- Today's electricity is shown from an optional Home Assistant energy meter when supplied; otherwise the Pi can estimate it from live power. Recovered and afterheat energy are air-side estimates. Optional electricity and heat prices add approximate kr figures.
- The System page shows Pi CPU load and temperature, RAM, disk, network, uptime and service status, with resource history.
- The History page also records setting changes with their source, and alarm start/clear events with duration. Administrators can see login and user-management events.

**Energy limit:** afterheat energy is not measured water-side heat consumption. Recovered heat multiplied by a heat price is a theoretical replacement value, not a measured bill saving. Kr figures use the current price rather than historical tariff intervals.

## Diagnostics and fault notification

- Active alarms cover RS485 health, frost risk, weak or inconsistent recovery, bypass failing to close, afterheat without an air-temperature lift, missing 1-Wire sensors, rising fan power relative to a clean-filter reference, overpressure and lost Home Assistant contact during Smart Auto.
- Alarm history is kept on the Pi, including HCP4 takeovers, even when mail is disabled. Safe read-only system tests and a downloadable diagnostic report help troubleshooting.
- Optional SMTP service supports test mail, chosen recipients, severity threshold, repeat interval for ongoing alarms and resolved mails. The login page can mail a single-use password-reset link to an account with an email address.
- Filter remaining life and a fan-power indicator are visible. The power indicator requires an optional unit power meter; it is not a differential-pressure measurement across the filter.

## Home Assistant integration

- Read-only raw RS485 mirror on TCP `4196`, plus an authenticated controller API on port `8080` for control intent and room, power, daily-energy and price inputs. Home Assistant never writes Modbus directly.
- The WebUI can show, copy and rotate the controller API key. It reports last Home Assistant contact and rejected key attempts; Smart Auto makes its local fallback clear if Home Assistant data stops arriving.
- The separate HACS integration exposes unit data and controller options. A matching HCH5 Live Card is available from [Smart Home Cards](https://github.com/MRDonnii/ha-smart-home-cards).

## Accounts, system and updates

- Separate **Administrator**, **Tekniker** and **Bruger** logins. Technician access can expire; accounts can be disabled or removed. The server enforces roles on every request, including for sessions already open.
- Users can manage their own account details. Administrators manage users; administrators and technicians can configure mail. Password hashes, sessions, CSRF protection and login rate limiting protect the WebUI.
- System controls include Pi power profiles and Wi-Fi setup. The WebUI offers Stable/Beta update channels with preflight checks, backups, service health checks and rollback on failure.
- Responsive desktop/mobile layout, dark and light themes, Danish/English settings, reduced-motion preference and optional Home Assistant weather conditions beside measured T1.

## RS485 safety boundary

The Pi transmits control frames only when it is the active master and the bus is healthy. An HCP4 writing on the bus takes priority; unknown or unhealthy state blocks Pi writes. Read-only observation and Home Assistant entity data can continue when control writes are blocked. Hardware changes and control behaviour still require commissioning on the actual installation; see [installation](installation.da.md) and [safety model](../README.md#safety-model).
