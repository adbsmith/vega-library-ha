"""The "add integration" dialog."""
from __future__ import annotations

from unittest.mock import PropertyMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from custom_components.vega_library.const import DOMAIN
from custom_components.vega_library.vega_client import LibraryConfig

from .common import BARCODE, PIN, PORTAL_URL, FakeVega, pending


async def start_flow(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    return result["flow_id"]


async def submit(hass: HomeAssistant, flow_id: str, url: str = PORTAL_URL, pin: str = PIN):
    return await hass.config_entries.flow.async_configure(
        flow_id, {"portal_url": url, "barcode": BARCODE, "pin": pin}
    )


async def test_user_flow(hass: HomeAssistant, fake_vega: FakeVega) -> None:
    """One dialog, corrected step by step, the way a user would."""
    flow_id = await start_flow(hass)

    result = await submit(hass, flow_id, url="not a url")
    assert result["errors"] == {"portal_url": "invalid_portal_url"}
    result = await submit(hass, flow_id, url="https://catalog.example.org")
    assert result["errors"] == {"portal_url": "invalid_portal_url"}
    result = await submit(hass, flow_id, pin="0000")
    assert result["errors"] == {"base": "invalid_auth"}

    result = await submit(hass, flow_id, url=PORTAL_URL + "/")  # a trailing slash is fine
    assert result["type"].value == "create_entry"
    assert result["title"] == "testlib.na4.iiivega.com (…7890)"
    assert result["data"] == {"portal_url": PORTAL_URL, "barcode": BARCODE, "pin": PIN}


async def test_same_card_twice_is_refused(hass: HomeAssistant, fake_vega: FakeVega) -> None:
    await submit(hass, await start_flow(hass))
    await hass.async_block_till_done()

    result = await submit(hass, await start_flow(hass))
    assert (result["type"].value, result["reason"]) == ("abort", "already_configured")


@pending("section 9, duplicate check before the login")
async def test_duplicate_is_refused_before_login(hass: HomeAssistant, fake_vega: FakeVega) -> None:
    await submit(hass, await start_flow(hass))
    await hass.async_block_till_done()

    fake_vega.grants.clear()
    await submit(hass, await start_flow(hass))
    assert fake_vega.grants == []  # no credentials were sent for a card that is already set up


@pending("section 9, portal URL without https://")
async def test_url_without_scheme_is_accepted(hass: HomeAssistant, fake_vega: FakeVega) -> None:
    result = await submit(hass, await start_flow(hass), url="testlib.na4.iiivega.com/portal")
    assert result["type"].value == "create_entry"
    assert result["data"]["portal_url"] == PORTAL_URL


async def test_auth_server_error_page(hass: HomeAssistant, fake_vega: FakeVega) -> None:
    """A 502 HTML page from the login server is an API error, not a crash."""
    fake_vega.fail = {"token": 502}
    result = await submit(hass, await start_flow(hass))
    assert result["errors"] == {"base": "api_error"}


@pending("section 9, cannot_connect error")
async def test_unreachable_server_says_cannot_connect(hass: HomeAssistant, socket_enabled) -> None:
    with patch.object(
        LibraryConfig, "keycloak_token_url",
        new_callable=PropertyMock, return_value="http://127.0.0.1:9/token",
    ):
        result = await submit(hass, await start_flow(hass))
    assert result["errors"] == {"base": "cannot_connect"}
