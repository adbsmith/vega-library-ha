"""Fixtures for the Vega Library tests."""
from __future__ import annotations

from unittest.mock import PropertyMock, patch

import pytest
from aiohttp import web

from custom_components.vega_library.vega_client import LibraryConfig

from .common import FakeVega


@pytest.fixture
async def fake_vega(hass, socket_enabled):
    """Start the fake library server and point the integration's URLs at it."""
    fake = FakeVega()
    runner = web.AppRunner(fake.app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0).start()
    fake.base = f"http://127.0.0.1:{runner.addresses[0][1]}"

    def token_url(self: LibraryConfig) -> str:
        return f"{fake.base}/auth/realms/{self.library_prefix}/protocol/openid-connect/token"

    with (
        patch.object(LibraryConfig, "api_base", new_callable=PropertyMock, return_value=fake.base),
        patch.object(LibraryConfig, "keycloak_token_url", new=property(token_url)),
    ):
        yield fake
    await runner.cleanup()
