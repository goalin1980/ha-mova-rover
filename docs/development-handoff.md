# Development handoff

Verified on 2026-09-07. This document records a point-in-time baseline; newer repository or live
device evidence takes precedence.

## Repository and tooling baseline

- Public repository: `goalin1980/ha-mova-rover`.
- `origin/main`, local clone baseline, and annotated tag `v0.1.0` all resolve to peeled commit
  `024725a1a48aa094fb6ae4023f4bddc78643895b` (`Fix CI metadata warnings`).
- The verified changes were squash-merged through PR #1 as commit `dd1a209` on `main`.
  Release `v0.1.1` is being prepared separately on `codex/release-v0.1.1` and is not published
  yet.
- GitHub reports no open issues. The latest Validate and Release runs for `024725a` completed
  successfully, and release `v0.1.0` contains `mova_rover.zip`.
- Lightweight environment: `.venv`, Python 3.12.14. Installed from `requirements.test.txt`.
- Local checks: Ruff lint passed; Ruff format check passed (26 files); 47 tests passed; compileall
  passed; integration/manifest version check passed (`0.1.0`).
- `tests/test_ha_smoke.py` was skipped in `.venv` because Home Assistant is intentionally absent.
  A separate `.venv-ha` installation was attempted, but the configured package index did not
  offer `homeassistant==2026.9.0`; therefore no local HA runtime result is claimed. The public
  GitHub Validate run did execute its separate HA runtime job successfully.

## Confirmed live-device facts

- Rover X10 cloud model: `mova.swbot.g2526`; product ID: `11178`; firmware: `4.3.6_0058`.
- Cloud discovery and periodic read-only status access worked on the physical Rover under Home
  Assistant 2026.9.1 / HA OS.
- During one confirmed active charge at 52%, Home Assistant simultaneously showed Charging = on
  and Status = `charged`. The normalized status was wrong in that observation.
- A fresh correlated diagnostic captured on 2026-09-07 at 08:58:47 UTC while the owner confirmed
  active dock charging (app battery 15%) returned HTTP 200, cloud code `0`, `online = true`,
  property `2:1 = 2`, and property `3:1 = 14`. The one-point battery difference is consistent with
  the app observation occurring just after the poll. This directly disproves the inherited X10
  interpretation that `2` means only `charged`. Heartbeat `1:1` was an array of length 20 but its
  value was intentionally not exposed by standard diagnostics.
- A second successful correlated diagnostic captured on 2026-09-07 at 14:59:17 UTC after the app
  reported that charging had ended returned battery 100%, `online = true`, cloud code `0`, and
  property `2:1 = 2` again. Thus `2:1` alone does not distinguish active charging from charge
  complete in these two X10 observations. Do not derive charge completion from battery percentage
  alone; another narrowly reviewed signal (potentially within heartbeat `1:1`) is required if the
  vendor exposes that distinction.
- A third successful diagnostic captured on 2026-09-07 at 15:06:36 UTC after the owner manually
  removed the fully charged Rover from the dock and left it idle returned battery 100%, cloud code
  `0`, `online = true`, and property `2:1 = 0`. Together the three captures confirm `0 = idle` for
  the observed undocked state and `2 = docked`, while `2` does not reveal the charge phase.
- The merged implementation maps `2` to model-specific status `docked` for
  `mova.swbot.g2526` and leaves the charging binary value unknown in that state. It also adds a
  bounded diagnostic field for heartbeat byte 9 only. These changes are covered by decoder,
  bounds, and redaction regression tests but are not part of a published release yet.
- A different, later diagnostic showed battery 67%, property `2:1 = 0`, normalized `idle`,
  `state.online = false`, cloud code `80001`, and an older `last_seen`. It does not capture the
  charging observation. The coordinator treats `80001` as device-offline and retains the prior
  measurements while marking the state offline.
- AquaSonar is a separately paired/account-linked unit and supplies water temperature in the
  MOVAhome app. No cloud descriptor or temperature property has yet been captured.

## Inherited assumptions, not X10/AquaSonar facts

- `profiles.py` currently applies the related Dreame Z1 mapping for property `2:1`:
  `0 idle`, `1 charging`, `2 charged`, `3 updating`, `4 cleaning`.
- Property `3:1` is treated as battery percentage. Heartbeat property `1:1`, byte index 9, is a
  provisional battery/charge-bit fallback.
- Both normalized statuses `charging` and `charged` force the charging binary sensor on. Those two
  UI entities are consequently not independent evidence.
- `rover_candidates()` prefers descriptors containing `pixz6111`, `pool`, `rover`, or `swbot` and
  returns all devices only when none match. If the Rover matches but AquaSonar does not, AquaSonar
  can disappear from the Home Assistant selection even though the account API returned it.
- The standalone probe lists every returned device, but its guided property profiles are designed
  for the Rover and must not be run against AquaSonar without review.

## Open questions

1. Does heartbeat `1:1` contain a privacy-safe, repeatable signal that distinguishes active
   charging from charge complete while `2:1` remains `2`? Its value remains hidden by standard
   diagnostics.
2. Does AquaSonar appear as its own record in `device/listV2`? What are its sanitized model,
   product ID, firmware, category, online/shared flags, and display role?
3. Which AquaSonar read-only field/property correlates with the app water temperature, with what
   unit, scale, refresh cadence, and offline behavior?
4. Is a narrow, bundle-local diagnostic mode needed for candidate AquaSonar numeric values? The
   standard export intentionally hides unknown raw values and cannot establish a scale by itself.

## Next targeted tests

### 1. Rover heartbeat charge-phase capture (first priority)

- Initial state: one capture below 100% while visibly charging and one capture at 100% after the app
  says charging has ended, both on the dock.
- Action: first add and review a narrowly scoped diagnostic that exposes only selected bounded
  numeric heartbeat fields; do not expose the full array and do not issue a device command.
- Wait: at least one fresh 60-second poll in each state.
- Capture at the same time: MOVAhome charging/status screenshot or written observation plus a new
  sanitized Home Assistant diagnostic.
- Needed fields: timestamp, app-reported state and battery, diagnostic `last_cloud_code`,
  `last_update_success`, state (`raw_status`, `status`, `battery`, `charging`, `online`, `last_seen`),
  and sanitized baseline properties `1:1`, `2:1`, `3:1`.
- Reject as inconclusive if cloud code is `80001`, online is false, or `last_seen` predates the
  observed app state. Do not swap status values from this single observation.
- Needed data: the selected heartbeat byte(s), raw `2:1`, battery `3:1`, app charge phase, cloud
  code, online state, and `last_seen`. Add leak-audit and regression tests before distributing the
  diagnostic build.

### 2. AquaSonar discovery (after the charging capture)

- Initial state: AquaSonar paired and visible in MOVAhome; no device actions.
- Action: run only the probe's device-list/selection stage (or add a reviewed list-only mode), and
  do not apply Rover property profiles to AquaSonar.
- Wait: only for login and the device-list response.
- Needed data: sanitized descriptor for every listed device so the AquaSonar record can be
  distinguished without exposing cloud IDs or names. Record the simultaneous temperature shown
  by the app separately for later correlation.
- Only after identifying its descriptor should a small, read-only, privacy-reviewed candidate
  property capture be designed.
