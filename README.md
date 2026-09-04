# MOVA Rover for Home Assistant

![MOVA Rover integration logo](custom_components/mova_rover/brand/logo.png)

Experimental, read-only Home Assistant integration for MOVA robotic pool
cleaners, starting with protocol discovery for the **MOVA Rover X10**
(`PIXZ6111`). It is installable as a custom HACS repository.

> [!WARNING]
> This project is unofficial and cloud-based. It is not affiliated with or
> endorsed by MOVA, Dreame, Spacewalker Technology, or Wavefuture Robotics.
> MOVA can change its undocumented cloud API at any time.

## Current status

Version `0.1.0` is a safe discovery beta:

- MOVAhome login for the European cloud region
- owned and shared device selection
- verified HTTPS only
- 60-second read-only polling
- provisional status, battery, charging and cleaning entities based on the
  related Dreame Z1 pool robot protocol
- privacy-preserving Home Assistant diagnostics
- guided read-only Rover X10 property capture tool

There are deliberately **no** start, pause, steering, parking, firmware,
pairing, reset or account-management commands. MQTT is also excluded until its
vendor endpoint can be used with normal certificate and hostname verification.

## Installation through HACS

1. In HACS, open **Integrations**.
2. Add `https://github.com/goalin1980/ha-mova-rover` as a custom
   **Integration** repository.
3. Download **MOVA Rover** and restart Home Assistant.
4. Open **Settings → Devices & services → Add integration** and search for
   **MOVA Rover**.

Only the European MOVAhome region is verified in this first release. Prefer a
separate MOVAhome account to which the robot owner shared the Rover instead of
using the owner's primary account. The discovery beta requires Home Assistant
`2026.9.0` or newer; broader compatibility will follow after the first live
Rover capture.

## Entities

The initial generic pool-robot profile exposes:

- battery
- normalized status
- cloud connection
- charging
- cleaning
- raw status and last-seen diagnostics, disabled by default

The Z1-derived property meanings are hypotheses until Rover X10 captures
confirm them. An unknown value remains `unknown`; this integration does not
invent a state.

## Testing a Rover X10

Start with the normal HACS installation. If setup succeeds, download the
integration diagnostics from Home Assistant and attach them to the
[Rover X10 capture issue form](https://github.com/goalin1980/ha-mova-rover/issues/new?template=rover-x10-capture.yml).

For deeper protocol discovery, an IT-capable tester can run the guided probe.
It asks for credentials interactively, performs only device-list and
`get_properties` reads, sanitizes everything in memory, then writes one
leak-audited file:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r tools/requirements.txt
python tools/mova_probe.py guided --profile rover-x10-core
```

See [Rover X10 testing](docs/testing-rover-x10.md) before running a capture.

## Privacy and security

- Credentials and tokens are never included in diagnostics.
- Cloud device IDs are replaced by a stable local Home Assistant identifier.
- The standalone probe accepts no password flag or environment variable.
- Raw server responses, maps, schedules and MQTT topics are never written.
- Unknown property values are never written verbatim. They are reduced to
  type/length and a bundle-local HMAC fingerprint that changes on every run.
- Every probe run creates a new owner-only file; earlier captures are never
  overwritten.
- The probe never uploads anything automatically.

Please read [Security and privacy](docs/security-and-privacy.md) before sharing
diagnostics. To report a vulnerability, follow [SECURITY.md](SECURITY.md).

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.test.txt
ruff check .
ruff format --check .
pytest
```

HACS and hassfest validation run in GitHub Actions. Releases contain
`mova_rover.zip`, whose version must match the integration manifest and tag.

## License and protocol acknowledgements

The project is MIT licensed. The cloud behavior was independently
reimplemented from interoperable, MIT-licensed community projects. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
