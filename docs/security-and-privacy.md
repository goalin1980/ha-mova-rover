# Security and privacy

## Cloud access

This integration connects to the fixed European MOVAhome host using the
operating system trust store. Redirects are rejected and TLS certificate
verification cannot be disabled. The public API surface contains only login,
device listing, device information and `get_properties` reads.

The password-derived value used by the undocumented MOVAhome protocol is
replay-sensitive. Use a dedicated shared account, a unique password and remove
the device share when testing is finished.

## Stored data

Home Assistant stores the MOVAhome email and password in its config-entry
storage, like other password-based integrations. Protect Home Assistant's
configuration directory and backups accordingly.

The integration does not persist raw cloud responses. Home Assistant
diagnostics use a positive allowlist and omit account details, cloud device
identifiers, network identifiers, map data and free-form property values. Only
the explicitly reviewed numeric status and battery properties may appear as
raw diagnostic values; every unknown property is summarized.

## Probe output

The standalone probe keeps raw responses in memory only. Before the sanitized
bundle is written it performs a second leak audit for known secrets, emails,
MAC/IP addresses, UUIDs, bearer tokens and signed URLs. If that audit fails, no
file is written. Unknown values use a random HMAC key that exists only for one
run, so equal values can be correlated inside that bundle but cannot be tracked
across captures. Each run uses a new filename and never overwrites an earlier
capture.

Even sanitized diagnostics should be reviewed by the tester before they are
attached to a public issue.
