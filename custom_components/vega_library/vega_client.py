"""
Async client for any Innovative Interfaces Vega Discover library portal.

All Vega libraries share:
  - Keycloak OIDC auth (client_id = "convergence")
  - API base at https://{cluster}.iiivega.com
  - The same endpoint paths and response field names
  - Required headers: iii-customer-domain, iii-host-domain, api-version

Only three things vary per library, all derivable from the portal URL:
  library_prefix   e.g. "ypsilantidl"   → Keycloak realm name
  cluster          e.g. "na4"            → determines api_base and auth_base
  library_domain   e.g. "ypsilantidl.na4.iiivega.com"

Usage:
  config = LibraryConfig.from_portal_url("https://ypsilantidl.na4.iiivega.com/portal")
  async with VegaClient(config, barcode="2710…", pin="1234") as client:
      account = await client.get_account()
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import aiohttp

_LOGGER = logging.getLogger(__name__)

KEYCLOAK_CLIENT_ID = "convergence"
DEFAULT_TIMEOUT    = aiohttp.ClientTimeout(total=30)

# API endpoint paths — identical on every Vega instance
_ENDPOINT_CHECKOUTS = "/api/search-result/patrons/me/checkouts"
_ENDPOINT_HOLDS     = "/api/search-result/patrons/me/holds"
_ENDPOINT_FINES     = "/api/search-result/gates/patrons/me/fines"
_ENDPOINT_PATRON    = "/api/search-result/patrons/me"
_ENDPOINT_RENEW     = "/api/search-result/patrons/me/checkouts/{id}/renew"
_ENDPOINT_CANCEL    = "/api/search-result/patrons/me/holds/{id}"


# ── Library config ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LibraryConfig:
    """All library-specific coordinates, derived from the portal URL."""

    library_domain: str   # "ypsilantidl.na4.iiivega.com"
    library_prefix: str   # "ypsilantidl"  (= Keycloak realm)
    cluster: str          # "na4"

    @property
    def portal_origin(self) -> str:
        return f"https://{self.library_domain}"

    @property
    def api_base(self) -> str:
        return f"https://{self.cluster}.iiivega.com"

    @property
    def keycloak_token_url(self) -> str:
        return (
            f"https://auth.{self.cluster}.iiivega.com"
            f"/auth/realms/{self.library_prefix}"
            "/protocol/openid-connect/token"
        )

    @property
    def display_name(self) -> str:
        """Human-readable name for HA device registry."""
        return self.library_domain

    @classmethod
    def from_portal_url(cls, url: str) -> "LibraryConfig":
        """
        Parse a Vega portal URL into a LibraryConfig.

        Accepts any of:
          https://ypsilantidl.na4.iiivega.com/portal
          https://ypsilantidl.na4.iiivega.com
          http://ferg.na.iiivega.com/portal
        """
        parsed   = urlparse(url.strip())
        host     = parsed.hostname or ""   # "ypsilantidl.na4.iiivega.com"
        parts    = host.split(".")
        # parts = ["ypsilantidl", "na4", "iiivega", "com"]
        if len(parts) < 4 or parts[-2] != "iiivega" or parts[-1] != "com":
            raise ValueError(
                f"Not a valid Vega portal URL: {url!r}. "
                "Expected format: https://<library>.<cluster>.iiivega.com/portal"
            )
        return cls(
            library_domain=host,
            library_prefix=parts[0],
            cluster=parts[1],
        )

    @staticmethod
    def is_valid_portal_url(url: str) -> bool:
        try:
            LibraryConfig.from_portal_url(url)
            return True
        except (ValueError, Exception):
            return False


# ── Exceptions ────────────────────────────────────────────────────────────────

class VegaAuthError(Exception):
    """Bad credentials or Keycloak rejected the login."""

class VegaAPIError(Exception):
    """Unexpected non-auth API error."""


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class LibraryCheckout:
    id: str
    title: str
    due_date: datetime | None
    checkout_date: datetime | None
    renewable: bool
    times_renewed: int
    renewal_limit: int
    format: str
    cover_url: str | None
    raw: dict = field(default_factory=dict)

    @property
    def renewals_remaining(self) -> int:
        return max(0, self.renewal_limit - self.times_renewed)

    @staticmethod
    def _parse_dt(val: Any) -> datetime | None:
        if not val:
            return None
        try:
            return datetime.fromisoformat(str(val).replace("Z", "+00:00"))
        except ValueError:
            return None

    @classmethod
    def from_api(cls, data: dict) -> "LibraryCheckout":
        resource      = data.get("resource") or {}
        renewal_count = int(data.get("renewalCount") or 0)
        renewal_limit = int(data.get("renewalLimit") or 999)
        return cls(
            id=str(data.get("id") or ""),
            title=resource.get("title") or data.get("title") or "Unknown",
            due_date=cls._parse_dt(data.get("dueDate")),
            checkout_date=cls._parse_dt(data.get("checkOutDate")),
            renewable=renewal_count < renewal_limit,
            times_renewed=renewal_count,
            renewal_limit=renewal_limit,
            format=resource.get("materialType") or "",
            cover_url=(resource.get("coverUrl") or {}).get("medium"),
            raw=data,
        )


@dataclass
class LibraryHold:
    id: str
    title: str
    status: str
    queue_position: int | None
    pickup_location: str
    expiry_date: datetime | None
    placed_date: datetime | None
    format: str
    cover_url: str | None
    raw: dict = field(default_factory=dict)

    @property
    def is_ready(self) -> bool:
        return self.status.upper() in (
            "READY", "READY_FOR_PICKUP", "ON_SHELF", "AVAILABLE",
            "HELD", "READYFORPICKUP",
        )

    @staticmethod
    def _parse_dt(val: Any) -> datetime | None:
        if not val:
            return None
        try:
            return datetime.fromisoformat(str(val).replace("Z", "+00:00"))
        except ValueError:
            return None

    @classmethod
    def from_api(cls, data: dict) -> "LibraryHold":
        resource = data.get("resource") or {}
        return cls(
            id=str(data.get("id") or data.get("holdId") or ""),
            title=resource.get("title") or data.get("title") or "Unknown",
            status=str(data.get("status") or "UNKNOWN").upper(),
            queue_position=data.get("queuePosition") or data.get("position"),
            pickup_location=str(data.get("pickupLocation") or data.get("pickupBranch") or ""),
            expiry_date=cls._parse_dt(data.get("expiryDate") or data.get("expireDate")),
            placed_date=cls._parse_dt(data.get("placedDate") or data.get("createDate")),
            format=resource.get("materialType") or "",
            cover_url=(resource.get("coverUrl") or {}).get("medium"),
            raw=data,
        )


@dataclass
class LibraryFine:
    id: str
    title: str
    description: str
    fine_type: str
    amount: float
    format: str
    creation_date: str
    cover_url: str | None

    @classmethod
    def from_api(cls, data: dict) -> "LibraryFine":
        resource = data.get("resource") or {}
        return cls(
            id=str(data.get("id") or ""),
            title=resource.get("title") or "Unknown",
            description=str(data.get("description") or ""),
            fine_type=str(data.get("type") or ""),
            amount=float(data.get("outstandingAmount") or 0.0),
            format=resource.get("materialType") or "",
            creation_date=str(data.get("creationDate") or ""),
            cover_url=(resource.get("coverUrl") or {}).get("medium"),
        )


@dataclass
class PatronAccount:
    checkouts: list[LibraryCheckout]  = field(default_factory=list)
    holds: list[LibraryHold]          = field(default_factory=list)
    fines: list[LibraryFine]          = field(default_factory=list)
    fines_total: float                = 0.0
    card_expiration_date: date | None = None

    @property
    def holds_ready(self) -> list[LibraryHold]:
        return [h for h in self.holds if h.is_ready]

    @property
    def overdue_checkouts(self) -> list[LibraryCheckout]:
        now = datetime.now().astimezone()
        return [c for c in self.checkouts if c.due_date and c.due_date < now]

    @property
    def due_soon(self) -> list[LibraryCheckout]:
        now  = datetime.now().astimezone()
        soon = now + timedelta(days=3)
        return [c for c in self.checkouts if c.due_date and now <= c.due_date <= soon]

    @property
    def card_days_until_expiry(self) -> int | None:
        if self.card_expiration_date is None:
            return None
        return (self.card_expiration_date - date.today()).days


# ── Keycloak token cache ──────────────────────────────────────────────────────

@dataclass
class _TokenCache:
    access_token: str
    refresh_token: str
    expires_at: float
    refresh_expires_at: float

    def access_valid(self, margin: int = 60) -> bool:
        return time.time() < (self.expires_at - margin)

    def refresh_valid(self, margin: int = 60) -> bool:
        return time.time() < (self.refresh_expires_at - margin)


# ── Main client ───────────────────────────────────────────────────────────────

class VegaClient:
    """Async Keycloak + Vega API client, works with any Vega library."""

    def __init__(self, config: LibraryConfig, barcode: str, pin: str) -> None:
        self._config  = config
        self._barcode = barcode
        self._pin     = pin
        self._cache: _TokenCache | None = None
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "VegaClient":
        self._session = aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT)
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._session:
            await self._session.close()

    def _headers(self, api_version: str = "1", token: str | None = None) -> dict[str, str]:
        h: dict[str, str] = {
            "iii-customer-domain": self._config.library_domain,
            "iii-host-domain":     self._config.library_domain,
            "api-version":         api_version,
            "Origin":              self._config.portal_origin,
            "Referer":             self._config.portal_origin + "/",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
            ),
            "Accept":          "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if token:
            h["Authorization"] = f"Bearer {token}"
        return h

    # ── Auth ──────────────────────────────────────────────────────────────────

    async def authenticate(self) -> None:
        assert self._session is not None
        _LOGGER.debug("Keycloak auth (%s)…", self._config.keycloak_token_url)
        form = aiohttp.FormData()
        form.add_field("grant_type", "password")
        form.add_field("client_id",  KEYCLOAK_CLIENT_ID)
        form.add_field("username",   self._barcode)
        form.add_field("password",   self._pin)
        async with self._session.post(
            self._config.keycloak_token_url, data=form,
            headers={"Origin": self._config.portal_origin,
                     "Referer": self._config.portal_origin + "/",
                     "Accept": "application/json"},
        ) as resp:
            body = await resp.json(content_type=None)
            if resp.status == 401:
                raise VegaAuthError("Invalid library card number or PIN")
            if resp.status != 200:
                raise VegaAPIError(f"Keycloak HTTP {resp.status}: {body}")
            now = time.time()
            self._cache = _TokenCache(
                access_token=body["access_token"],
                refresh_token=body.get("refresh_token", ""),
                expires_at=now + int(body.get("expires_in", 600)),
                refresh_expires_at=now + int(body.get("refresh_expires_in", 1800)),
            )

    async def _refresh(self) -> None:
        assert self._session is not None and self._cache is not None
        form = aiohttp.FormData()
        form.add_field("grant_type",    "refresh_token")
        form.add_field("client_id",     KEYCLOAK_CLIENT_ID)
        form.add_field("refresh_token", self._cache.refresh_token)
        async with self._session.post(self._config.keycloak_token_url, data=form) as resp:
            if resp.status != 200:
                self._cache = None
                await self.authenticate()
                return
            body = await resp.json(content_type=None)
            now = time.time()
            self._cache = _TokenCache(
                access_token=body["access_token"],
                refresh_token=body.get("refresh_token", self._cache.refresh_token),
                expires_at=now + int(body.get("expires_in", 600)),
                refresh_expires_at=now + int(body.get("refresh_expires_in", 1800)),
            )

    async def _token(self) -> str:
        if self._cache is None:
            await self.authenticate()
        elif not self._cache.access_valid():
            if self._cache.refresh_valid():
                await self._refresh()
            else:
                await self.authenticate()
        return self._cache.access_token  # type: ignore[union-attr]

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    async def _get(self, path: str, params: dict | None = None,
                   api_version: str = "1") -> Any:
        assert self._session is not None
        tok = await self._token()
        h   = self._headers(api_version, tok)
        url = self._config.api_base + path
        async with self._session.get(url, headers=h, params=params) as resp:
            if resp.status == 401:
                self._cache = None
                h["Authorization"] = f"Bearer {await self._token()}"
                async with self._session.get(url, headers=h, params=params) as r2:
                    r2.raise_for_status()
                    return await r2.json(content_type=None)
            resp.raise_for_status()
            return await resp.json(content_type=None)

    async def _post(self, path: str, json_body: dict | None = None) -> tuple[int, Any]:
        assert self._session is not None
        tok = await self._token()
        h   = {**self._headers("1", tok), "content-type": "application/json"}
        async with self._session.post(
            self._config.api_base + path, json=json_body or {}, headers=h
        ) as resp:
            body = await resp.json(content_type=None) if resp.content_length else {}
            return resp.status, body

    async def _delete(self, path: str) -> int:
        assert self._session is not None
        h = self._headers("1", await self._token())
        async with self._session.delete(self._config.api_base + path, headers=h) as resp:
            return resp.status

    # ── Patron data ───────────────────────────────────────────────────────────

    async def get_checkouts(self) -> list[LibraryCheckout]:
        raw   = await self._get(_ENDPOINT_CHECKOUTS)
        items = raw if isinstance(raw, list) else (
            raw.get("checkouts") or raw.get("items") or raw.get("data") or []
        )
        return [LibraryCheckout.from_api(i) for i in items]

    async def get_holds(self) -> list[LibraryHold]:
        raw   = await self._get(_ENDPOINT_HOLDS, params={"placedHoldIds": ""})
        items = raw if isinstance(raw, list) else (
            raw.get("holds") or raw.get("items") or raw.get("data") or []
        )
        return [LibraryHold.from_api(i) for i in items]

    async def get_fines(self) -> tuple[float, list[LibraryFine]]:
        try:
            raw   = await self._get(_ENDPOINT_FINES)
            total = float(raw.get("totalOutstandingAmount") or 0.0)
            items = [LibraryFine.from_api(f) for f in (raw.get("data") or [])]
            return total, items
        except Exception:
            _LOGGER.debug("Fines fetch failed", exc_info=True)
            return 0.0, []

    async def get_patron_profile(self) -> dict:
        try:
            return await self._get(
                _ENDPOINT_PATRON,
                params={"listsPrefetch": "10", "showcasesPrefetch": "10"},
                api_version="2",
            )
        except Exception:
            _LOGGER.debug("Patron profile fetch failed", exc_info=True)
            return {}

    async def get_account(self) -> PatronAccount:
        checkouts             = await self.get_checkouts()
        holds                 = await self.get_holds()
        fines_total, fines    = await self.get_fines()
        profile               = await self.get_patron_profile()

        expiry_date: date | None = None
        if exp_str := profile.get("expirationDate"):
            try:
                expiry_date = date.fromisoformat(exp_str)
            except ValueError:
                pass

        return PatronAccount(
            checkouts=checkouts, holds=holds,
            fines=fines, fines_total=fines_total,
            card_expiration_date=expiry_date,
        )

    # ── Actions ───────────────────────────────────────────────────────────────

    async def renew_checkout(self, checkout_id: str) -> bool:
        status, _ = await self._post(_ENDPOINT_RENEW.format(id=checkout_id))
        return status in (200, 204)

    async def cancel_hold(self, hold_id: str) -> bool:
        status = await self._delete(_ENDPOINT_CANCEL.format(id=hold_id))
        return status in (200, 204)
