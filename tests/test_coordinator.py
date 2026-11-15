"""Polling: how the integration logs in, fetches, and reacts when something fails."""
from __future__ import annotations

import time

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from custom_components.vega_library.const import DOMAIN

from .common import FakeVega, new_entry, pending, poll, sensor, setup, skip_ahead


async def test_server_error_is_retried(hass: HomeAssistant, fake_vega: FakeVega) -> None:
    """A failing library server makes the sensors unavailable until the next good poll."""
    entry = new_entry(hass)
    await setup(hass, entry)

    fake_vega.fail = {"checkouts": 503}
    await skip_ahead(hass)
    assert sensor(hass, entry, "checkouts").state == "unavailable"
    assert hass.config_entries.flow.async_progress() == []  # not treated as a bad PIN

    fake_vega.fail = {}
    await skip_ahead(hass)
    assert sensor(hass, entry, "checkouts").state == "3"


async def test_requests_run_concurrently(hass: HomeAssistant, fake_vega: FakeVega) -> None:
    entry = new_entry(hass)
    await setup(hass, entry)
    fake_vega.delay = 0.1
    fake_vega.max_in_flight = 0
    await poll(hass, entry)
    assert fake_vega.max_in_flight == 4


async def test_token_is_reused_between_polls(hass: HomeAssistant, fake_vega: FakeVega) -> None:
    entry = new_entry(hass)
    await setup(hass, entry)
    await poll(hass, entry)
    await poll(hass, entry)
    assert fake_vega.grants == ["password"]  # one login for three polls


async def test_expired_token_is_refreshed(hass: HomeAssistant, fake_vega: FakeVega) -> None:
    entry = new_entry(hass)
    await setup(hass, entry)
    client = hass.data[DOMAIN][entry.entry_id]._client

    client._cache.expires_at = time.time() - 1          # access token expired
    await poll(hass, entry)
    assert fake_vega.grants == ["password", "refresh_token"]  # the PIN is not sent again

    client._cache.expires_at = time.time() - 1          # refresh token expired too
    client._cache.refresh_expires_at = time.time() - 1
    await poll(hass, entry)
    assert fake_vega.grants == ["password", "refresh_token", "password"]
    assert sensor(hass, entry, "checkouts").state == "3"


async def test_rejected_token_causes_one_relogin(hass: HomeAssistant, fake_vega: FakeVega) -> None:
    """All four concurrent requests get a 401; they must share a single new login."""
    entry = new_entry(hass)
    await setup(hass, entry)
    fake_vega.access_token = "access-rotated"  # the server stops accepting the old token
    fake_vega.requests.clear()
    fake_vega.grants.clear()
    await poll(hass, entry)

    assert fake_vega.grants == ["password"]
    assert fake_vega.api_calls == 8             # 4 rejected + 4 retried
    assert sensor(hass, entry, "checkouts").state == "3"


async def test_changed_pin_starts_reauth_and_stops_polling(hass: HomeAssistant, fake_vega: FakeVega) -> None:
    fake_vega.expires_in = fake_vega.refresh_expires_in = 1  # every poll has to log in
    entry = new_entry(hass)
    await setup(hass, entry)

    fake_vega.valid_pin = "9999"                # the PIN was changed at the library
    fake_vega.grants.clear()
    await skip_ahead(hass)
    assert fake_vega.grants == ["password"]     # one rejected login ...
    await skip_ahead(hass)
    await skip_ahead(hass)
    assert fake_vega.grants == ["password"]     # ... and no more after that
    assert sensor(hass, entry, "checkouts").state == "unavailable"

    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == [config_entries.SOURCE_REAUTH]

    result = await hass.config_entries.flow.async_configure(flows[0]["flow_id"], {"pin": "0000"})
    assert result["errors"] == {"base": "invalid_auth"}
    result = await hass.config_entries.flow.async_configure(flows[0]["flow_id"], {"pin": "9999"})
    await hass.async_block_till_done()
    assert (result["type"].value, result["reason"]) == ("abort", "reauth_successful")
    assert entry.data["pin"] == "9999"
    assert entry.state is ConfigEntryState.LOADED
    assert sensor(hass, entry, "checkouts").state == "3"


async def test_wrong_pin_at_startup_asks_for_reauth(hass: HomeAssistant, fake_vega: FakeVega) -> None:
    fake_vega.valid_pin = "9999"
    entry = new_entry(hass)
    await setup(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_ERROR  # not SETUP_RETRY: no retry loop
    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1
    assert fake_vega.grants == ["password"]

    result = await hass.config_entries.flow.async_configure(flows[0]["flow_id"], {"pin": "9999"})
    await hass.async_block_till_done()
    assert result["reason"] == "reauth_successful"
    assert entry.state is ConfigEntryState.LOADED
    assert sensor(hass, entry, "checkouts").state == "3"
