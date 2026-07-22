"""Unit tests for app/core/auth/oidc.py — OIDC discovery and JWKS caching."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.auth.oidc import _JWKS_CACHE, _CACHE_KEY, fetch_jwks, get_jwks_uri

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_JWKS = {
    "keys": [
        {
            "kty": "RSA",
            "kid": "key-1",
            "use": "sig",
            "n": "sampleN",
            "e": "AQAB",
        }
    ]
}

SAMPLE_DISCOVERY = {
    "issuer": "https://idp.hospital.example.com",
    "jwks_uri": "https://idp.hospital.example.com/.well-known/jwks.json",
}


@pytest.fixture(autouse=True)
def clear_jwks_cache():
    """Clear the module-level JWKS cache before every test."""
    _JWKS_CACHE.clear()
    yield
    _JWKS_CACHE.clear()


@pytest.fixture
def idp_env(monkeypatch):
    """Set IDP_BASE_URL for tests that require it."""
    monkeypatch.setenv("IDP_BASE_URL", "https://idp.hospital.example.com")


# ---------------------------------------------------------------------------
# get_jwks_uri() tests
# ---------------------------------------------------------------------------

class TestGetJwksUri:
    def test_raises_when_idp_base_url_unset(self, monkeypatch):
        """IDP_BASE_URL missing → RuntimeError with helpful message."""
        monkeypatch.delenv("IDP_BASE_URL", raising=False)
        with pytest.raises(RuntimeError, match="IDP_BASE_URL"):
            get_jwks_uri()

    def test_returns_jwks_uri_from_discovery_document(self, idp_env):
        """Parses jwks_uri from the OIDC discovery JSON response."""
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_DISCOVERY
        mock_response.raise_for_status = MagicMock()

        with patch("app.core.auth.oidc.httpx.get", return_value=mock_response):
            uri = get_jwks_uri()

        assert uri == "https://idp.hospital.example.com/.well-known/jwks.json"

    def test_raises_on_missing_jwks_uri_key(self, idp_env):
        """Discovery document without 'jwks_uri' → RuntimeError."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"issuer": "https://idp.hospital.example.com"}
        mock_response.raise_for_status = MagicMock()

        with patch("app.core.auth.oidc.httpx.get", return_value=mock_response):
            with pytest.raises(RuntimeError, match="jwks_uri"):
                get_jwks_uri()


# ---------------------------------------------------------------------------
# fetch_jwks() tests — cache behaviour (AC Scenario 3)
# ---------------------------------------------------------------------------

class TestFetchJwks:
    @pytest.mark.asyncio
    async def test_jwks_cache_miss_fetches_from_network(self, idp_env):
        """On cache miss: fetches JWKS from network and stores in cache."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_JWKS
        mock_response.raise_for_status = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("app.core.auth.oidc.get_jwks_uri", return_value="https://idp/jwks.json"), \
             patch("app.core.auth.oidc.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_jwks()

        assert result == SAMPLE_JWKS
        # Verify cache was populated
        assert _JWKS_CACHE.get(_CACHE_KEY) == SAMPLE_JWKS

    @pytest.mark.asyncio
    async def test_jwks_cache_hit_skips_network(self, idp_env):
        """On cache hit: returns cached JWKS without any network call."""
        # Pre-populate cache
        _JWKS_CACHE[_CACHE_KEY] = SAMPLE_JWKS

        with patch("app.core.auth.oidc.get_jwks_uri") as mock_discovery, \
             patch("app.core.auth.oidc.httpx.AsyncClient") as mock_client:
            result = await fetch_jwks()

        # Confirm no network calls were made
        mock_discovery.assert_not_called()
        mock_client.assert_not_called()
        assert result == SAMPLE_JWKS

    @pytest.mark.asyncio
    async def test_jwks_cache_is_not_fetched_per_request(self, idp_env):
        """Multiple calls within TTL window should only fetch JWKS once."""
        # Pre-populate cache to simulate cached state
        _JWKS_CACHE[_CACHE_KEY] = SAMPLE_JWKS

        with patch("app.core.auth.oidc.get_jwks_uri") as mock_discovery:
            await fetch_jwks()
            await fetch_jwks()

        # Discovery should not be called at all since cache has the entry
        mock_discovery.assert_not_called()
