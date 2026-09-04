"""Shared entity model for MOVA Rover."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MovaRoverCoordinator


class MovaRoverEntity(CoordinatorEntity[MovaRoverCoordinator]):
    """Base entity tied to one pseudonymous MOVA device key."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: MovaRoverCoordinator) -> None:
        super().__init__(coordinator)
        self._device_key = coordinator.device.key(coordinator.region)

    @property
    def device_info(self) -> DeviceInfo:
        """Describe the device without exposing its cloud identifier."""

        device = self.coordinator.data.device
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_key)},
            manufacturer="MOVA",
            model=device.model,
            name=device.name,
            sw_version=device.firmware,
        )
