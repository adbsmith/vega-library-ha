"""Vega Library integration for Home Assistant."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_BARCODE, CONF_PIN, CONF_PORTAL_URL, DOMAIN
from .coordinator import LibraryDataCoordinator
from .vega_client import LibraryConfig

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    lib_config = LibraryConfig.from_portal_url(entry.data[CONF_PORTAL_URL])
    coordinator = LibraryDataCoordinator(
        hass,
        lib_config=lib_config,
        barcode=entry.data[CONF_BARCODE],
        pin=entry.data[CONF_PIN],
    )
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
