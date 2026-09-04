"""Fail-safe diagnostic value handling for MOVA Rover."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from hashlib import sha256
from hmac import new as new_hmac
from ipaddress import ip_address
from typing import Any
from urllib.parse import quote, quote_plus

from .models import MovaDevice, MovaProperty

_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_MAC = re.compile(r"(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_UUID = re.compile(
    r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_URL = re.compile(r"(?i)https?://[^\s\"']+")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_IP_CANDIDATE = re.compile(r"(?i)(?<![0-9a-f:.])[0-9a-f:.]{3,}(?![0-9a-f:.])")
_HYPHENATED_MAC = re.compile(r"(?i)\b(?:[0-9a-f]{2}-){5}[0-9a-f]{2}\b")

# These two scalar properties are the only values already understood from the
# related Dreame Z1 protocol. Everything else is discovery data and must never
# be emitted verbatim.
_PUBLIC_INTEGER_RANGES: dict[tuple[int, int], tuple[int, int]] = {
    (2, 1): (0, 255),  # operational status
    (3, 1): (0, 100),  # battery percentage
}

_MAX_FINGERPRINT_DEPTH = 6
_MAX_FINGERPRINT_ITEMS = 64
_MAX_FINGERPRINT_TEXT_BYTES = 4096
_MAX_METADATA_LENGTH = 160
_SAFE_METADATA = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._+:/ -]*\Z")


def _contains_sensitive_shape(value: str) -> bool:
    """Recognize common identifiers, credentials and network addresses."""

    checks = (_EMAIL, _MAC, _HYPHENATED_MAC, _IPV4, _UUID, _BEARER, _JWT, _URL)
    if any(pattern.search(value) for pattern in checks):
        return True
    for candidate in _IP_CANDIDATE.findall(value):
        if ":" not in candidate:
            continue
        try:
            ip_address(candidate)
        except ValueError:
            continue
        return True
    return False


def _bounded_fingerprint_material(value: Any, *, depth: int = 0) -> bytes:
    """Return bounded correlation material without retaining a raw payload."""

    if depth >= _MAX_FINGERPRINT_DEPTH:
        return f"depth:{type(value).__name__}".encode()
    if value is None:
        return b"null"
    if isinstance(value, bool):
        return b"bool:1" if value else b"bool:0"
    if isinstance(value, (int, float)):
        return f"number:{value!r}".encode()
    if isinstance(value, str):
        encoded = value.encode("utf-8", errors="replace")
        return b"str:" + str(len(encoded)).encode() + b":" + encoded[:_MAX_FINGERPRINT_TEXT_BYTES]
    if isinstance(value, (bytes, bytearray)):
        encoded = bytes(value)
        return b"bytes:" + str(len(encoded)).encode() + b":" + encoded[:_MAX_FINGERPRINT_TEXT_BYTES]
    if isinstance(value, Mapping):
        chunks = [f"object:{len(value)}".encode()]
        for index, (key, item) in enumerate(value.items()):
            if index >= _MAX_FINGERPRINT_ITEMS:
                break
            chunks.append(_bounded_fingerprint_material(str(key), depth=depth + 1))
            chunks.append(_bounded_fingerprint_material(item, depth=depth + 1))
        return b"|".join(chunks)
    if isinstance(value, Sequence):
        chunks = [f"array:{len(value)}".encode()]
        for item in value[:_MAX_FINGERPRINT_ITEMS]:
            chunks.append(_bounded_fingerprint_material(item, depth=depth + 1))
        return b"|".join(chunks)
    return f"other:{type(value).__name__}".encode()


def _fingerprint(value: Any, correlation_key: bytes | None) -> str | None:
    """Return a bundle-local fingerprint, never a globally stable raw hash."""

    if not correlation_key:
        return None
    return new_hmac(
        correlation_key,
        _bounded_fingerprint_material(value),
        sha256,
    ).hexdigest()


def _summary(
    kind: str,
    value: Any,
    correlation_key: bytes | None,
    *,
    length: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"kind": kind}
    if length is not None:
        result["length"] = length
    fingerprint = _fingerprint(value, correlation_key)
    if fingerprint is not None:
        result["fingerprint"] = f"hmac-sha256:{fingerprint}"
    return result


def safe_property_value(value: Any, *, correlation_key: bytes | None = None) -> dict[str, Any]:
    """Summarize an unknown value without ever returning it verbatim."""

    if value is None:
        return _summary("null", value, correlation_key)
    if isinstance(value, bool):
        return _summary("boolean", value, correlation_key)
    if isinstance(value, int):
        return _summary("integer", value, correlation_key)
    if isinstance(value, float):
        return _summary("number", value, correlation_key)

    if isinstance(value, (bytes, bytearray)):
        return _summary("bytes", value, correlation_key, length=len(value))

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return _summary("array", value, correlation_key, length=len(value))

    if isinstance(value, str):
        return _summary("string", value, correlation_key, length=len(value))

    if isinstance(value, Mapping):
        return _summary("object", value, correlation_key, length=len(value))

    return _summary(type(value).__name__, value, correlation_key)


def safe_property(
    property_value: MovaProperty,
    *,
    correlation_key: bytes | None = None,
) -> dict[str, Any]:
    """Convert a property result to the only allowed diagnostics shape."""

    value: Any
    value_range = _PUBLIC_INTEGER_RANGES.get((property_value.siid, property_value.piid))
    if (
        value_range is not None
        and isinstance(property_value.value, int)
        and not isinstance(property_value.value, bool)
        and value_range[0] <= property_value.value <= value_range[1]
    ):
        value = property_value.value
    else:
        value = safe_property_value(
            property_value.value,
            correlation_key=correlation_key,
        )

    return {
        "siid": property_value.siid,
        "piid": property_value.piid,
        "code": property_value.code,
        "value": value,
    }


def _safe_metadata(value: str | None) -> str | None:
    """Keep short vendor identifiers while rejecting free-form/untrusted text."""

    if value is None:
        return None
    if not 1 <= len(value) <= _MAX_METADATA_LENGTH:
        return "redacted"
    if not _SAFE_METADATA.fullmatch(value):
        return "redacted"
    if _contains_sensitive_shape(value):
        return "redacted"
    return value


def safe_device(device: MovaDevice, *, alias: str = "device_1") -> dict[str, Any]:
    """Expose only explicitly reviewed non-secret device metadata."""

    return {
        "alias": alias,
        "model": _safe_metadata(device.model) or "unknown",
        "product_id": _safe_metadata(device.product_id),
        "firmware": _safe_metadata(device.firmware),
        "category": _safe_metadata(device.category),
        "online": device.online,
        "shared": device.shared,
    }


def audit_serialized_diagnostics(serialized: str, secrets: Sequence[str]) -> None:
    """Fail closed if a known or structurally likely secret remains."""

    candidates: set[str] = set()
    for secret in secrets:
        if not isinstance(secret, str) or len(secret) < 6:
            continue
        json_escaped = json.dumps(secret, ensure_ascii=True)[1:-1]
        candidates.update({secret, json_escaped, quote(secret, safe=""), quote_plus(secret)})
    if any(candidate and candidate in serialized for candidate in candidates):
        raise ValueError("Known secret remained in diagnostics")

    if _contains_sensitive_shape(serialized):
        raise ValueError("Potential personal or authentication data remained in diagnostics")


def fail_closed_diagnostics(
    diagnostics: dict[str, Any],
    secrets: Sequence[str],
    fallback: dict[str, Any],
) -> dict[str, Any]:
    """Return diagnostics only after a leak audit, otherwise a minimal fallback."""

    try:
        serialized = json.dumps(
            diagnostics,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        audit_serialized_diagnostics(serialized, secrets)
    except (TypeError, ValueError):
        return fallback
    return diagnostics
