"""Sensors for MOVA Rover."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import STATUS_OPTIONS
from .entity import MovaRoverEntity
from .models import MovaCoordinatorData


@dataclass(frozen=True, kw_only=True)
class MovaSensorDescription(SensorEntityDescription):
    """Describe a MOVA Rover sensor."""

    value_fn: Callable[[MovaCoordinatorData], Any]


SENSORS: tuple[MovaSensorDescription, ...] = (
    MovaSensorDescription(
        key="battery",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda data: data.state.battery,
    ),
    MovaSensorDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=list(STATUS_OPTIONS),
        value_fn=lambda data: data.state.status,
    ),
    MovaSensorDescription(
        key="raw_status",
        translation_key="raw_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.state.raw_status,
    ),
    MovaSensorDescription(
        key="last_seen",
        translation_key="last_seen",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.state.last_seen,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up MOVA Rover sensors."""

    coordinator = entry.runtime_data.coordinator
    async_add_entities(MovaRoverSensor(coordinator, description) for description in SENSORS)


class MovaRoverSensor(MovaRoverEntity, SensorEntity):
    """One coordinator-backed MOVA sensor."""

    entity_description: MovaSensorDescription

    def __init__(self, coordinator: Any, description: MovaSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{self._device_key}_{description.key}"

    @property
    def native_value(self) -> Any:
        """Return the latest decoded or diagnostic value."""

        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def available(self) -> bool:
        """Hide only values that have never been observed."""

        return super().available and self.native_value is not None
