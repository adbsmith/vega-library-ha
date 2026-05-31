"""DataUpdateCoordinator for the Vega Library integration."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .vega_client import LibraryConfig, PatronAccount, VegaAuthError, VegaAPIError, VegaClient

_LOGGER = logging.getLogger(__name__)


class LibraryDataCoordinator(DataUpdateCoordinator[PatronAccount]):

    def __init__(
        self, hass: HomeAssistant,
        lib_config: LibraryConfig, barcode: str, pin: str,
    ) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN,
            update_interval=timedelta(minutes=DEFAULT_SCAN_INTERVAL),
        )
        self._lib_config = lib_config

    @property
    def lib_config(self) -> LibraryConfig:
        return self._lib_config
        self._barcode    = barcode
        self._pin        = pin

    async def _async_update_data(self) -> PatronAccount:
        try:
            async with VegaClient(self._lib_config, self._barcode, self._pin) as client:
                await client.authenticate()
                return await client.get_account()
        except VegaAuthError as err:
            raise UpdateFailed(f"Library auth failed: {err}") from err
        except VegaAPIError as err:
            raise UpdateFailed(f"Library API error: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected error: {err}") from err
