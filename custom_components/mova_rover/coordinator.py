"""Polling coordinator for MOVA Rover."""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from datetime import UTC, datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    MovaAuthError,
    MovaCloudClient,
    MovaDeviceOfflineError,
    MovaProtocolError,
    MovaRateLimitError,
    MovaTransportError,
)
from .const import BASELINE_PROPERTIES, DEVICE_REFRESH_INTERVAL, DOMAIN, UPDATE_INTERVAL
from .models import MovaCoordinatorData, MovaDevice, MovaProperty
from .profiles import decode_state


class MovaRoverCoordinator(DataUpdateCoordinator[MovaCoordinatorData]):
    """Fetch a deliberately small read-only property baseline."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: MovaCloudClient,
        device: MovaDevice,
        region: str,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(
            hass,
            logger=logging.getLogger(__name__),
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self.device = device
        self.region = region
        self._next_device_refresh = 0.0

    def _offline_data(self) -> MovaCoordinatorData:
        if self.data is not None:
            return MovaCoordinatorData(
                device=self.data.device,
                state=replace(self.data.state, online=False),
                properties=self.data.properties,
            )
        state = decode_state(self.device, {}, response_received=False)
        return MovaCoordinatorData(device=self.device, state=state, properties={})

    async def _async_update_data(self) -> MovaCoordinatorData:
        try:
            results = await self.client.async_get_properties(
                self.device.device_id, BASELINE_PROPERTIES
            )

            if time.monotonic() >= self._next_device_refresh:
                devices = await self.client.async_get_devices()
                refreshed = next(
                    (item for item in devices if item.device_id == self.device.device_id), None
                )
                if refreshed is not None:
                    self.device = refreshed
                self._next_device_refresh = (
                    time.monotonic() + DEVICE_REFRESH_INTERVAL.total_seconds()
                )
        except MovaAuthError as err:
            raise ConfigEntryAuthFailed("MOVAhome authentication failed") from err
        except MovaDeviceOfflineError:
            return self._offline_data()
        except MovaRateLimitError as err:
            raise UpdateFailed("MOVAhome rate limit reached") from err
        except MovaTransportError as err:
            raise UpdateFailed("MOVAhome connection failed") from err
        except MovaProtocolError as err:
            raise UpdateFailed("MOVAhome returned an unexpected response") from err

        properties: dict[tuple[int, int], MovaProperty] = {
            (item.siid, item.piid): item for item in results
        }
        state = decode_state(self.device, properties, response_received=True)

        if self.data is not None and state.last_seen is None:
            state = replace(self.data.state, online=state.online)
        elif state.last_seen is None:
            state = replace(state, last_seen=datetime.now(UTC))

        return MovaCoordinatorData(
            device=self.device,
            state=state,
            properties=properties,
        )
