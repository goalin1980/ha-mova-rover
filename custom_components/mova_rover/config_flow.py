"""Config flow for the MOVA Rover integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    MovaAuthError,
    MovaCloudClient,
    MovaProtocolError,
    MovaRateLimitError,
    MovaTransportError,
)
from .const import (
    CONF_CATEGORY,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    CONF_FIRMWARE,
    CONF_MODEL,
    CONF_PRODUCT_ID,
    CONF_REGION,
    CONF_SHARED,
    DEFAULT_REGION,
    DOMAIN,
    SUPPORTED_REGIONS,
)
from .models import MovaDevice, rover_candidates, stable_device_key


class MovaRoverConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure one owned or shared MOVA device per entry."""

    VERSION = 1

    def __init__(self) -> None:
        self._credentials: dict[str, str] = {}
        self._devices: list[MovaDevice] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Authenticate against the fixed European MOVAhome cloud."""

        errors: dict[str, str] = {}
        if user_input is not None:
            client = MovaCloudClient(
                async_get_clientsession(self.hass),
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
                region=user_input[CONF_REGION],
            )
            try:
                await client.async_login()
                devices = await client.async_get_devices()
            except MovaAuthError:
                errors["base"] = "invalid_auth"
            except MovaRateLimitError:
                errors["base"] = "rate_limited"
            except MovaTransportError:
                errors["base"] = "cannot_connect"
            except MovaProtocolError:
                errors["base"] = "invalid_response"
            except Exception:  # Home Assistant must keep the flow recoverable.
                errors["base"] = "unknown"
            else:
                if not devices:
                    errors["base"] = "no_devices"
                else:
                    self._credentials = {
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_REGION: user_input[CONF_REGION],
                    }
                    self._devices = rover_candidates(devices)
                    client.clear_credentials()
                    return await self.async_step_device()
            finally:
                client.clear_credentials()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Required(CONF_REGION, default=DEFAULT_REGION): vol.In(SUPPORTED_REGIONS),
                }
            ),
            errors=errors,
        )

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Let the user choose without exposing the cloud device identifier."""

        if not self._devices or not self._credentials:
            return self.async_abort(reason="setup_expired")

        choices = {
            str(index): f"{device.name} ({device.model})"
            for index, device in enumerate(self._devices)
        }
        if user_input is not None:
            try:
                device = self._devices[int(user_input["device"])]
            except (IndexError, KeyError, TypeError, ValueError):
                return self.async_abort(reason="device_not_found")

            region = self._credentials[CONF_REGION]
            await self.async_set_unique_id(stable_device_key(region, device.device_id))
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=device.name,
                data={
                    **self._credentials,
                    CONF_DEVICE_ID: device.device_id,
                    CONF_MODEL: device.model,
                    CONF_DEVICE_NAME: device.name,
                    CONF_PRODUCT_ID: device.product_id,
                    CONF_FIRMWARE: device.firmware,
                    CONF_CATEGORY: device.category,
                    CONF_SHARED: device.shared,
                },
            )

        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema({vol.Required("device"): vol.In(choices)}),
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Start reauthentication for the existing device."""

        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Replace the password only after the configured device is visible."""

        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            client = MovaCloudClient(
                async_get_clientsession(self.hass),
                username=entry.data[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
                region=entry.data[CONF_REGION],
            )
            try:
                await client.async_login()
                devices = await client.async_get_devices()
                if not any(device.device_id == entry.data[CONF_DEVICE_ID] for device in devices):
                    errors["base"] = "device_not_found"
                else:
                    return self.async_update_reload_and_abort(
                        entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                    )
            except MovaAuthError:
                errors["base"] = "invalid_auth"
            except MovaRateLimitError:
                errors["base"] = "rate_limited"
            except MovaTransportError:
                errors["base"] = "cannot_connect"
            except MovaProtocolError:
                errors["base"] = "invalid_response"
            except Exception:
                errors["base"] = "unknown"
            finally:
                client.clear_credentials()

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors,
            description_placeholders={CONF_USERNAME: entry.data[CONF_USERNAME]},
        )
