# Experimental HCP4 replacement controller

Test scaffold for HCH5 with HCP4 physically disconnected.

## Safety
- Disabled by default.
- WebUI/HA request high-level intent; only the Pi controller translates intent to verified RS485 writes.
- `smart_auto` falls back locally when HA heartbeat expires.
- Persistent state is atomic.
- Known fan pairs only: L1 25/13, L2 55/43, L3 85/73, boost 100/88.
- Do not invent frost/defrost or afterheat writes. HCH5/HAC1 native regulation remains authoritative.

## Existing verified evidence must be reused
Do **not** reverse-engineer already-known HRC2/HCP4 behaviour again. Before implementing active control, inventory and cross-reference:

1. `MRDonnii/dantherm-hch-passivelink` current `tests/test_parser.py` and parser implementation.
2. Git history for the parser/mode/afterheat work, especially the commits that introduced or corrected observed HRC2/HCP4 sequences.
3. The deploy host's local checkout, including any untracked or not-yet-pushed `docs/captures/**`, `analysis.md`, JSONL/raw capture files and test scripts. Run `git status --untracked-files=all` and inventory `docs/captures` before changing code.
4. The installed monolithic Pi gateway, whose verified `write_pair()`, bypass and fireplace paths take precedence over guessed or reconstructed writes.

Concrete frames already preserved in the main repo tests include:
- L1 fan pair: reg66=25, reg67=13.
- L2 fan pair: reg66=55, reg67=43.
- L3 fan pair: reg66=85, reg67=73.
- command register 143 (`0x008f`) sequences used to distinguish manual/auto/night transitions, including observed values 172, 189 and 200.
- night transition: 143=172 followed by both fan registers; 25/13 represents night-on in the verified parser behaviour.
- HAC1 connected state observed on reg146 (`0x0092`) including value 3.
- HAC1 FC16 write blocks for optional room/extract thermostat states and supply-air afterheat setpoint.

The current parser explicitly says it decodes only values verified on the observed HCH5 MK1/HAC1 bus. Treat those mappings and regression tests as evidence, not hypotheses.

## Required deploy adaptation
Adapt this core to the actual monolithic Pi gateway. Reuse its hardware-verified `write_pair()`, bypass and fireplace functions. Do not replace those with guessed writes.

The raw capture archive may be richer on the local Codex checkout than on GitHub `main`; if found locally, use it as the primary source for exact HRC2 button-to-frame sequences and document which capture proves each active command.

## Acceptance
HCP4 disconnected; backups taken; read/TCP/HA stay healthy; L2 produces 55/43 and RPM response; WebUI exposes controller state; HA timeout falls back to L2; restart restores safe config; RS485 exceptions stop active writes and surface an error without aggressive retry.
