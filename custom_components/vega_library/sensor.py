"""Sensor platform for Vega Library integration."""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    SENSOR_CHECKOUTS,
    SENSOR_HOLDS,
    SENSOR_HOLDS_READY,
    SENSOR_FINES,
    SENSOR_OVERDUE,
    SENSOR_DUE_SOON,
    SENSOR_CARD_EXPIRY,
)
from .coordinator import LibraryDataCoordinator
from .vega_client import PatronAccount

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: LibraryDataCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        CheckoutsSensor(coordinator, entry),
        HoldsSensor(coordinator, entry),
        HoldsReadySensor(coordinator, entry),
        FinesSensor(coordinator, entry),
        OverdueSensor(coordinator, entry),
        DueSoonSensor(coordinator, entry),
        CardExpirySensor(coordinator, entry),
    ])


# ── Base ─────────────────────────────────────────────────────────────────────

class _Base(CoordinatorEntity[LibraryDataCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, suffix, name, icon):
        super().__init__(coordinator)
        card_last4 = entry.data.get("barcode", "")[-4:]
        self._attr_unique_id = f"{entry.entry_id}_{suffix}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"{coordinator.lib_config.display_name} (…{card_last4})",
            "manufacturer": "Innovative Interfaces (Vega)",
            "model": f"Vega Discover ({coordinator.lib_config.cluster})",
            "entry_type": "service",
            "configuration_url": coordinator.lib_config.portal_origin + "/portal",
        }

    @property
    def account(self) -> PatronAccount | None:
        return self.coordinator.data


# ── Checkouts ─────────────────────────────────────────────────────────────────

class CheckoutsSensor(_Base):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "items"

    def __init__(self, c, e):
        super().__init__(c, e, SENSOR_CHECKOUTS, "Checkouts", "mdi:book-open")

    @property
    def native_value(self):
        return None if self.account is None else len(self.account.checkouts)

    @property
    def extra_state_attributes(self):
        if self.account is None:
            return {}
        sorted_items = sorted(
            self.account.checkouts,
            key=lambda c: c.due_date or datetime.max.replace(tzinfo=None),
        )
        return {
            "items": [
                {
                    "title":              c.title,
                    "format":             c.format,
                    "due_date":           c.due_date.isoformat() if c.due_date else None,
                    "checkout_date":      c.checkout_date.isoformat() if c.checkout_date else None,
                    "renewable":          c.renewable,
                    "renewals_remaining": c.renewals_remaining,
                    "times_renewed":      c.times_renewed,
                    "renewal_limit":      c.renewal_limit,
                    "cover_url":          c.cover_url,
                    "id":                 c.id,
                }
                for c in sorted_items
            ]
        }


# ── Holds ─────────────────────────────────────────────────────────────────────

class HoldsSensor(_Base):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "items"

    def __init__(self, c, e):
        super().__init__(c, e, SENSOR_HOLDS, "Holds", "mdi:bookmark-clock")

    @property
    def native_value(self):
        return None if self.account is None else len(self.account.holds)

    @property
    def extra_state_attributes(self):
        if self.account is None:
            return {}
        return {
            "holds": [
                {
                    "title":           h.title,
                    "format":          h.format,
                    "status":          h.status,
                    "queue_position":  h.queue_position,
                    "pickup_location": h.pickup_location,
                    "ready":           h.is_ready,
                    "expiry_date":     h.expiry_date.isoformat() if h.expiry_date else None,
                    "placed_date":     h.placed_date.isoformat() if h.placed_date else None,
                    "cover_url":       h.cover_url,
                    "id":              h.id,
                }
                for h in self.account.holds
            ]
        }


# ── Holds ready ───────────────────────────────────────────────────────────────

class HoldsReadySensor(_Base):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "items"

    def __init__(self, c, e):
        super().__init__(c, e, SENSOR_HOLDS_READY, "Holds Ready for Pickup", "mdi:bookmark-check")

    @property
    def native_value(self):
        return None if self.account is None else len(self.account.holds_ready)

    @property
    def extra_state_attributes(self):
        if self.account is None:
            return {}
        return {
            "ready_items": [
                {
                    "title":           h.title,
                    "pickup_location": h.pickup_location,
                    "expiry_date":     h.expiry_date.isoformat() if h.expiry_date else None,
                    "cover_url":       h.cover_url,
                }
                for h in self.account.holds_ready
            ]
        }


# ── Fines ─────────────────────────────────────────────────────────────────────

class FinesSensor(_Base):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "USD"
    _attr_suggested_display_precision = 2

    def __init__(self, c, e):
        super().__init__(c, e, SENSOR_FINES, "Outstanding Fines", "mdi:currency-usd")

    @property
    def native_value(self):
        return None if self.account is None else self.account.fines_total

    @property
    def extra_state_attributes(self):
        if self.account is None:
            return {}
        return {
            "fines": [
                {
                    "title":         f.title,
                    "format":        f.format,
                    "description":   f.description,
                    "type":          f.fine_type,
                    "amount":        f.amount,
                    "date":          f.creation_date,
                    "cover_url":     f.cover_url,
                }
                for f in self.account.fines
            ]
        }


# ── Overdue ───────────────────────────────────────────────────────────────────

class OverdueSensor(_Base):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "items"

    def __init__(self, c, e):
        super().__init__(c, e, SENSOR_OVERDUE, "Overdue Items", "mdi:book-alert")

    @property
    def native_value(self):
        return None if self.account is None else len(self.account.overdue_checkouts)

    @property
    def extra_state_attributes(self):
        if self.account is None:
            return {}
        now = datetime.now().astimezone()
        return {
            "overdue_items": [
                {
                    "title":       c.title,
                    "format":      c.format,
                    "due_date":    c.due_date.isoformat() if c.due_date else None,
                    "days_overdue": (now - c.due_date).days if c.due_date else None,
                    "cover_url":   c.cover_url,
                }
                for c in self.account.overdue_checkouts
            ]
        }


# ── Due soon ──────────────────────────────────────────────────────────────────

class DueSoonSensor(_Base):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "items"

    def __init__(self, c, e):
        super().__init__(c, e, SENSOR_DUE_SOON, "Items Due Soon", "mdi:book-clock")

    @property
    def native_value(self):
        return None if self.account is None else len(self.account.due_soon)

    @property
    def extra_state_attributes(self):
        if self.account is None:
            return {}
        now = datetime.now().astimezone()
        return {
            "due_soon_items": [
                {
                    "title":              c.title,
                    "format":             c.format,
                    "due_date":           c.due_date.isoformat() if c.due_date else None,
                    "days_left":          (c.due_date - now).days if c.due_date else None,
                    "renewable":          c.renewable,
                    "renewals_remaining": c.renewals_remaining,
                    "cover_url":          c.cover_url,
                }
                for c in self.account.due_soon
            ]
        }


# ── Card expiry ───────────────────────────────────────────────────────────────

class CardExpirySensor(_Base):
    """Days until library card expires. Goes negative if already expired."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "days"
    _attr_icon = "mdi:card-account-details-outline"

    def __init__(self, c, e):
        super().__init__(c, e, SENSOR_CARD_EXPIRY, "Card Expires In", "mdi:card-account-details-outline")

    @property
    def native_value(self) -> int | None:
        if self.account is None:
            return None
        return self.account.card_days_until_expiry

    @property
    def extra_state_attributes(self):
        if self.account is None:
            return {}
        exp = self.account.card_expiration_date
        return {
            "expiration_date": exp.isoformat() if exp else None,
        }
