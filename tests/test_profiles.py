"""Tests for conservative pool-robot decoding."""

from custom_components.mova_rover.const import STATUS_CLEANING
from custom_components.mova_rover.models import MovaDevice, MovaProperty
from custom_components.mova_rover.profiles import decode_state

DEVICE = MovaDevice(device_id="1", model="unknown", name="Rover")


def test_related_swbot_baseline_decodes_cleaning_and_battery() -> None:
    properties = {
        (2, 1): MovaProperty(2, 1, 0, 4),
        (3, 1): MovaProperty(3, 1, 0, 78),
    }

    state = decode_state(DEVICE, properties, response_received=True)

    assert state.status == STATUS_CLEANING
    assert state.raw_status == 4
    assert state.battery == 78
    assert state.cleaning is True
    assert state.charging is False
    assert state.online is True
    assert state.last_seen is not None


def test_heartbeat_fallback_decodes_charge_bit_without_claiming_status() -> None:
    heartbeat = [0] * 10
    heartbeat[9] = 0x80 | 63
    properties = {(1, 1): MovaProperty(1, 1, 0, heartbeat)}

    state = decode_state(DEVICE, properties, response_received=True)

    assert state.status is None
    assert state.battery == 63
    assert state.charging is True
    assert state.cleaning is None


def test_failed_properties_are_not_interpreted() -> None:
    properties = {
        (2, 1): MovaProperty(2, 1, -4004, 4),
        (3, 1): MovaProperty(3, 1, -4004, 99),
    }

    state = decode_state(DEVICE, properties, response_received=False)

    assert state.status is None
    assert state.raw_status is None
    assert state.battery is None
    assert state.online is False
