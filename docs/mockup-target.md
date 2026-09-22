# WebUI professional dashboard target

This branch implements the approved dark HCH5 Control dashboard direction.

Key physical rules:
- Outdoor-air filter is on the outdoor-air intake path before the heat exchanger.
- Extract-air filter is on the extract/room-air path before the heat exchanger.
- Afterheat is a hydronic coil on the supply-air path after the heat exchanger.
- The UI changes only the afterheat supply-air setpoint; it never presents or issues a direct actuator-position command.
- Bypass requested mode and physical bypass state remain distinct.

Visual target:
- Professional dark/navy application shell.
- Detailed HCH5 cabinet SVG with internal exchanger, fans, filters, bypass and afterheat coil.
- Live animated air paths and fan speed driven from readback data.
- Compact right-side daily controls.
- Indoor-climate cards and software-update progress card below.
- Real update progress/state rather than an indeterminate spinner.
