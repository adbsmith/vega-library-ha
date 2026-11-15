"""DataUpdateCoordinator for the Vega Library integration."""
from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_BARCODE, CONF_PIN, DEFAULT_SCAN_INTERVAL, DOMAIN
from .vega_client import LibraryConfig, PatronAccount, VegaAuthError, VegaAPIError, VegaClient

_LOGGER = logging.getLogger(__name__)


class LibraryDataCoordinator(DataUpdateCoordinator[PatronAccount]):

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, lib_config: LibraryConfig,
    ) -> None:
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(minutes=DEFAULT_SCAN_INTERVAL),
        )
        self._lib_config = lib_config
        # One client for the life of the entry: it reuses Home Assistant's HTTP
        # session and keeps its token between polls.
        self._client = VegaClient(
            lib_config, entry.data[CONF_BARCODE], entry.data[CONF_PIN],
            session=async_get_clientsession(hass),
        )

    @property
    def lib_config(self) -> LibraryConfig:
        return self._lib_config

    async def _async_update_data(self) -> PatronAccount:
        try:
            return await self._client.get_account()
        except VegaAuthError as err:
            # Stops polling and prompts for a new PIN instead of retrying forever.
            raise ConfigEntryAuthFailed(str(err)) from err
        except (VegaAPIError, aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed(f"Library API error: {err}") from err
