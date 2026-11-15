# Vega Library for Home Assistant

[![HACS Badge](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=adbsmith&repository=vega-library-ha&category=integration)
[![GitHub Release](https://img.shields.io/github/release/adbsmith/vega-library-ha.svg)](https://github.com/adbsmith/vega-library-ha/releases)
[![Downloads](https://img.shields.io/github/downloads/adbsmith/vega-library-ha/total.svg)](https://github.com/adbsmith/vega-library-ha/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A Home Assistant custom integration for libraries using the [**Innovative Interfaces Vega Discover**](https://iii.com) platform. Track your checkouts, holds, fines, and card expiry — and automate reminders — directly from Home Assistant.

> **Is your library on Vega?** Check your library's online catalog. If the URL contains `.iiivega.com`, this integration works for you.

---

## Sensors

| Sensor | What it shows |
|---|---|
| **Checkouts** | Number of items checked out, sorted by due date. Attributes include title, format, due date, renewals remaining, and cover image URL. |
| **Holds** | Total hold requests. Attributes include status, queue position, pickup location. |
| **Holds Ready for Pickup** | Holds available to collect now — ideal for push notifications. |
| **Outstanding Fines** | Total fines in USD. Attributes include a per-item breakdown with title and description. Shows `unknown` if the library's fines request fails. |
| **Overdue Items** | Items past their due date, with days overdue per item. |
| **Items Due Soon** | Items due within 3 days — a gentler early reminder. |
| **Card Expires In** | Days until your library card expires. |

**Entity IDs** include your library's address and the last four digits of your card number, for example `sensor.yourlibrary_na4_iiivega_com_1234_checkouts`. You can see yours under **Settings → Devices & Services → Vega Library**. The examples below use that example ID; replace it with your own.

---

## Installation

Requires Home Assistant 2024.11 or newer.

### Via the Marketplace or HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=adbsmith&repository=vega-library-ha&category=integration)

1. Search for **Vega Library**:
   - Home Assistant 2026.11 or newer: **Settings → Marketplace**
   - Older versions: **HACS**
2. Install it
3. Restart Home Assistant

### Manual

1. Copy the `custom_components/vega_library` folder into your HA `config/custom_components/` directory
2. Restart Home Assistant

---

## Configuration

After installation, go to **Settings → Devices & Services → Add Integration → Vega Library**, or use this button:

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=vega_library)

You need three things:

**Portal URL** — your library's Vega portal URL. Find it by going to your library's website and clicking the online catalog or "My Account" link. It will look like this (the `https://` is optional):
```
https://yourlibrary.na4.iiivega.com/portal
```

**Library card number** — the barcode number on your library card.

**PIN** — your library account PIN (usually 4 digits; the same one you use to log in online).

---

## Automation examples

### Notification when a hold is ready

```yaml
automation:
  - alias: "Library hold ready for pickup"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.yourlibrary_na4_iiivega_com_1234_holds_ready_for_pickup
        above: 0
    actions:
      - action: notify.mobile_app_your_phone
        data:
          title: "📚 Library hold ready!"
          message: >
            {{ state_attr('sensor.yourlibrary_na4_iiivega_com_1234_holds_ready_for_pickup', 'ready_items')
               | map(attribute='title') | join(', ') }} is ready to collect.
```

### Reminder for items due within 3 days

```yaml
automation:
  - alias: "Library items due soon"
    triggers:
      - trigger: time
        at: "09:00:00"
    conditions:
      - condition: numeric_state
        entity_id: sensor.yourlibrary_na4_iiivega_com_1234_items_due_soon
        above: 0
    actions:
      - action: notify.mobile_app_your_phone
        data:
          title: "📚 Library items due soon"
          message: >
            {% for item in state_attr('sensor.yourlibrary_na4_iiivega_com_1234_items_due_soon', 'due_soon_items') %}
              {{ item.title }} — due in {{ item.days_left }} day(s).
            {% endfor %}
```

### Library card expiry warning

```yaml
automation:
  - alias: "Library card expiry warning"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.yourlibrary_na4_iiivega_com_1234_card_expires_in
        below: 30
    actions:
      - action: notify.mobile_app_your_phone
        data:
          title: "🪪 Library card expiring"
          message: >
            Your library card expires in
            {{ states('sensor.yourlibrary_na4_iiivega_com_1234_card_expires_in') }} days.
            Renew at the library or online.
```

---

## Lovelace card

```yaml
type: entities
title: Library
entities:
  - entity: sensor.yourlibrary_na4_iiivega_com_1234_checkouts
    name: Checked out
  - entity: sensor.yourlibrary_na4_iiivega_com_1234_holds
    name: Holds
  - entity: sensor.yourlibrary_na4_iiivega_com_1234_holds_ready_for_pickup
    name: Ready to collect
  - entity: sensor.yourlibrary_na4_iiivega_com_1234_overdue_items
    name: Overdue
  - entity: sensor.yourlibrary_na4_iiivega_com_1234_outstanding_fines
    name: Fines
  - entity: sensor.yourlibrary_na4_iiivega_com_1234_card_expires_in
    name: Card expires in
```

---

## Troubleshooting

**"Invalid library card number or PIN"** — verify your credentials at the portal URL. Some libraries use the full barcode number printed on the card.

**Home Assistant asks for a new PIN** — if the library rejects the saved PIN (for example after you change it), the integration stops checking your account and is flagged as needing attention under **Settings → Devices & Services**. Open it there and enter your current PIN.

**"Could not reach the library's servers"** — shown during setup when the library's servers can't be reached. Check your connection and the portal URL, then try again.

**Outstanding Fines shows `unknown`** — the library's fines request failed. The other sensors keep working, and a warning in the log says what went wrong.

**Sensors show `unavailable`** — check **Settings → System → Logs** for details. Enable debug logging in `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.vega_library: debug
```

**Portal URL not accepted** — the address must be in the form `yourlibrary.cluster.iiivega.com`. Make sure you're copying the URL from your library's catalog, not a library website URL.

---

## How it works

The integration authenticates against your library's [Keycloak](https://www.keycloak.org/) OIDC server (the same system the Vega web portal uses) and polls the Vega REST API every 30 minutes. All authentication is direct between your Home Assistant instance and the library's servers — no third-party services are involved.

It signs in with your card number and PIN, keeps the session token between polls, and renews it or signs in again when it expires. Your card number and PIN are stored in Home Assistant's own configuration storage and are only sent to your library's `iiivega.com` servers.

---

## Contributing

Issues and pull requests are welcome. If your library uses Vega but something doesn't work, please open an issue with your portal URL (you can redact the library-name prefix if preferred) and the relevant debug log lines.

Pull requests are checked automatically by HACS validation, hassfest and the test suite. To run the tests yourself you need Python 3.14:

```
pip install -r requirements_test.txt
pytest
```

The tests run against a local stand-in for the Vega servers, so no library account is needed.

---

## License

MIT © adbsmith
