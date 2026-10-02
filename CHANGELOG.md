# Changelog

## 1.4.5

- **Free cooling uses the real room temperature:** it took the room temperature from T5, the HRC2 remote's own sensor. Without an HRC2 the unit only repeats its last T5 word (seen stuck at 22.42 °C for days) and reports 0 after a power cut, so free cooling compared the outdoor air with 0 °C and never started. Free cooling now uses the same room temperature as the afterheat: by default the average of the Home Assistant rooms, else the extract air (T3). T5 only counts between 5 and 40 °C.
- Changes by Claude AI.

## 1.4.4

- **No more "missing FC16 acknowledgement" for the afterheat:** a capture of 457 setpoint writes on 2026-10-02 showed that HAC1 always answers after about 51 ms, but in about 5 % of the answers the first bytes are garbled when the bus turns around (`10 00 B9 …`, `40 41 00 B9 …`, `C0 10 00 B9 …`). The Pi required a perfect start, so it repeated the write, and when both answers were garbled it logged the error (about 50 times a day) and left a late answer on the bus that master arbitration could mistake for another master. The acknowledgement is now also recognised by its register, count and CRC; replayed against the capture, all 914 writes to registers 180 and 185 are acknowledged at the first try.
- Changes by Claude AI.

## 1.4.3

- **Filter status from the unit itself:** HAC1 keeps its own filter counter in block 1024 (slave 1), which the Pi already read without naming it: period in months (3–12), remaining life as 0–255 and hours since the filter was reset. Verified on 2026-10-02 with the filter reset button on the unit (from 249/235 h to 255/0 h, with nothing on the bus); a power cut leaves the counter alone. *Filter*, days left, status and the change date in the WebUI, MQTT and Home Assistant now come from it, also passively while the HCP4 is master, instead of the Pi's own timer, which now follows the unit.
- **Clogging measured at the same fan gears:** the fans hold their speed per gear whatever the filter (washed and new filters were within 0.5 % in rpm and watts at all four steps), so the clean reference is now the mean power per gear pair during the first 72 hours after a filter change, and *Filter · strøm* shows how far the power at the running gears has moved from it. The old per-level minimum gave nonsense at low steps (11.9 at step 1) and no longer matched after the change to four steps. The alarm is raised at ±15 % until dirty filters have been measured.
- Changes by Claude AI.

## 1.4.2

- **A step chosen by hand is used as chosen:** *Auto minimumsniveau* and *Auto maksimumsniveau* also clamped manual mode, so with the minimum at step 2 manual step 1 ran step 2. The Auto limits now only apply to automatic control (Local Auto, Smart Auto, schedule, night and the timed functions on top of them).
- Changes by Claude AI.

## 1.4.1

- **Vacation runs its own step:** *Auto minimumsniveau* is meant for an occupied house, so vacation is no longer lifted to it. With the minimum at step 2 and the vacation step at 1, vacation now runs step 1; the house-size minimum (*Reduceret minimum*) still applies. Home Assistant can switch vacation on and off (integration 0.8.1-beta.12), for example from the house mode.
- Changes by Claude AI.

## 1.4.0

