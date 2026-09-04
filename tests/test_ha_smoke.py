"""Import smoke tests against the minimum supported Home Assistant runtime."""

from __future__ import annotations

import asyncio
import importlib
import inspect

import pytest

homeassistant = pytest.importorskip("homeassistant")


@pytest.mark.parametrize(
    "module_name",
    (
        "custom_components.mova_rover",
        "custom_components.mova_rover.binary_sensor",
        "custom_components.mova_rover.config_flow",
        "custom_components.mova_rover.coordinator",
        "custom_components.mova_rover.diagnostics",
        "custom_components.mova_rover.entity",
        "custom_components.mova_rover.sensor",
    ),
)
def test_home_assistant_modules_import(module_name: str) -> None:
    """Every HA-facing module must import on the supported runtime."""

    importlib.import_module(module_name)


def test_coordinator_runtime_supports_bound_config_entry() -> None:
    """Guard the coordinator API required by first-refresh handling."""

    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

    parameters = inspect.signature(DataUpdateCoordinator.__init__).parameters
    assert "config_entry" in parameters


def test_config_flow_masks_password() -> None:
    """The setup form must ask Home Assistant to mask the password."""

    from homeassistant.const import CONF_PASSWORD

    from custom_components.mova_rover.config_flow import MovaRoverConfigFlow

    result = asyncio.run(MovaRoverConfigFlow().async_step_user())
    schema = result["data_schema"].schema
    password_selector = next(
        value for key, value in schema.items() if getattr(key, "schema", None) == CONF_PASSWORD
    )
    assert password_selector.config["type"] == "password"


def test_coordinator_binds_config_entry(tmp_path: object) -> None:
    """Construct the coordinator on the supported Home Assistant runtime."""

    from homeassistant.core import HomeAssistant

    from custom_components.mova_rover.coordinator import MovaRoverCoordinator
    from custom_components.mova_rover.models import MovaDevice

    class FakeEntry:
        def async_on_unload(self, callback: object) -> None:
            self.callback = callback

    async def build() -> None:
        hass = HomeAssistant(str(tmp_path))
        entry = FakeEntry()
        coordinator = MovaRoverCoordinator(
            hass,
            object(),
            MovaDevice("test-device", "PIXZ6111", "Rover X10"),
            "eu",
            entry,  # type: ignore[arg-type]
        )
        assert coordinator.config_entry is entry
        assert getattr(entry, "callback", None) == coordinator.async_shutdown

    asyncio.run(build())
