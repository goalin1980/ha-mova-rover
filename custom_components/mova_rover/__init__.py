"""MOVA Rover integration for Home Assistant."""

from __future__ import annotations

from typing import Any

from .const import (
    CONF_CATEGORY,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    CONF_FIRMWARE,
    CONF_MODEL,
    CONF_PRODUCT_ID,
    CONF_REGION,
    CONF_SHARED,
)
from .models import MovaDevice, MovaRuntimeData


async def async_setup(hass: Any, config: dict[str, Any]) -> bool:
    """Set up is performed through config entries only."""

    return True


async def async_setup_entry(hass: Any, entry: Any) -> bool:
    """Set up one MOVA Rover device."""

    from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from .api import MovaCloudClient
    from .coordinator import MovaRoverCoordinator

    device = MovaDevice(
        device_id=entry.data[CONF_DEVICE_ID],
        model=entry.data.get(CONF_MODEL, "unknown"),
        name=entry.data.get(CONF_DEVICE_NAME, "MOVA Rover"),
        product_id=entry.data.get(CONF_PRODUCT_ID),
        firmware=entry.data.get(CONF_FIRMWARE),
        category=entry.data.get(CONF_CATEGORY),
        shared=entry.data.get(CONF_SHARED),
    )
    client = MovaCloudClient(
        async_get_clientsession(hass),
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        region=entry.data[CONF_REGION],
    )
    coordinator = MovaRoverCoordinator(hass, client, device, entry.data[CONF_REGION], entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = MovaRuntimeData(client=client, coordinator=coordinator)
    await hass.config_entries.async_forward_entry_setups(
        entry, [Platform.SENSOR, Platform.BINARY_SENSOR]
    )
    return True


async def async_unload_entry(hass: Any, entry: Any) -> bool:
    """Unload a MOVA Rover config entry and forget its cloud tokens."""

    from homeassistant.const import Platform

    unloaded = await hass.config_entries.async_unload_platforms(
        entry, [Platform.SENSOR, Platform.BINARY_SENSOR]
    )
    if unloaded:
        runtime_data = getattr(entry, "runtime_data", None)
        if runtime_data is not None:
            runtime_data.client.clear_credentials()
    return unloaded
