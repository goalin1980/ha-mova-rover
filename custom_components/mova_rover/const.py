"""Constants for the MOVA Rover integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "mova_rover"
INTEGRATION_VERSION = "0.1.1"

CONF_REGION = "region"
CONF_DEVICE_ID = "device_id"
CONF_MODEL = "model"
CONF_DEVICE_NAME = "device_name"
CONF_PRODUCT_ID = "product_id"
CONF_FIRMWARE = "firmware"
CONF_CATEGORY = "category"
CONF_SHARED = "shared"

DEFAULT_REGION = "eu"
SUPPORTED_REGIONS = {"eu": "Europe"}

UPDATE_INTERVAL = timedelta(seconds=60)
DEVICE_REFRESH_INTERVAL = timedelta(minutes=15)

# Read-only properties verified on the related Dreame Z1 pool robot. Their exact
# meaning on a MOVA Rover X10 remains deliberately labelled as provisional.
BASELINE_PROPERTIES: tuple[tuple[int, int], ...] = (
    (1, 1),  # Heartbeat/status byte array on Dreame Z1
    (2, 1),  # Operating status on Dreame Z1
    (3, 1),  # Battery percentage on Dreame Z1
)

STATUS_IDLE = "idle"
STATUS_DOCKED = "docked"
STATUS_CHARGING = "charging"
STATUS_CHARGED = "charged"
STATUS_UPDATING = "updating"
STATUS_CLEANING = "cleaning"

STATUS_OPTIONS = (
    STATUS_IDLE,
    STATUS_DOCKED,
    STATUS_CHARGING,
    STATUS_CHARGED,
    STATUS_UPDATING,
    STATUS_CLEANING,
)
