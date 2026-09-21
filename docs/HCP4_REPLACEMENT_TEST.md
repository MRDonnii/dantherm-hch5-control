# Experimental HCP4 replacement controller
Test scaffold for HCH5 with HCP4 physically disconnected.

## Safety
- Disabled by default.
- WebUI/HA request high-level intent; only the Pi controller translates intent to verified RS485 writes.
- smart_auto falls back locally when HA heartbeat expires.
- Persistent state is atomic.
- Known fan pairs only: L1 25/13, L2 55/43, L3 85/73, boost 100/88.
- Do not invent frost/defrost or afterheat writes. HCH5/HAC1 native regulation remains authoritative.

## Required deploy adaptation
Adapt this core to the actual monolithic Pi gateway. Reuse its hardware-verified write_pair(), bypass and fireplace functions. Do not replace those with guessed writes.

## Acceptance
HCP4 disconnected; backups taken; read/TCP/HA stay healthy; L2 produces 55/43 and RPM response; WebUI exposes controller state; HA timeout falls back to L2; restart restores safe config; RS485 exceptions stop active writes and surface an error without aggressive retry.
