"""Config flow for the Vega Library integration."""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from homeassistant import config_entries

from .const import CONF_BARCODE, CONF_PIN, CONF_PORTAL_URL, DOMAIN
from .vega_client import LibraryConfig, VegaAuthError, VegaAPIError, VegaClient

_LOGGER = logging.getLogger(__name__)

PIN_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

STEP_SCHEMA = vol.Schema({
    vol.Required(CONF_PORTAL_URL): str,
    vol.Required(CONF_BARCODE):    str,
    vol.Required(CONF_PIN):        PIN_SELECTOR,
})
REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PIN): PIN_SELECTOR})


class VegaLibraryConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Vega Library."""

    VERSION = 1

    async def _async_try_login(
        self, lib_config: LibraryConfig, barcode: str, pin: str
    ) -> str | None:
        """Return an error key, or None when the credentials work."""
        client = VegaClient(
            lib_config, barcode, pin, session=async_get_clientsession(self.hass)
        )
        try:
            await client.authenticate()
        except VegaAuthError:
            return "invalid_auth"
        except (aiohttp.ClientError, TimeoutError):
            return "cannot_connect"
        except VegaAPIError as err:
            _LOGGER.error("API error during config flow: %s", err)
            return "api_error"
        except Exception:
            _LOGGER.exception("Unexpected error during config flow")
            return "unknown"
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            portal_url = user_input[CONF_PORTAL_URL].strip().rstrip("/")
            if "://" not in portal_url:
                portal_url = f"https://{portal_url}"
            barcode    = user_input[CONF_BARCODE].strip()
            pin        = user_input[CONF_PIN].strip()

            # 1 — parse and validate the portal URL
            lib_config: LibraryConfig | None = None
            try:
                lib_config = LibraryConfig.from_portal_url(portal_url)
            except ValueError:
                errors[CONF_PORTAL_URL] = "invalid_portal_url"

            if lib_config is not None:
                # Use library_domain + barcode as unique ID to prevent duplicates
                unique_id = f"{lib_config.library_domain}:{barcode}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                # 2 — try to authenticate
                if error := await self._async_try_login(lib_config, barcode, pin):
                    errors["base"] = error

            if lib_config is not None and not errors:
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

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """The library rejected the stored PIN: ask for the current one."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            pin        = user_input[CONF_PIN].strip()
            lib_config = LibraryConfig.from_portal_url(entry.data[CONF_PORTAL_URL])
            error      = await self._async_try_login(lib_config, entry.data[CONF_BARCODE], pin)
            if error is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PIN: pin}
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={"card": entry.title},
        )
