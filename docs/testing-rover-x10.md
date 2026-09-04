# Rover X10 testing

Thank you for helping identify the MOVA Rover X10 protocol. The probe is
designed for an informed device owner and never sends a robot action.

## Before testing

- Obtain the owner's explicit permission.
- Keep people and animals out of the pool.
- Use a separate MOVAhome account and share only the Rover to it when possible.
- Confirm the robot can be retrieved manually if networking fails.
- Do not deliberately provoke errors, deep discharge, blocked pumps or
  emergency conditions.

The probe supports only the verified European MOVAhome region in version
`0.1.0`.

## Install the probe

Clone this repository on a trusted computer, then create a temporary Python
environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r tools/requirements.txt
```

No password can be passed on the command line, in an environment variable or
in a configuration file. The tool asks for it through a hidden interactive
prompt and retains it only in memory.

## Capture profiles

Run the core flow first:

```bash
python tools/mova_probe.py guided --profile rover-x10-core
```

The owner follows each prompt in MOVAhome. For every transition, the probe
first records the explicitly described baseline. It then asks the owner to
perform the app action and takes two post-state snapshots five seconds apart
once the app reports the requested state. The idle and charging states are
separate steps. `s` skips a step and `q` finishes early.

Return the Rover to the baseline stated by each mode step before continuing.
This avoids confusing a direct mode switch with a start from idle. The probe
never performs the app action itself.

Optional follow-up flows:

```bash
python tools/mova_probe.py guided --profile rover-x10-modes
python tools/mova_probe.py guided --profile rover-x10-completion
```

The completion flow intentionally waits for a natural cleaning completion.
Do not simulate a low battery or fault.

## Share only the sanitized result

Every run creates one new output file. Existing captures are never replaced:

```text
probe-output/mova-rover-<profile>-<timestamp>-<random>.json
```

The directory is owner-only (`0700`) and the file is owner-readable only
(`0600`). Inspect it before sharing. It should contain aliases such as
`device_1`, model/firmware information, numeric property identifiers and
sanitized values. Unknown property values are never included verbatim. Their
type and length, plus a bundle-local HMAC fingerprint where useful, allow
changes within one capture to be correlated without creating a stable hash
across captures. It must not contain email addresses, passwords, access tokens,
device IDs, serial numbers, MAC/IP addresses, URLs, maps or schedules.

Attach the file to the Rover X10 capture issue form. There is no automatic
upload.
