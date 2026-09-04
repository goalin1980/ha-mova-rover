"""Tests for safe MOVA data models."""

from custom_components.mova_rover.models import (
    MovaDevice,
    rover_candidates,
    stable_device_key,
)


def test_device_descriptor_keeps_only_required_metadata() -> None:
    raw = {
        "did": "secret-device-123",
        "model": "mova.swbot.test",
        "customName": "Friend's pool",
        "productId": "PIXZ6111",
        "ver": "1.2.3",
        "online": True,
        "sharedStatus": 1,
        "access_token": "must-not-survive",
        "deviceInfo": {"displayName": "Rover X10", "categoryPath": "pool/robot"},
    }

    device = MovaDevice.from_cloud(raw)

    assert device.device_id == "secret-device-123"
    assert device.model == "mova.swbot.test"
    assert device.name == "Friend's pool"
    assert device.product_id == "PIXZ6111"
    assert device.firmware == "1.2.3"
    assert device.category == "pool/robot"
    assert device.online is True
    assert device.shared is True
    assert not hasattr(device, "access_token")


def test_device_key_is_stable_and_does_not_contain_identifier() -> None:
    key = stable_device_key("eu", "secret-device-123")
    assert key == stable_device_key("eu", "secret-device-123")
    assert key != stable_device_key("eu", "secret-device-456")
    assert "secret-device-123" not in key
    assert len(key) == 20


def test_rover_candidates_prefer_pool_markers() -> None:
    vacuum = MovaDevice(device_id="1", model="mova.vacuum.test", name="Kitchen")
    rover = MovaDevice(
        device_id="2",
        model="unknown",
        name="Cleaner",
        product_id="PIXZ6111",
    )

    assert rover_candidates([vacuum, rover]) == [rover]


def test_rover_candidates_keep_unknown_list_as_discovery_fallback() -> None:
    unknown = MovaDevice(device_id="1", model="mova.device.g9999", name="Cleaner")

    assert rover_candidates([unknown]) == [unknown]
