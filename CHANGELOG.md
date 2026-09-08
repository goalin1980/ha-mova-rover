# Changelog

## [0.1.1] - 2026-09-08

- Interpret raw status `2` on the verified Rover X10 model as the conservative
  `docked` state instead of claiming that charging has completed.
- Leave the X10 charging binary sensor unknown while docked because correlated
  captures show the same raw status during active charging and after completion.
- Add a bounded, privacy-reviewed diagnostic observation for heartbeat byte 9
  without exposing the full heartbeat array.
- Add regression tests and record the correlated charging, charged and undocked
  device observations.

## [0.1.0] - 2026-09-04

- Initial HACS discovery beta.
- Add European MOVAhome login and shared-device selection.
- Add verified-HTTPS, REST-only polling for the related pool-robot baseline.
- Add privacy-preserving Home Assistant diagnostics.
- Add original local Home Assistant icon and logo assets in standard and HiDPI
  sizes.
- Add guided, fail-closed Rover X10 property capture tooling with explicit
  before/after markers, bundle-local fingerprints and non-overwriting output.