- **Dantherm's four steps (new default):** the controller now runs the fan steps the way Dantherm's HCP4 panel and HRC 2 do (HCH 5 installation and service manual). Step 3 is the nominal airflow the house is commissioned to: supply and extract each get their own gear 46–91. Steps 2 and 1 lie one and two offsets below step 3 on both fans (factory 25 gears, 10–30 like the HRC 2), and step 4 is the maximum, per fan from step 3 up to gear 100. Step 4 chosen by hand runs for four hours and then returns to step 3, as on Dantherm's panel. Supply may never run a higher gear than extract.
- **Choose 4 or 6 steps:** *Indstillinger → Hus og luftmængde → Trinstyring* switches between the four Dantherm steps and the free six-step table of earlier releases. The switch happens at once, and every step choice (normal level, night, vacation, week plan, bathroom drying, free cooling, dry air, PM2.5, Quick Boost, Local and Smart Auto limits) moves to the step with the nearest fan gears. The other model's values and measured airflows are kept, so switching back restores them exactly.
- **Balance like on Dantherm's panel:** with *Luftbalance → Manuel* the balance is set with the supply and extract gears separately at step 3 (and step 4), like the HCP4's two potentiometers. A new *Balance* column shows at once how much more air extract gives on every step. *Auto* still solves the supply on every step so extract stays the chosen share above supply in m³/h.
- **Upgrade keeps the unit running as before:** an installation on six steps moves to four steps on the first start. The fan pair it ran (the manual step, else the normal step) becomes step 3, so the fans do not change; old step 4 becomes step 3, old step 6 becomes step 4, and every other stored choice follows the nearest gear pair. The old file is kept as `controller.json.six-steps.bak`, the six-step table stays stored for *6 trin*, and measured airflows stay with the steps they were measured at.
- **All control follows the step count:** Local Auto, Smart Auto (room priorities, CO₂/RH/PM2.5 steps, 10-minute RH rise, bathroom drying), night ceiling, week plan, vacation, free cooling, dry-air limit, house sizing (base and lowest step) and the air balance all work on the chosen steps. A Home Assistant integration that still asks for step 5 or 6 gets the highest step.
- **WebUI:** *Oversigt* shows 4 or 6 step buttons (with the step names and step 4's four hours), *Ugeplan* and *Indregulering* offer the steps that exist, and *Indregulering* suggests measuring at step 3 with four steps, like Dantherm's commissioning. The controller state has `fan_step_count`, `fan_settings`, `fan_levels`, `max_level` and `max_level_remaining_seconds`.
- Changes by Claude AI.

## 1.3.4

- **The WebUI no longer drops the connection:** every ten seconds one `/state.json` request waited for the 1-Wire service (1.7–6 s, because it read the DS18B20 sensors on every call) and for a dozen `systemctl`/`ip` calls. That was longer than the WebUI's 2.5 s poll timeout, so the top bar switched to *Afventer* and *Styring nu* went empty until the next poll. The 1-Wire and system values are now refreshed by a background thread, and a request only reads what it has cached. A 1-Wire service that has not answered for a minute is shown as unreachable.
- **1-Wire service reads in the background:** the DS18B20 service reads the sensors every 10 s and answers every request from the latest reading at once (Home Assistant, the WebUI and the controller asked it about 15 times a minute). A reading older than 60 s is reported as missing. The controller now takes the water flow/return temperatures from the service instead of reading those two sensors a second time, which halves the time the shared bus is busy.
- **One slow answer is not "offline":** the top bar, *Oversigt*, *Teknik* and *Home Assistant* only show *Afventer* after several failed polls in a row, and a poll is skipped while the previous one is still waiting.
- **Ended sessions go to the login page:** after a restart of the Pi service a login without *Husk mig* has ended. The Pi now answers data requests with 401 and `login_required`, and the WebUI opens the login page; before, it got the login page as data and stayed on *Afventer*.
- **Smaller and faster answers:** `/api/controller/state?compact=1` leaves out the decision and change logs (about 90 % of the 87 kB answer); the pages that poll every few seconds use it. JSON and text are gzip-compressed when the browser asks for it, and the content-named `v2-*.js`/`v2-*.css` files may be cached by the browser, so the 700 kB bundle is not downloaded on every page load.
- **Faster history:** 7- and 30-day history is thinned out in SQLite instead of in Python (1.2 s → 0.4 s for 7 days on a Pi 3), with the same points as before.
- Changes by Claude AI.

## 1.3.3

- Show the HCH5 measured outdoor T1 in the top bar instead of an Open-Meteo browser temperature.
- Accept an optional leased Home Assistant weather entity for condition display and, when explicitly selected, outdoor humidity control. Reject stale readings and weather temperatures that differ more than 6 °C from T1.
- Refresh the documentation and illustrated WebUI preview.

## 1.3.2

- **"Styring nu" stands straight:** the panel with the controller's current decision was part of the unit drawing, which is turned in perspective, so it leaned with it. It is now a flat label over the drawing in the same corner, with text that never gets smaller than a readable size. When the drawing is narrow (for example on a 1440 px screen, where the overview has two columns) it becomes a straight bar just under the drawing. On phones the same decision stays in the *Drift og styring* card.
- Changes by Claude AI.

## 1.3.1

- **Update check compares version numbers:** the beta channel offered 1.2.1-beta.13 to an installation already on 1.3.0, because any different version counted as an update. Versions are now compared by number (1.3.0 is newer than 1.2.1-beta.13 and 1.3.0-beta.x), and only a newer version is offered, on both channels.
- **API key for Home Assistant in the WebUI:** *Home Assistant → Forbindelse fra Home Assistant* shows the controller address and the API key, with buttons to show, copy and generate a new key (technicians and administrators). A new key stops the old one at once and is stored on the Pi (`controller-token.json`, mode 0600); `update.sh` uses it for its health check. Generating a key is logged in the alarm history.
- **Clear Home Assistant status:** the Pi records every request from Home Assistant and every request with a wrong API key. The top bar shows an *HA* chip (green when connected, red with *Ingen kontakt* or *Forkert API-nøgle*); with Smart Auto chosen and no data from Home Assistant, the Drift card says so and that the unit runs on its own sensors. The Home Assistant page shows the real status, the last contact and rejected attempts with the sender's IP; before, "Integration: Forbundet" only meant that the browser could reach the Pi. After five minutes without Home Assistant in Smart Auto an *ha_offline* alarm is logged and mailed like the other alarms.
- **The beta channel also follows stable releases:** a stable release newer than every beta is offered on the beta channel too, and the next beta after it (for example 1.3.1-beta.1) is offered once it exists.
- Changes by Claude AI.

## 1.3.0

Stable release. Everything from 1.2.1-beta.1 to 1.2.1-beta.13 (the details are in the beta notes below):

- **Users and roles:** several logins with the roles *Administrator*, *Tekniker* (everything technical, optionally time-limited) and *Bruger* (daily controls). Rules are enforced by the Pi on every request; the existing owner becomes administrator.
- **Mail service:** SMTP with provider presets and a test mail, fault mails for diagnostics alarms (severity, repeat and resolved mails) and *Glemt adgangskode?* links from the login page.
- **Ugeplan:** a week planner with several periods per day, drag to move and resize, *Grundtrin* periods that can lower the base level and *Mindst* periods as a floor, templates, copy to weekdays/weekend and holiday with a planned start and end.
- **Indregulering:** rooms with type, m², ceiling height and supply/extract; design airflow per valve after BR18 balanced against extract; recommended level; measuring mode with l/s per valve and deviation; a printable A4 report saved on the Pi.
- **Alarm history:** alarms and HCP4 takeovers logged when they start and clear, plus sign-ins and user changes for administrators.
- **PM2.5 (optional):** Smart Auto can raise the level on fine dust from Home Assistant room sensors, with a limit, step, maximum level and per-room opt-out.
- **Overview:** compact and symmetric, controls on the right and information on the left, one *Funktioner* card; *OFF* with presets, *Bål i haven* and afterheat changes confirmed in a popup.
- **Air balance:** extract a chosen share above supply in m³/h, a duct ratio learned from the exchanger heat balance, airflow following real fan speed, and an overpressure alarm.
- **Control and bus:** the Pi no longer hands the bus to HCP4 by mistake, the HAC1 connection no longer flickers, the temperature block to HAC1 keeps going, afterheat off while the unit is off, bathroom drying at night and stronger bathroom drying, and every setting change logged with who made it.
- **Larger text** in the whole WebUI, a neutral weather picker without a default location, and the project renamed to Dantherm HCH5 Control.
- Changes by Claude AI.

## 1.2.1-beta.13

- **Ugeplan (new page):** draw the week on a 24-hour timeline per day. Click a day to add a period, drag it to move it, drag its edges to change the length (15-minute steps), and click it to edit name, time, level and type. Up to 8 periods per day, and a period may run past midnight (for example Friday 21:00–01:00).
- **Two kinds of period:** *Grundtrin* replaces the normal base level, so "Ude · trin 1" can lower the ventilation while CO₂ and humidity can still lift it. *Mindst* is a floor that automation can only go above (what the old schedule did). Where periods overlap, the highest level wins; night reduction and the house minimum still apply.
- Copy a period or a whole day to weekdays, weekend or all days, or start from a template (*Arbejdsdage ude*, *Hjemmearbejde*). Changes are a draft until **Gem ugeplan**; **Fortryd** throws them away.
- The page shows what the schedule does right now, when it next changes and to which level, the night reduction as a hatched band and a line for the current time.
- **Holiday with a planned start:** choose from/to (or start now), the holiday level and quick lengths (3 days to 3 weeks). A planned holiday waits for its start and ends by itself.
- A plain *Bruger* may edit the week plan and holiday. The old single window per day keeps working until the week plan is saved.
- On phones the menu stays on one row whatever the role shows.
- **Alarm history (Historik):** every diagnostics alarm and HCP4 takeover is logged when it starts and when it clears, with how long it lasted, also when mail is off. Active alarms are shown at the top. Administrators also see sign-ins, failed sign-ins and user changes. The log keeps the latest 500 events on the Pi and survives restarts without logging an active alarm twice.
- **Indregulering (new page for technicians and administrators):** four steps.
  1. *Rum:* each room with name, type (living room, bedroom, office, kitchen, bath, separate WC, utility room, hallway, other), m², ceiling height and whether it has supply and/or extract; the type fills in sensible defaults.
  2. *Beregning:* design airflow per room after BR18 §447 (0.3 l/s per m²; kitchen 20, bath 15, WC and utility room 10 l/s extract). Supply is balanced against extract with the controller's air-balance setting and shared by floor area. Shows totals, air change rate and the lowest fan level that covers it, and can transfer area, ceiling height and wet rooms to Hus og luftmængde.
  3. *Måling:* run the unit fixed on the chosen level, enter measured l/s and the valve setting per valve, and see the deviation (±10 % OK, ±20 % adjust), totals and balance. The measured totals can be stored as measured airflow for that level.
  4. *Rapport:* site, address, owner, technician, company, instrument and notes; a report that prints on A4 or saves as PDF, with verdict, room table and signature lines. Reports can be saved on the Pi and printed again later.
- **PM2.5 (optional):** rooms from Home Assistant can send `pm25` (or `pm2_5`) in µg/m³ next to CO₂, humidity and temperature, as IKEA air-quality sensors report them. With *Brug PM2.5* on (Indstillinger → Luftkvalitet), Smart Auto raises the level above a limit (default 25 µg/m³, one level per 15 µg/m³, highest level 5). PM2.5 only raises the level, and each room can be left out.
- **Larger text in the whole WebUI:** labels, help text, inputs, buttons, tables and cards were 7–11 px and are now roughly 11.5–15 px (settings fields 13–14 px). Cards with several buttons (fireplace, Bål i haven) put the buttons on their own row, and the afterheat dial stacks above its readings when the card is narrow. The unit drawing is unchanged.
- **Compact, symmetric overview:** controls on the right and information on the left, in two columns that end at the same height. Quick Boost, bypass, free cooling, fireplace and Bål i haven are one *Funktioner* card with a row each instead of five separate cards. The decision box under the fan level is hidden on wide screens, where the drawing already shows *Styring nu*. The left holds the unit drawing, indoor climate, diagnostics, energy and the values calculated from a measured T2. On medium screens the right column is wider so the afterheat dial sits beside its readings, and the tiles adapt to the column width. The top bar wraps instead of scrolling sideways on narrow screens. At 2000 px the page went from about 1480 to 1150 px high.
- Changes by Claude AI.

## 1.2.1-beta.12

- **Users and roles:** several WebUI logins, each with a role. *Administrator* can do everything, including users and mail. *Tekniker* gets everything technical (advanced settings, sensors, Teknik, System, Home Assistant, Diagnostik, sniffer, updates, restart and mail) but not user management. *Bruger* gets the daily controls on the overview (mode, level, OFF, Quick Boost, bypass, free cooling, fireplace, Bål i haven, afterheat) and history. Users are managed under Indstillinger → Brugere.
- A technician account can get an **expiry date**, so access ends by itself after a service visit. Accounts can be disabled or deleted; role changes apply to open sessions immediately. The last active administrator cannot be removed.
- The server checks the role on every request; the menu and settings only show what the role may use. The existing owner becomes administrator, and the old login file is only rewritten the next time a user is changed or someone signs in.
- Top bar shows who is signed in, with the role and a log-out button. Indstillinger → Sikkerhed lets every user change their own e-mail, username and password.
- **Mail service (Indstillinger → Mail):** SMTP with presets for Gmail, Outlook.com, Microsoft 365, iCloud and one.com, and a test mail. The SMTP password stays on the Pi and is never sent to the browser.
- **Fault mails** to a list of recipients for the diagnostics alarms (no RS485 connection, frost risk, low recovery, bypass not closing, afterheat without effect, missing 1-Wire sensor, filter, overpressure) and when HCP4 takes over. Choose the minimum severity, a repeat interval while the alarm stays active and whether to mail when it clears.
- **Forgot password:** the login page shows *Glemt adgangskode?* and mails a single-use link valid for 30 minutes to users with an e-mail on their account. Administrators can also send a reset link from the user list.
- Changes by Claude AI.

## 1.2.1-beta.11

- **Air balance (Hus og luftmængde → Luftbalance):** with *Auto* every level keeps its extract percentage and the controller works out the supply percentage so extract is a chosen share (default 5 %, 0–20 %) above supply **in m³/h**, not in percent. The HCH5 fans turn at about 550 rpm at 0 %, so the old fixed 12-point gap gave about 30 % more extract at level 1 but only a few percent at level 6. The balanced percentages are written into the level profiles, so the engine, the house-size plan and Home Assistant all use them. While Auto is on, supply is set by the balance (changing it is refused with an explanation); switching to *Manuel* keeps the last balanced values.
- **Duct ratio:** supply and extract ducts rarely move the same air per rpm. The ratio comes from airflow measured at the valves when both sides are entered, else from the **heat balance of the exchanger** (below), else from a fixed value (1.00 = alike ducts).
- **Heat balance learning:** with a 1-Wire T2 sensor before the afterheat, the Pi compares the extract temperature drop (T3 − T4) with the supply temperature rise (T2 − T1). Only calm, cold periods count: the same fan pair for 30 minutes, then 15-minute windows with at least 8 K between inside and outside, no bypass, fireplace, frost or condensation in the core (dew point from the unit's humidity). Half of the fans' heat (from the power meter in Home Assistant, else a fan model) is taken out and counted as uncertainty. The learned ratio is used once at least 8 windows from two nights agree, follows new windows in small steps and survives summers without cold nights. *Nulstil læring* starts it over.
- **Measured airflow keeps its fan percentage:** a value from the commissioning report is tied to the percentage it was measured at ("ved %"), so the balance can change the level without misusing it. One measured value per side now corrects the airflow estimate on every level.
- **Overpressure alarm:** once the ducts are known (measured or learned), running with more supply than extract for an hour raises an info alarm, except in fireplace mode.
- Settings on a phone: wide tables scroll inside their card instead of widening the page.
- Changes by Claude AI.

## 1.2.1-beta.10

- **New name: Dantherm HCH5 Control.** The project is no longer only passive, so the repository is now `MRDonnii/dantherm-hch5-control` (the old URL redirects, so existing installations keep updating) and the Home Assistant integration is `MRDonnii/dantherm-hch5-control-ha`. Install paths on the Pi are unchanged.
- **Pi no longer hands the bus to HCP4 by mistake:** a late HAC1 acknowledgement of the Pi's own write was counted as a foreign write, which paused control about ten times a day. An 8-byte FC16 frame is now always treated as a response.
- **HAC1 connection no longer flickers:** the Pi's own T2 feed (register 146 = 3) was read as "HAC1 disconnected".
- **Temperature block to HAC1 keeps going:** if reading HAC1's T5 word fails once, the last value (up to 10 minutes old) is used instead of skipping the whole T1–T5 block. The error is logged at most every 15 minutes.
- **Airflow follows the real fan speed:** the air-side afterheat power and recovered heat scale the level's airflow by the actual supply rpm.
- **Who changed what:** every setting change is logged with its source (WebUI user or Home Assistant) and old → new value, shown under Historik.
- Changes by Claude AI.

## 1.2.1-beta.9

- The afterheat confirmation is now a popup over the thermostat card: old and new value, its own −/+ and Fortryd/Bekræft.
- Changes by Claude AI.

## 1.2.1-beta.8

- **Confirm afterheat changes:** +/-, the dial and the power button on the afterheat thermostat only change a draft. A box asks "Skift eftervarme fra 20 °C til 25 °C?" and nothing is sent before **Bekræft** is pressed; **Fortryd** keeps the current setting. A change is no longer sent by itself after a pause.
- Changes by Claude AI.

## 1.2.1-beta.7

- **Afterheat off while the unit is off:** standby and "Bål i haven" now also switch the afterheat off, so the water coil does not heat still air. The previous setting returns when the unit starts again.
- **Afterheat refreshed every 4 seconds again:** the beta.6 exception for outdoor temperatures of 15 °C or more is removed. HAC1 was seen heating at 17.7 °C outdoor, so the 15 °C summer stop is not reliable.
- A missing HAC1 acknowledgement is now logged at most once every 15 minutes, with a count, instead of a traceback on every attempt.
- The air-side afterheat power and recovered heat are 0 while the fans are stopped.
- Changes by Claude AI.

## 1.2.1-beta.6

- **No afterheat writes during the summer stop:** when the outdoor temperature is 15 °C or higher, HAC1 cannot switch the water afterheat on, so the Pi no longer rewrites the afterheat setpoint every 4 seconds. It writes only when the setpoint changes, and the 4-second refresh resumes by itself when it is colder than 15 °C. This removes the repeated "missing FC16 acknowledgement for register 185" errors in the log. The outdoor temperature block (register 180) is still sent so HAC1 keeps seeing the outdoor temperature.
- Changes by Claude AI.

## 1.2.1-beta.5

- **OFF in the level row:** "Ventilatorniveau" now has an OFF button. It opens a popup with presets: 1, 4 or 8 hours, until tomorrow at 07:00, or permanently until switched on again. Pressing a level switches the unit on at that level. The separate "Sluk anlæg" card from beta.4 is gone.
- Popups on the overview (OFF and the temperature history) are centred on the screen again.
- Changes by Claude AI.

## 1.2.1-beta.4

- **Sluk anlæg:** a new card (and in Home Assistant) switches the unit off for 1, 4, 8 or 24 hours or until switched on again. It uses the standby pattern of the HRC2/HCP4 controllers (the verified fireplace sequence with both fans at 0 %), rewritten every second, and restores the previous state when switched on. Boost, bonfire and fireplace cannot start while the unit is off.
- **Bål i haven switches the unit off** for the chosen time instead of running the fans at minimum, and starts it again by itself.
- Changes by Claude AI.

## 1.2.1-beta.3

- **Bål i haven:** a new card under the fireplace function (and in Home Assistant) runs both fans at the lowest speed (extract 11 %, supply 10 %) for 30 minutes to 3 hours (10–480 minutes via the API), closes the bypass, pauses free cooling and boost, and stops by itself. The fireplace function keeps priority.
- **Better airflow calculation:** airflow now follows fan speed (fan law) instead of the fan percentage. On the HCH5 the speed is about 557 rpm at 0 % plus 24 rpm per %, so the low levels move far more air than before. The Pi learns the exact curve of the unit from steady readings. For a 179 m² house, level 3 now covers the requirement, so the house-sized base level becomes 3 and the lowest level 1.
- Changes by Claude AI.

## 1.2.1-beta.2

- Bathroom drying is allowed at night: night mode no longer caps it at the night air-quality level. It still steps down as humidity falls. CO₂ and other rooms stay capped at night as before.
- Changes by Claude AI.

## 1.2.1-beta.1

- Bathroom drying: when bathroom humidity passes its limit, or rises 7 %-points within 10 minutes during a shower, Smart Auto starts at the bathroom's drying level (default 6, the highest) and steps down in proportion as humidity falls from its peak. Normal ventilation takes over below the limit minus the hysteresis. Previously a bathroom only added one level per 5 % RH and was capped at level 4.
- The bathroom setting is renamed "Trin ved udtørring" and explains the behaviour.
- Changes by Claude AI.

## 1.2.0

First stable release of the controller line. Compared with 1.0.1 (passive data bridge), HCH5 Control is now a local controller:

- The Raspberry Pi can become Modbus master with automatic HCP4 arbitration; unknown or unhealthy bus state blocks all writes.
- New WebUI: animated airflow drawing with bypass and afterheat water, dark and light theme, mobile layout, live weather, history, technique, diagnostics, system and settings pages.
- Local Auto, Smart Auto (Home Assistant rooms) and Manual with six fan profiles; weekly schedule, night reduction, holiday mode, free cooling, fireplace mode and bathroom humidity policy.
- Afterheat thermostat, summer stop, T2 before the coil and afterheat water flow/return via 1-Wire.
- Energy today: measured electricity from Home Assistant or the Pi's estimate, estimated afterheat and recovered heat, with approximate kr values.
- Home Assistant sends rooms, power, daily energy and prices through the authenticated controller API (HCH PassiveLink 0.8.0).
- New README with screenshots and GIF, and a Danish getting-started guide (`docs/kom-godt-i-gang.da.md`).
- Changes by Claude AI.

## 1.2.0-beta.83

- Home Assistant can now send the unit's measured kWh today and the current electricity and heat prices through the integration's controller options (HCH PassiveLink 0.8.0-beta.3); no YAML automation is needed. The overview then shows **Strøm i dag · målt** and approximate kr values.
- "Diagnose og energi i dag" shows all five tiles in one row on desktop.
- "Beregnet fra målt T2" moved into the afterheat card beside the indoor climate panel, as a compact 2 × 2 grid, so the overview is lower. The thermostat readings no longer run past the card edge in the narrow right column.
- The documentation link on **Opdateringer** points at the maintained branch.
- Changes by Claude AI.

## 1.2.0-beta.82

- Daily electricity (measured when HA supplies it, otherwise estimated), afterheat and recovered heat with approximate kr values from the current electricity and heat prices. Recovered heat × heat price is shown as a theoretical value, not a saving on the bill.
- **Opdateringer** links to the HA integration and the dashboard card in HACS and to the new setup guide `docs/energy-and-ha.da.md`.
- The afterheat water flow goes straight up into the afterheat coil instead of running under the HAC1 unit.
- New README screenshots and an animated GIF of the overview.

## 1.2.0-beta.81

- The content security policy allows the weather APIs used by the top bar.

## 1.2.0-beta.80

- Live weather and outdoor air status in the top bar.
- The afterheat water flow follows the incoming air.

## 1.2.0-beta.79

- The afterheat card is now a thermostat: a round 10–35 °C scale you can drag or tap, − / + and an on/off button that remembers the last setpoint. The arc glows orange while HAC1 heats, turns amber during the summer stop (with the reason), blue when ready and grey when off. Beside it: air before and after the coil, the lift, and what HAC1 has registered. One command is still sent once you let go.
- Changes by Claude AI.

## 1.2.0-beta.78

- The afterheat water flow and return are chosen under Indstillinger → Følere like the other sensors ("Eftervarme · frem" and "Eftervarme · retur", one sensor each). Until a choice is saved the 1-Wire service's own pairing is shown. The choice is published on `/api/onewire/water`, answered only on the Pi itself, and the 1-Wire service follows it (and saves it) when it runs alongside; without the WebUI the service works as before.
- Changes by Claude AI.

## 1.2.0-beta.77

- Indstillinger → Følere lists all 1-Wire sensors, including the afterheat water flow and return. Those two show their temperature and a fixed role; the 1-Wire service keeps owning them and they cannot be given another role. A flow or return sensor that stops answering now also raises the missing-sensor alarm.
- Changes by Claude AI.

## 1.2.0-beta.76

- The T3 and T5 setpoints are removed from the overview. They were only stored locally and never sent to the unit. The controller still accepts the fields so older Home Assistant versions keep working.
- Changes by Claude AI.

## 1.2.0-beta.75

- Diagnostics and protection. The controller now watches the unit and raises alarms once a condition has lasted a while, and clears them on its own: frost risk in the exchanger (exhaust T4 near 0 °C), low heat recovery, supply- and extract-side recovery disagreeing, the bypass not closing, the afterheat calling without warming the air, a 1-Wire sensor with a role not answering, no healthy RS485 bus, and the fans drawing more power than with a clean filter. The overview shows active alarms at the top.
- Fan power and filter: with a power meter on the unit (from Home Assistant) the controller computes the specific fan power, W per m³/s, and learns the clean-filter value per fan level; a filter reset starts it over. The overview shows how much more power the fans use than with a clean filter.
- Energy: recovered heat, afterheat and the unit's own consumption are counted as kWh totals that survive restarts, plus today's values and how many times its own power the unit recovers. Stored in `diagnostics.json` next to the controller state.
- Changes by Claude AI.

## 1.2.0-beta.74

- The unit's electrical draw from a power meter in Home Assistant (e.g. a Shelly on the unit's supply) is shown in the overview as "Forbrug". Home Assistant sends it on `/api/controller/signals` as `unit_power_w`, leased like the fireplace signal, so a stale value disappears on its own. Sending only the power leaves the fireplace signal untouched.
- Changes by Claude AI.

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
