"""Shared test helpers: a fake Vega server and a few shortcuts.

The integration is tested end to end. Home Assistant loads the real integration and
the client talks over real HTTP to FakeVega, a small local server that stands in for
the Keycloak login endpoint and the Vega patron API.

The payloads are synthetic: they contain the fields the integration's parsers read.
Replace them with (redacted) captures from a real library when you have some.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import pytest
from aiohttp import web
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

from custom_components.vega_library.const import DOMAIN

PORTAL_URL = "https://testlib.na4.iiivega.com/portal"
BARCODE = "21234000567890"
PIN = "1234"
NOW = datetime.now(timezone.utc)


def pending(change: str) -> pytest.MarkDecorator:
    """Mark a test for a fix that is not on main yet.

    Until the fix is applied the test is reported as "xfailed" and does not fail the
    run. When you apply the fix, delete the @pending line above the test so that it
    counts from then on. If you forget, the run fails with XPASS(strict), which only
    means "this passes now, remove the marker".
    """
    return pytest.mark.xfail(
        strict=True,
        reason=f"Not on main yet: {change}. If this is reported as XPASS, the fix is in "
        "and the @pending line above the test can be deleted.",
    )


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_checkout(
    number: int, due: datetime | None, *, limit: int | None = 3, count: int = 0
) -> dict:
    """One checkout as the API returns it. `limit=None` leaves renewalLimit out."""
    item: dict = {
        "id": f"co-{number:04d}",
        "checkOutDate": iso(NOW - timedelta(days=14)),
        "renewalCount": count,
        "resource": {
            "title": f"A Reasonably Long Book Title Number {number}",
            "materialType": "Book",
            "coverUrl": {
                "medium": f"https://covers.example.invalid/cover?isbn=97800000{number:05d}&size=medium"
            },
        },
    }
    if limit is not None:
        item["renewalLimit"] = limit
    if due is not None:
        item["dueDate"] = iso(due)
    return item


class FakeVega:
    """An in-memory library account served over HTTP.

    Tests change its attributes to set up a situation (a wrong PIN, a failing
    endpoint, slow responses) and read `requests` / `grants` to see what the
    integration sent.
    """

    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []  # (method, path) of every request
        self.grants: list[str] = []                # grant_type of every login request
        self.delay = 0.0                           # seconds each request takes
        self.in_flight = 0
        self.max_in_flight = 0                     # most requests being served at once
        self.valid_pin = PIN
        self.access_token = "access-abc"           # change it and the old token gets a 401
        self.expires_in = 300
        self.refresh_expires_in = 1800
        self.fail: dict[str, int] = {}             # endpoint name -> HTTP status to return
        self.checkouts: list[dict] = [
            make_checkout(1, NOW + timedelta(days=10)),
            make_checkout(2, NOW + timedelta(days=2)),   # due soon
            make_checkout(3, NOW - timedelta(days=4)),   # overdue
        ]
        self.holds: list[dict] = [
            {
                "id": "h-1", "status": "READY", "pickupLocation": "Main",
                "expiryDate": iso(NOW + timedelta(days=5)),
                "placedDate": iso(NOW - timedelta(days=20)),
                "resource": {"title": "Ready Hold", "materialType": "Book",
                             "coverUrl": {"medium": "https://covers.example.invalid/h1"}},
            },
            {
                "id": "h-2", "status": "PENDING", "queuePosition": 7, "pickupLocation": "Main",
                "placedDate": iso(NOW - timedelta(days=3)),
                "resource": {"title": "Waiting Hold", "materialType": "DVD", "coverUrl": None},
            },
        ]
        self.fines: dict = {
            "totalOutstandingAmount": 4.5,
            "data": [{
                "id": "f-1", "description": "Overdue", "type": "OVERDUE",
                "outstandingAmount": 4.5, "creationDate": "2026-10-01",
                "resource": {"title": "Late Book", "materialType": "Book"},
            }],
        }
        self.patron: dict = {"expirationDate": "2027-06-30"}

        self.app = web.Application()
        self.app.router.add_post("/auth/realms/{realm}/protocol/openid-connect/token", self._token)
        self.app.router.add_get("/api/search-result/patrons/me/checkouts", self._api("checkouts"))
        self.app.router.add_get("/api/search-result/patrons/me/holds", self._api("holds"))
        self.app.router.add_get("/api/search-result/gates/patrons/me/fines", self._api("fines"))
        self.app.router.add_get("/api/search-result/patrons/me", self._api("patron"))
        self.base = ""  # set by the fake_vega fixture once the server is listening

    @property
    def api_calls(self) -> int:
        return sum(1 for method, _ in self.requests if method == "GET")

    async def _busy(self) -> None:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delay)
        finally:
            self.in_flight -= 1

    async def _token(self, request: web.Request) -> web.Response:
        self.requests.append(("POST", request.path))
        await self._busy()
        if status := self.fail.get("token"):
            return web.Response(status=status, text="<html>upstream error</html>", content_type="text/html")
        if request.match_info["realm"] != "testlib":
            return web.json_response({"error": "Realm does not exist"}, status=404)
        form = await request.post()
        self.grants.append(str(form.get("grant_type")))
        if form.get("grant_type") == "password" and form.get("password") != self.valid_pin:
            return web.json_response(
                {"error": "invalid_grant", "error_description": "Invalid user credentials"},
                status=401,
            )
        return web.json_response({
            "access_token": self.access_token,
            "refresh_token": "refresh-xyz",
            "expires_in": self.expires_in,
            "refresh_expires_in": self.refresh_expires_in,
            "token_type": "Bearer",
        })

    def _api(self, name: str):
        async def handler(request: web.Request) -> web.Response:
            self.requests.append(("GET", request.path))
            await self._busy()
            if request.headers.get("Authorization") != f"Bearer {self.access_token}":
                return web.json_response({"error": "unauthorized"}, status=401)
            if status := self.fail.get(name):
                return web.json_response({"error": "boom"}, status=status)
            return web.json_response(getattr(self, name))

        return handler


# ── Shortcuts used by the tests ───────────────────────────────────────────────

def new_entry(hass: HomeAssistant, pin: str = PIN) -> MockConfigEntry:
    """A config entry as the config flow would have created it."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="testlib.na4.iiivega.com (…7890)",
        unique_id=f"testlib.na4.iiivega.com:{BARCODE}",
        data={"portal_url": PORTAL_URL, "barcode": BARCODE, "pin": pin},
    )
    entry.add_to_hass(hass)
    return entry


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def poll(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Fetch from the library now, as the 30 minute timer would."""
    await hass.data[DOMAIN][entry.entry_id].async_refresh()
    await hass.async_block_till_done()


async def skip_ahead(hass: HomeAssistant, minutes: int = 31) -> None:
    """Move the clock past the next scheduled poll and let it run."""
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=minutes))
    await hass.async_block_till_done(wait_background_tasks=True)


def sensor(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> State:
    """The state of one sensor. `key` is the end of its unique id, e.g. "checkouts"."""
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id, f"the {key} sensor was not created"
    state = hass.states.get(entity_id)
    assert state, f"the {key} sensor has no state"
    return state


def errors_in(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.levelno >= logging.ERROR]
