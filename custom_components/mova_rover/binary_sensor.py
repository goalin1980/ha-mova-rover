"""Binary sensors for MOVA Rover."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import MovaRoverEntity
from .models import MovaCoordinatorData


@dataclass(frozen=True, kw_only=True)
class MovaBinarySensorDescription(BinarySensorEntityDescription):
    """Describe a MOVA Rover binary sensor."""

    value_fn: Callable[[MovaCoordinatorData], bool | None]


BINARY_SENSORS: tuple[MovaBinarySensorDescription, ...] = (
    MovaBinarySensorDescription(
        key="online",
        translation_key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.state.online,
    ),
    MovaBinarySensorDescription(
        key="charging",
        translation_key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value_fn=lambda data: data.state.charging,
    ),
    MovaBinarySensorDescription(
        key="cleaning",
        translation_key="cleaning",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda data: data.state.cleaning,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up MOVA Rover binary sensors."""

    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        MovaRoverBinarySensor(coordinator, description) for description in BINARY_SENSORS
    )


class MovaRoverBinarySensor(MovaRoverEntity, BinarySensorEntity):
    """One coordinator-backed MOVA binary sensor."""

    entity_description: MovaBinarySensorDescription

    def __init__(self, coordinator: Any, description: MovaBinarySensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{self._device_key}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return the latest decoded value."""

        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def available(self) -> bool:
        """Hide only values that have never been observed."""

        return super().available and self.is_on is not None
