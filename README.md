# HCH5 Control

**Modern local ventilation control for Dantherm HCH5 MK1 / HAC1.**

HCH5 Control turns a Raspberry Pi and a USB-RS485 adapter into a local controller, WebUI and Home Assistant bridge for older HCH5 installations. It keeps the proven PassiveLink decoder for compatibility, but the product is no longer a passive-only project: the Pi can take over as Modbus master, run local automation and issue only the RS485 writes that have been physically verified on the reference installation.

> **Unofficial community project.** HCH5 Control is not developed, approved, certified or supported by Dantherm Group. Installation changes the control path of the ventilation system and is performed entirely at your own risk. Keep the original controller available so the installation can be returned to its original configuration.

## What is included

- Local HCH5 controller with automatic HCP4 master arbitration and fail-safe write blocking.
- Responsive WebUI with live temperatures, fans, bypass, after-heater, diagnostics and history.
- Animated airflow diagram: normal heat recovery uses the crossed exchanger routes; physical bypass readback switches the diagram to the straight-through routes.
- Local Auto and Smart Auto with six adjustable fan profiles.
- Adjustable weekly schedule, night reduction and holiday mode.
- Free-cooling automation using indoor/outdoor temperature, hysteresis and minimum temperature difference.
- Manual bypass request plus separate physical bypass feedback.
- Fireplace mode and after-heater setpoint support from the verified controller layer.
- Home Assistant API plus raw TCP mirror on port `4196`.
- Stable/Beta update channels in the WebUI. Beta is opt-in.
- First-user login, CSRF protection, system diagnostics and safe backups before updates.

## Important: original HCP4 controller

For **normal active HCH5 Control operation**, disconnect the original HCP4 controller from the RS485 control path so the Raspberry Pi can become the active master.

The arbitration layer is still intentionally fail-safe: if an HCP4 is connected again and verified foreign control writes are observed, the Pi immediately stops transmitting and yields mastership. In `UNKNOWN`, unhealthy-bus or HCP4-master state, controller writes are blocked.

Do not connect two independent masters and assume they can control the unit at the same time.

## Hardware

Reference setup:

- Dantherm HCH5 MK1 with HAC1;
- Raspberry Pi 2B or newer;
- Linux-supported USB-RS485 adapter;
- RS485: `19200 8E1`;
- optional DS18B20 sensors for water temperatures.

Turn off the ventilation unit and adapter before changing RS485 wiring. Use a stable `/dev/serial/by-id/...` device path and do not add termination blindly.

## Install the current beta

Find the adapter first:

```bash
ls -l /dev/serial/by-id/
```

Then install:

```bash
curl -fsSL https://raw.githubusercontent.com/MRDonnii/dantherm-hch-passivelink-webui/beta/1.1-modern-controller/install-hch5-control.sh \
  | sudo bash -s -- \
      --device /dev/serial/by-id/usb-YOUR_ADAPTER \
      --enable-onewire
```

Omit `--enable-onewire` if DS18B20 sensors are not used.

The installer preserves existing controller state, WebUI login, tokens and YAML configuration when upgrading an existing installation. Backups are written before program files are replaced.

After installation open:

```text
http://RASPBERRY-PI-IP:8080/
```

There is no default password. The first browser session creates the owner account.

## Updating from the WebUI

Open **Opdateringer**.

- **Stable** is the default channel.
- Enable **Brug beta-kanal** only when you want prerelease functionality.
- **Søg efter opdatering** compares the installed version with the selected channel.
- **Installer opdatering** downloads a fixed repository ref, backs up application code, replaces only program files and restarts the required services.

Persistent configuration under `/etc/dantherm-passivelink-webui/` and controller state under `/var/lib/dantherm-hch5-ha/` are not reset by the in-place updater.

## Modern automation

The Raspberry Pi is the source of truth for controller settings.

### Weekly schedule

Weekday/weekend start/end times and ventilation level are adjustable in the WebUI. Schedule is an automation layer on top of Local/Smart Auto rather than a separate Modbus implementation.

### Night reduction

Night start/end and target fan level are adjustable. Normal air-quality demand can override the reduced level when CO₂/RH becomes elevated.

### Holiday mode

Holiday mode forces the selected low ventilation level and pauses automatic free cooling until holiday mode is disabled.

### Free cooling

Free cooling can be enabled with adjustable:

- indoor target temperature;
- minimum outdoor temperature;
- minimum indoor/outdoor temperature difference;
- minimum ventilation level;
- hysteresis.

When conditions are useful for cooling, the controller requests bypass and raises ventilation to at least the configured cooling level. The requested bypass state and the **physical** bypass state remain separate. A slow damper actuator is therefore not treated as an immediate failure.

## Bypass

The verified request binding used by this beta is:

```text
Slave:    0x01
Function: FC06
Register: 0x0044 / 68
AUTO:     0x0000
ON:       0x00FF
```

The physical bypass readback is separate and is what drives the WebUI airflow diagram. `AUTO` can legitimately coexist with a physically open bypass when the HCH5's own conditions call for it.

## Home Assistant

Use the companion repository:

`MRDonnii/dantherm-hch-passivelink`

The classic raw data connection remains compatible on TCP port `4196`. Controller commands and Smart Auto room data go through the authenticated HTTP controller API; Home Assistant does not write Modbus directly.

## Safety model

1. HCP4 has priority whenever foreign control writes are observed.
2. `UNKNOWN` or unhealthy bus state means **zero Pi control writes**.
3. Only the central controller hardware boundary may transmit verified control frames.
4. No unverified T3/T5 write sequence is enabled.
5. Fireplace mode prevents automatic bypass request.
6. Existing configuration is preserved during updates and rollback backups are created.

This software cannot make an altered HVAC installation risk-free. Check frost protection, after-heater behaviour, airflow and physical bypass operation on the actual installation after changes. If behaviour is unexpected, disconnect the Pi controller and restore the original HCP4 setup.

## Development

```bash
python3 -m py_compile gateway/*.py
pytest -q
node --check gateway/webui/dashboard.js
node --check gateway/webui/smartcontrol.js
bash -n install.sh install-hch5-control.sh update.sh uninstall.sh
```

## License

MIT — see [LICENSE](LICENSE).
