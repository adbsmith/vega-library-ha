"""What the sensors report for a given library account."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant.components.recorder.common import async_wait_recording_done

from .common import NOW, FakeVega, errors_in, make_checkout, new_entry, pending, poll, sensor, setup


async def test_sensor_values(hass: HomeAssistant, fake_vega: FakeVega) -> None:
    entry = new_entry(hass)
    await setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED

    assert sensor(hass, entry, "checkouts").state == "3"
    assert sensor(hass, entry, "holds").state == "2"
    assert sensor(hass, entry, "holds_ready").state == "1"
    assert sensor(hass, entry, "fines").state == "4.5"
    assert sensor(hass, entry, "overdue").state == "1"
    assert sensor(hass, entry, "due_soon").state == "1"
    assert sensor(hass, entry, "card_expiry").state == str((date(2027, 6, 30) - date.today()).days)

    items = sensor(hass, entry, "checkouts").attributes["items"]
    assert [item["id"] for item in items] == ["co-0003", "co-0002", "co-0001"]  # soonest due first
    assert sensor(hass, entry, "holds_ready").attributes["ready_items"][0]["title"] == "Ready Hold"


async def test_checkout_without_due_date(hass: HomeAssistant, fake_vega: FakeVega, caplog) -> None:
    """A missing due date used to raise TypeError while sorting and break the sensor."""
    fake_vega.checkouts = [
        make_checkout(1, None),
        make_checkout(2, NOW + timedelta(days=5)),
        make_checkout(3, None),
    ]
    entry = new_entry(hass)
    await setup(hass, entry)

    state = sensor(hass, entry, "checkouts")
    assert state.state == "3"
    assert [item["id"] for item in state.attributes["items"]] == ["co-0002", "co-0001", "co-0003"]
    assert errors_in(caplog) == []


async def test_due_date_without_utc_offset(hass: HomeAssistant, fake_vega: FakeVega, caplog) -> None:
    """A timestamp with no offset used to raise TypeError in the overdue / due soon sensors."""
    checkout = make_checkout(1, NOW)
    checkout["dueDate"] = (NOW - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S")
    fake_vega.checkouts = [checkout]
    entry = new_entry(hass)
    await setup(hass, entry)

    assert sensor(hass, entry, "overdue").state == "1"
    assert sensor(hass, entry, "due_soon").state == "0"
    assert errors_in(caplog) == []


@pending("section 5, renewalLimit of 0")
async def test_renewal_limit_of_zero(hass: HomeAssistant, fake_vega: FakeVega) -> None:
    """renewalLimit: 0 means "cannot be renewed", not "999 renewals left"."""
    fake_vega.checkouts = [
        make_checkout(1, NOW + timedelta(days=5), limit=0),
        make_checkout(2, NOW + timedelta(days=6), limit=3, count=1),
        make_checkout(3, NOW + timedelta(days=7), limit=None),
    ]
    entry = new_entry(hass)
    await setup(hass, entry)

    items = {item["id"]: item for item in sensor(hass, entry, "checkouts").attributes["items"]}
    assert (items["co-0001"]["renewable"], items["co-0001"]["renewals_remaining"]) == (False, 0)
    assert (items["co-0002"]["renewable"], items["co-0002"]["renewals_remaining"]) == (True, 2)
    assert (items["co-0003"]["renewable"], items["co-0003"]["renewals_remaining"]) == (True, 999)


@pending("section 6, item lists kept out of the recorder")
async def test_item_lists_stay_out_of_the_recorder(
    recorder_mock, hass: HomeAssistant, fake_vega: FakeVega, caplog
) -> None:
    """120 checkouts is about 40 kB of attributes; the recorder refuses anything over 16 kB."""
    fake_vega.checkouts = [make_checkout(n, NOW + timedelta(days=n % 21)) for n in range(120)]
    entry = new_entry(hass)
    await setup(hass, entry)
    await async_wait_recording_done(hass)

    assert "exceed maximum size" not in caplog.text
    assert len(sensor(hass, entry, "checkouts").attributes["items"]) == 120  # still there for templates


@pending("section 4, failed fines request shows unknown")
async def test_failed_fines_request_is_unknown_not_zero(hass: HomeAssistant, fake_vega: FakeVega) -> None:
    entry = new_entry(hass)
    await setup(hass, entry)
    assert sensor(hass, entry, "fines").state == "4.5"

    fake_vega.fail = {"fines": 500, "patron": 500}
    await poll(hass, entry)
    assert sensor(hass, entry, "fines").state == "unknown"
    assert sensor(hass, entry, "card_expiry").state == "unknown"
    assert sensor(hass, entry, "checkouts").state == "3"  # everything else keeps working

    fake_vega.fail = {}
    await poll(hass, entry)
    assert sensor(hass, entry, "fines").state == "4.5"


@pending("sections 4 and 8, failed optional requests are logged once")
async def test_failed_optional_requests_are_logged_once(
    hass: HomeAssistant, fake_vega: FakeVega, caplog
) -> None:
    entry = new_entry(hass)
    await setup(hass, entry)

    def warnings() -> list[str]:
        return [
            record.getMessage() for record in caplog.records
            if record.levelno == logging.WARNING
            and record.name.startswith("custom_components.vega_library")
        ]

    fake_vega.fail = {"fines": 500, "patron": 500}
    caplog.clear()
    await poll(hass, entry)
    assert len(warnings()) == 2            # one for fines, one for the patron profile
    assert "access-abc" not in caplog.text  # the access token never reaches the log

    caplog.clear()
    await poll(hass, entry)                 # still failing: no repeat warnings
    assert warnings() == []
