"""Tests for fail-closed diagnostics."""

import json

import pytest

from custom_components.mova_rover.models import MovaDevice, MovaProperty
from custom_components.mova_rover.redaction import (
    audit_serialized_diagnostics,
    fail_closed_diagnostics,
    safe_device,
    safe_property,
    safe_property_value,
)


def test_safe_property_only_preserves_reviewed_protocol_numbers() -> None:
    assert safe_property(MovaProperty(2, 1, 0, 4)) == {
        "siid": 2,
        "piid": 1,
        "code": 0,
        "value": 4,
    }
    assert safe_property(MovaProperty(7, 9, 0, 4))["value"] == {"kind": "integer"}
    assert safe_property_value([0, 1, 2, 255]) == {"kind": "array", "length": 4}


def test_safe_property_uses_bundle_local_hmac_for_unknown_values() -> None:
    correlation_key = b"a" * 32
    text = safe_property_value(
        "https://example.invalid/map?token=secret",
        correlation_key=correlation_key,
    )
    assert text["kind"] == "string"
    assert text["length"] == 40
    assert "example" not in json.dumps(text)
    assert text["fingerprint"].startswith("hmac-sha256:")

    large = safe_property_value(list(range(100)), correlation_key=correlation_key)
    assert large["kind"] == "array"
    assert large["length"] == 100
    assert len(large["fingerprint"].removeprefix("hmac-sha256:")) == 64


def test_unknown_fingerprints_correlate_only_inside_one_bundle() -> None:
    value = [10, 20, 30]
    first = safe_property_value(value, correlation_key=b"a" * 32)
    repeated = safe_property_value(value, correlation_key=b"a" * 32)
    another_bundle = safe_property_value(value, correlation_key=b"b" * 32)

    assert first["fingerprint"] == repeated["fingerprint"]
    assert first["fingerprint"] != another_bundle["fingerprint"]
    assert value not in first.values()


def test_safe_device_omits_name_and_cloud_identifier() -> None:
    device = MovaDevice(
        device_id="did-secret",
        model="mova.swbot.test",
        name="Private pool name",
        firmware="1.0",
    )
    safe = safe_device(device)
    serialized = json.dumps(safe)
    assert safe["alias"] == "device_1"
    assert "did-secret" not in serialized
    assert "Private pool name" not in serialized


def test_safe_device_redacts_identifier_shaped_vendor_metadata() -> None:
    device = MovaDevice(
        device_id="did-secret",
        model="123e4567-e89b-42d3-a456-426614174000",
        name="Rover",
        firmware="1.2.3.4",
        product_id="aa-bb-cc-dd-ee-ff",
    )

    safe = safe_device(device)

    assert safe["model"] == "redacted"
    assert safe["firmware"] == "redacted"
    assert safe["product_id"] == "redacted"


@pytest.mark.parametrize(
    "leaked",
    (
        "user@example.com",
        "aa:bb:cc:dd:ee:ff",
        "aa-bb-cc-dd-ee-ff",
        "192.168.10.20",
        "2001:db8:85a3::8a2e:370:7334",
        "123e4567-e89b-42d3-a456-426614174000",
        "Bearer abcdefghijklmnop",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnopqrstuvwxyz",
        "https://example.invalid/file?signature=abc",
        "https://example.invalid/file",
    ),
)
def test_audit_rejects_structurally_sensitive_values(leaked: str) -> None:
    with pytest.raises(ValueError):
        audit_serialized_diagnostics(json.dumps({"value": leaked}), ())


def test_audit_rejects_known_secrets_and_encoded_variants() -> None:
    with pytest.raises(ValueError):
        audit_serialized_diagnostics('{"value":"super-secret-token"}', ("super-secret-token",))
    with pytest.raises(ValueError):
        audit_serialized_diagnostics('{"value":"secret%40example.com"}', ("secret@example.com",))


def test_audit_accepts_sanitized_protocol_bundle() -> None:
    serialized = json.dumps(
        {
            "device": {"alias": "device_1", "model": "mova.swbot.g9999"},
            "property": {"siid": 2, "piid": 1, "value": 4},
            "sha256": "d" * 64,
        }
    )
    audit_serialized_diagnostics(serialized, ("real-password", "device-identifier"))


def test_diagnostics_fail_closed_when_reviewed_metadata_looks_sensitive() -> None:
    diagnostics = {"device": {"model": "user@example.com"}}
    fallback = {"redaction": {"status": "unsafe_fields_removed"}}

    assert fail_closed_diagnostics(diagnostics, (), fallback) == fallback


def test_diagnostics_keeps_safe_payload_after_audit() -> None:
    diagnostics = {"device": {"model": "mova.swbot.g9999"}}

    assert fail_closed_diagnostics(diagnostics, (), {}) is diagnostics
