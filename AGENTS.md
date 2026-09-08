# Project working rules

## Scope and evidence

- Keep the integration read-only unless the device owner explicitly approves a separately
  reviewed command change. Do not add start, stop, steering, firmware, pairing, reset, account,
  or other physical-device actions as part of protocol discovery.
- Separate live X10/AquaSonar observations, behavior inherited from related devices, and open
  hypotheses. Never assign a property meaning, unit, or scale without correlated evidence.
- Preserve the existing brand assets and Home Assistant behavior unless a change is intentional
  and regression-tested.

## Security and privacy

- Follow `SECURITY.md` and `docs/security-and-privacy.md` before handling diagnostics.
- Never place credentials, password hashes, tokens, cloud device IDs, serial/MAC/IP addresses,
  signed URLs, maps, raw account responses, or unredacted captures in logs, chat, fixtures,
  commits, issues, or pull requests.
- Keep TLS verification, the fixed-host/read-only request allowlists, response-size limits, and
  fail-closed redaction intact. New diagnostic values require a narrow allowlist and leak-audit
  tests.
- Device tests must state the initial state, owner action, wait time, and exact sanitized data
  needed. No automated physical test or command without explicit owner consent.

## Development

- Work on a feature branch; coordinate before push, pull request, or release.
- Use Python 3.12+ and install the lightweight checks with
  `python -m pip install -r requirements.test.txt`.
- Before handoff, run `ruff check .`, `ruff format --check .`, `pytest`,
  `python -m compileall -q custom_components tools tests`, and
  `python .github/scripts/check_version.py`.
- The Home Assistant smoke test needs the separate dependencies in
  `requirements.ha-test.txt`. A skip caused solely by an unavailable `homeassistant` package is
  not a passing runtime test; report it explicitly.
- Add regression tests for every confirmed mapping or behavior change. Document substantial
  protocol findings learned from another implementation and preserve applicable license notices.

