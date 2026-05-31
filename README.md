# Vega Library for Home Assistant

[![HACS Badge](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/adbsmith/vega-library-ha.svg)](https://github.com/adbsmith/vega-library-ha/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A Home Assistant custom integration for libraries using the **Innovative Interfaces Vega Discover** platform (iiivega.com). Track your checkouts, holds, fines, and card expiry — and automate reminders — directly from Home Assistant.

> **Is your library on Vega?** Check your library's online catalog. If the URL contains `.iiivega.com`, this integration works for you.

---

## Sensors

| Sensor | What it shows |
|---|---|
| **Checkouts** | Number of items checked out, sorted by due date. Attributes include title, format, due date, renewals remaining, and cover image URL. |
| **Holds** | Total hold requests. Attributes include status, queue position, pickup location. |
| **Holds Ready for Pickup** | Holds available to collect now — ideal for push notifications. |
| **Outstanding Fines** | Total fines in USD. Attributes include a per-item breakdown with title and description. |
| **Overdue Items** | Items past their due date, with days overdue per item. |
| **Items Due Soon** | Items due within 3 days — a gentler early reminder. |
| **Card Expires In** | Days until your library card expires. |

---

## Installation

### Via HACS (recommended)

1. Open HACS in Home Assistant
2. Search for **Vega Library**
3. Click **Download**
4. Restart Home Assistant

### Manual

1. Copy the `custom_components/vega_library` folder into your HA `config/custom_components/` directory
2. Restart Home Assistant

---

## Configuration

After installation, go to **Settings → Devices & Services → Add Integration → Vega Library**.

You need three things:

**Portal URL** — your library's Vega portal URL. Find it by going to your library's website and clicking the online catalog or "My Account" link. It will look like:
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
    trigger:
      - platform: numeric_state
        entity_id: sensor.library_holds_ready_for_pickup
        above: 0
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "📚 Library hold ready!"
          message: >
            {{ state_attr('sensor.library_holds_ready_for_pickup', 'ready_items')
               | map(attribute='title') | join(', ') }} is ready to collect.
```

### Reminder for items due within 3 days

```yaml
automation:
  - alias: "Library items due soon"
    trigger:
      - platform: time
        at: "09:00:00"
    condition:
      - condition: numeric_state
        entity_id: sensor.library_items_due_soon
        above: 0
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "📚 Library items due soon"
          message: >
            {% for item in state_attr('sensor.library_items_due_soon', 'due_soon_items') %}
              {{ item.title }} — due in {{ item.days_left }} day(s).
            {% endfor %}
```

### Library card expiry warning

```yaml
automation:
  - alias: "Library card expiry warning"
    trigger:
      - platform: numeric_state
        entity_id: sensor.library_card_expires_in
        below: 30
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "🪪 Library card expiring"
          message: >
            Your library card expires in
            {{ states('sensor.library_card_expires_in') }} days.
            Renew at the library or online.
```

---

## Lovelace card

```yaml
type: entities
title: Library
entities:
  - entity: sensor.library_checkouts
    name: Checked out
  - entity: sensor.library_holds
    name: Holds
  - entity: sensor.library_holds_ready_for_pickup
    name: Ready to collect
  - entity: sensor.library_overdue_items
    name: Overdue
  - entity: sensor.library_outstanding_fines
    name: Fines
  - entity: sensor.library_card_expires_in
    name: Card expires in
```

---

## Troubleshooting

**"Invalid library card number or PIN"** — verify your credentials at the portal URL. Some libraries use the full barcode number printed on the card.

**Sensors show `unavailable`** — check **Settings → System → Logs** for details. Enable debug logging in `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.vega_library: debug
```

**Portal URL not accepted** — the URL must be in the form `https://yourlibrary.cluster.iiivega.com`. Make sure you're copying the URL from your library's catalog, not a library website URL.

---

## How it works

The integration authenticates against your library's [Keycloak](https://www.keycloak.org/) OIDC server (the same system the Vega web portal uses) and polls the Vega REST API every 30 minutes. All authentication is direct between your Home Assistant instance and the library's servers — no third-party services are involved.

Tokens are silently refreshed every 10 minutes without re-entering credentials.

---

## Contributing

Issues and pull requests are welcome. If your library uses Vega but something doesn't work, please open an issue with your portal URL (you can redact the library-name prefix if preferred) and the relevant debug log lines.

---

## License

MIT © adbsmith
