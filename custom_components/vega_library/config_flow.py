"""Config flow for the Vega Library integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_BARCODE, CONF_PIN, CONF_PORTAL_URL, DOMAIN
from .vega_client import LibraryConfig, VegaAuthError, VegaAPIError, VegaClient

_LOGGER = logging.getLogger(__name__)

STEP_SCHEMA = vol.Schema({
    vol.Required(CONF_PORTAL_URL): str,
    vol.Required(CONF_BARCODE):    str,
    vol.Required(CONF_PIN):        TextSelector(
        TextSelectorConfig(type=TextSelectorType.PASSWORD)
    ),
})


class VegaLibraryConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Vega Library."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            portal_url = user_input[CONF_PORTAL_URL].strip().rstrip("/")
            barcode    = user_input[CONF_BARCODE].strip()
            pin        = user_input[CONF_PIN].strip()

            # 1 — parse and validate the portal URL
            if not LibraryConfig.is_valid_portal_url(portal_url):
                errors[CONF_PORTAL_URL] = "invalid_portal_url"
            else:
                try:
                    lib_config = LibraryConfig.from_portal_url(portal_url)
                except ValueError:
                    errors[CONF_PORTAL_URL] = "invalid_portal_url"

            # 2 — try to authenticate (only if URL parsed OK)
            if not errors:
                try:
                    async with VegaClient(lib_config, barcode, pin) as client:
                        await client.authenticate()
                except VegaAuthError:
                    errors["base"] = "invalid_auth"
                except VegaAPIError as err:
                    _LOGGER.exception("API error during config flow: %s", err)
                    errors["base"] = "api_error"
                except Exception:
                    _LOGGER.exception("Unexpected error during config flow")
                    errors["base"] = "unknown"

            if not errors:
                # Use library_domain + barcode as unique ID to prevent duplicates
                unique_id = f"{lib_config.library_domain}:{barcode}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"{lib_config.library_domain} (…{barcode[-4:]})",
                    data={
                        CONF_PORTAL_URL: portal_url,
                        CONF_BARCODE:    barcode,
                        CONF_PIN:        pin,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_SCHEMA,
            errors=errors,
        )
