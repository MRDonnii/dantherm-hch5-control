# HCH5 Control WebUI rebuild v2

Status: active development on `work/webui-rebuild-v2`.

## Goal

Rebuild the HCH5 Control WebUI as one coherent, professional local control application without changing verified HCH5/HAC1 protocol semantics or weakening master arbitration.

The rebuild must remove the current layering of legacy dashboard code, `prepaint.js`, injected modern controls, emergency navigation patches and separate Technique navigation behavior. The finished application must have one shell, one router, one state model and one navigation implementation.

## Product principles

- Local-first and usable with no cloud dependency.
- HCP4 always wins. UI must never bypass controller/master safety gates.
- UI failures must not stop RS485, raw TCP, auth or controller runtime.
- History is optional/degraded functionality and must never take the controller down.
- Persistent auth/controller/filter/update-channel state survives updates.
- No hidden duplicate event handlers for the same action.
- Stable entity/API contracts remain compatible unless explicitly migrated.
- Professional light UI by default with full dark mode.
- Responsive desktop/tablet/mobile layout.
- No Dantherm official branding/logo; HCH5 Control owns its visual identity.

## Target architecture

### 1. Single application shell

`index.html` becomes the single shell for all normal pages:

- Overview
- History
- Technique
- System
- Home Assistant
- Diagnostics
- Updates
- Settings

Technique is no longer a special full-page navigation or iframe. It renders as a normal application view.

### 2. One router

Create one small router module that owns:

- sidebar navigation
- active page state
- deep links (`?tab=` initially; optional hash/history migration later)
- browser back/forward
- focus/ARIA page state
- default page = Overview

There must be exactly one navigation click handler.

Navigation must continue to work if live data polling fails.

### 3. One state layer

Separate live state into explicit stores:

- gateway/live measurements
- controller state
- auth/session state
- admin/update state
- history availability

Rendering reads from these stores; API functions update them. UI components do not directly create competing polling loops.

### 4. Resilient API client

Central request helper with:

- timeout
- JSON validation
- 401 handling
- CSRF handling
- bounded retry for read-only polling
- clear unavailable/degraded states

A failure in one endpoint must not break navigation or unrelated pages.

### 5. Modular UI

Split the current monolithic frontend into focused modules, for example:

- `app.js`
- `router.js`
- `api.js`
- `state.js`
- `render-overview.js`
- `render-history.js`
- `render-technique.js`
- `render-system.js`
- `render-homeassistant.js`
- `render-diagnostics.js`
- `render-updates.js`
- `render-settings.js`
- `controls.js`
- `theme.js`

Use vanilla browser JavaScript unless a framework provides a clear reliability benefit. No runtime dependency on Node/npm on the Raspberry Pi.

### 6. Design system

Create one design token layer for:

- spacing
- typography
- radii
- shadows
- borders
- status colours
- light/dark surfaces
- controls

Visual direction:

- light professional main canvas
- dark/navy sidebar
- restrained green primary accent
- blue informational state
- orange warning
- red fault
- strong information hierarchy
- compact technical density without looking industrial/legacy

Sidebar supports expanded and icon-only collapsed states.

### 7. Overview layout

Primary dashboard should contain:

- system/master status strip
- large animated ventilation/heat-exchanger diagram
- actual physical bypass routing (not a fake extra pipe)
- temperatures at correct air positions
- supply/extract RPM and percentages
- CO2/RH status
- afterheat state/setpoint
- filter status
- current control mode and effective reason
- quick controls (Local Auto / Smart Auto / Manual, level, bypass request, fireplace, Quick Boost)
- intelligent automation summary

Bypass request and physical bypass must always be shown separately.

### 8. Technique page

Technique becomes a normal shell page containing:

- active master
- hardware writes allowed
- arbitration reason
- bus freshness
- controller health
- sensor freshness
- effective source/reason
- decision log
- verified readbacks
- Modbus/sniffer link/tooling

No page reload is required to enter/leave Technique.

### 9. History

History must be isolated from the runtime:

- unavailable SQLite => UI shows `Historik utilgængelig`
- no unhandled exception
- no restart loop
- controller stays active
- API can return empty/degraded result

### 10. Auth and persistent state

Auth path is explicit and tested.

Updater/install must preserve:

- `webui-auth.json`
- `webui-sessions.json`
- controller state
- filter state
- update channel

No install/update may silently reset login.

### 11. Update/runtime safety

Before restart updater validates:

- Python compile/imports
- controller config
- environment
- serial by-id path
- state directory writable
- auth readable/writable when configured
- temporary SQLite write or degraded-history capability
- frontend JS syntax in CI
- required assets exist
- legacy gateway service not active

After restart updater validates:

- MainPID stable
- port 8080 owner = MainPID
- port 4196 owner = MainPID
- auth endpoint responds
- controller API responds
- raw TCP accepts connection
- RS485 remains healthy
- no restart loop
- history healthy or explicitly degraded

Rollback restores last-known-good application/service files without re-enabling legacy services.

## Test gates

### Unit/static

- Python compile/import smoke
- pytest
- JavaScript syntax checks for every frontend module
- HTML required element check
- duplicate DOM id check
- router target/page consistency check

### Browser smoke tests

Add automated browser tests for:

1. login/setup page renders
2. every sidebar item changes page
3. Technique changes page without full reload
4. browser back/forward does not strand the UI
5. navigation works while `/state.json` fails
6. history failure does not break navigation
7. theme persists
8. collapsed sidebar persists
9. controller POST failure displays an error without breaking the app
10. mobile navigation is usable

### Deployment gate

No beta promotion until:

- CI green
- isolated local runtime smoke passes
- update/rollback smoke passes
- navigation test passes
- persistent auth/state survives test update

## Migration strategy

1. Build v2 entirely on `work/webui-rebuild-v2`.
2. Keep current beta untouched while rebuilding.
3. Reuse backend APIs and verified controller semantics.
4. Remove legacy frontend layers only on the rebuild branch.
5. Validate with browser/static/runtime tests.
6. Deploy to Pi only as an explicit test build after backup/rollback path is confirmed.
7. Promote to beta only after live validation.

## Non-goals

- No new unverified Modbus writes.
- No native filter register assumptions until filter research proves them.
- No changes to HCP4 priority/master arbitration semantics.
- No forced redesign of Home Assistant entity identities.
