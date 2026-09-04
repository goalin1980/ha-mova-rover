"""Data models shared by the MOVA Rover integration and diagnostic tooling."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from typing import Any


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)):
            return str(value)
    return None


def stable_device_key(region: str, device_id: str) -> str:
    """Return a stable, non-reversible Home Assistant device key."""

    return sha256(f"{region}:{device_id}".encode()).hexdigest()[:20]


@dataclass(frozen=True)
class MovaDevice:
    """Cloud device metadata needed by the integration."""

    device_id: str
    model: str
    name: str
    product_id: str | None = None
    firmware: str | None = None
    category: str | None = None
    online: bool | None = None
    shared: bool | None = None

    @classmethod
    def from_cloud(cls, raw: Mapping[str, Any]) -> MovaDevice:
        """Create a descriptor without retaining the raw cloud response."""

        device_info = raw.get("deviceInfo")
        if not isinstance(device_info, Mapping):
            device_info = {}

        device_id = _first_text(raw.get("did"), raw.get("deviceId"), raw.get("id"))
        if device_id is None:
            raise ValueError("Cloud device has no device identifier")

        model = _first_text(raw.get("model"), device_info.get("model")) or "unknown"
        name = (
            _first_text(
                raw.get("customName"),
                raw.get("deviceName"),
                device_info.get("displayName"),
                model,
            )
            or "MOVA Rover"
        )
        product_id = _first_text(raw.get("productId"), device_info.get("productId"))
        firmware = _first_text(
            raw.get("ver"),
            raw.get("firmwareVersion"),
            raw.get("firmware"),
            device_info.get("firmwareVersion"),
        )
        category = _first_text(
            raw.get("categoryPath"),
            raw.get("category"),
            device_info.get("categoryPath"),
            device_info.get("category"),
        )

        online_value = raw.get("online")
        online = online_value if isinstance(online_value, bool) else None

        shared_value = raw.get("shared")
        if not isinstance(shared_value, bool):
            shared_status = raw.get("sharedStatus")
            shared = bool(shared_status) if isinstance(shared_status, (bool, int)) else None
        else:
            shared = shared_value

        return cls(
            device_id=device_id,
            model=model,
            name=name,
            product_id=product_id,
            firmware=firmware,
            category=category,
            online=online,
            shared=shared,
        )

    def key(self, region: str) -> str:
        """Return the pseudonymous device key used by Home Assistant."""

        return stable_device_key(region, self.device_id)


_ROVER_MARKERS = ("pixz6111", "pool", "rover", "swbot")


def rover_candidates(devices: Sequence[MovaDevice]) -> list[MovaDevice]:
    """Prefer likely pool robots without excluding an unidentified X10.

    The X10 cloud model is not known yet. If none of the returned descriptors
    carries a known marker, retaining the full list gives the tester a chance
    to select the X10 and provide the metadata needed to tighten detection.
    """

    candidates = [
        device
        for device in devices
        if any(
            marker
            in " ".join(
                value.casefold()
                for value in (
                    device.model,
                    device.name,
                    device.product_id or "",
                    device.category or "",
                )
            )
            for marker in _ROVER_MARKERS
        )
    ]
    return candidates or list(devices)


@dataclass(frozen=True)
class MovaProperty:
    """One MIoT-style property result."""

    siid: int
    piid: int
    code: int | None
    value: Any = None

    @property
    def supported(self) -> bool:
        """Return whether the property was returned successfully."""

        return self.code == 0


@dataclass(frozen=True)
class MovaState:
    """Conservative state inferred from currently verified properties."""

    status: str | None
    raw_status: int | None
    battery: int | None
    online: bool
    charging: bool | None
    cleaning: bool | None
    last_seen: datetime | None


@dataclass(frozen=True)
class MovaCoordinatorData:
    """Latest coordinator snapshot."""

    device: MovaDevice
    state: MovaState
    properties: Mapping[tuple[int, int], MovaProperty] = field(default_factory=dict)


@dataclass
class MovaRuntimeData:
    """Objects owned by a Home Assistant config entry."""

    client: Any
    coordinator: Any
