"""Conservative protocol decoding for MOVA pool robots."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from .const import (
    STATUS_CHARGED,
    STATUS_CHARGING,
    STATUS_CLEANING,
    STATUS_DOCKED,
    STATUS_IDLE,
    STATUS_UPDATING,
)
from .models import MovaDevice, MovaProperty, MovaState

_RELATED_SWBOT_STATUS = {
    0: STATUS_IDLE,
    1: STATUS_CHARGING,
    2: STATUS_CHARGED,
    3: STATUS_UPDATING,
    4: STATUS_CLEANING,
}

_ROVER_X10_MODEL = "mova.swbot.g2526"


def _integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _heartbeat_battery(value: object) -> tuple[int | None, bool | None]:
    """Decode only the byte proven useful on the related Dreame Z1."""

    if not isinstance(value, (list, tuple)) or len(value) <= 9:
        return None, None
    encoded = _integer(value[9])
    if encoded is None or encoded < 0 or encoded > 255:
        return None, None
    return encoded & 0x7F, bool(encoded & 0x80)


def decode_state(
    device: MovaDevice,
    properties: Mapping[tuple[int, int], MovaProperty],
    *,
    response_received: bool,
) -> MovaState:
    """Decode the small related-device baseline without inventing X10 semantics."""

    heartbeat = properties.get((1, 1))
    heartbeat_battery, heartbeat_charging = _heartbeat_battery(
        heartbeat.value if heartbeat and heartbeat.supported else None
    )

    battery_property = properties.get((3, 1))
    battery = _integer(
        battery_property.value if battery_property and battery_property.supported else None
    )
    if battery is None or not 0 <= battery <= 100:
        battery = (
            heartbeat_battery
            if heartbeat_battery is not None and heartbeat_battery <= 100
            else None
        )

    status_property = properties.get((2, 1))
    raw_status = _integer(
        status_property.value if status_property and status_property.supported else None
    )
    status = _RELATED_SWBOT_STATUS.get(raw_status)

    charging: bool | None = heartbeat_charging
    if device.model.casefold() == _ROVER_X10_MODEL and raw_status == 2:
        # Correlated X10 captures return 2 both while charging and after charge
        # completion, then 0 when removed from the dock. The baseline property
        # therefore proves a docked state but not whether current is flowing.
        status = STATUS_DOCKED
        charging = None
    elif status in (STATUS_CHARGING, STATUS_CHARGED):
        charging = True
    elif status in (STATUS_IDLE, STATUS_CLEANING, STATUS_UPDATING):
        charging = False

    cleaning = raw_status == 4 if raw_status is not None else None
    online = response_received
    if device.online is False and not response_received:
        online = False

    return MovaState(
        status=status,
        raw_status=raw_status,
        battery=battery,
        online=online,
        charging=charging,
        cleaning=cleaning,
        last_seen=datetime.now(UTC) if response_received else None,
    )
