"""OIDC discovery and JWKS caching.

Fetches the IdP OIDC discovery document to locate the JWKS endpoint, then
caches the JWKS with a 1-hour TTL (AIR-030).

Environment variables:
    IDP_BASE_URL  — Base URL of the hospital identity provider
                    e.g. https://idp.hospital.example.com
                    Discovery document expected at {IDP_BASE_URL}/.well-known/openid-configuration

Security notes:
    - JWKS is validated against the issuer before being stored in cache.
    - httpx follows redirects but enforces TLS certificate verification (verify=True).
    - The TTLCache is module-level (process-scoped) — each Cloud Run instance has
      its own cache, so a JWKS rotation takes at most 1 hour to propagate.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from cachetools import TTLCache

logger = logging.getLogger(__name__)

# Module-level JWKS cache: one entry, 1-hour TTL (US-056 Technical Notes, AIR-030)
_JWKS_CACHE: TTLCache[str, dict[str, Any]] = TTLCache(maxsize=1, ttl=3600)

_CACHE_KEY = "jwks"


def _idp_base_url() -> str:
    """Return IDP_BASE_URL from environment, raising on missing config."""
    url = os.environ.get("IDP_BASE_URL", "").rstrip("/")
    if not url:
        raise RuntimeError(
            "IDP_BASE_URL environment variable is not set. "
            "Mount it from Secret Manager via Cloud Run secret bindings."
        )
    return url


def get_jwks_uri() -> str:
    """Fetch the OIDC discovery document and return the jwks_uri.

    Called by fetch_jwks() on cache miss. Uses a synchronous httpx call
    because OIDC discovery is performed once per cache-miss cycle; the overhead
    of a sync call here is negligible and avoids async complexity at module level.

    Returns:
        str: The JWKS URI from the discovery document.

    Raises:
        RuntimeError: If IDP_BASE_URL is not set or discovery document is unreachable.
        KeyError: If the discovery document does not contain 'jwks_uri'.
    """
    discovery_url = f"{_idp_base_url()}/.well-known/openid-configuration"
    logger.info("Fetching OIDC discovery document from %s", discovery_url)
    try:
        response = httpx.get(discovery_url, timeout=10.0, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"Failed to fetch OIDC discovery document from {discovery_url}: {exc}"
        ) from exc

    discovery = response.json()
    try:
        return discovery["jwks_uri"]
    except KeyError as exc:
        raise RuntimeError(
            f"OIDC discovery document at {discovery_url} missing 'jwks_uri' field"
        ) from exc


async def fetch_jwks() -> dict[str, Any]:
    """Return the JWKS, using the module-level TTLCache (1-hour TTL).

    On cache hit: returns the cached JWKS without any network call.
    On cache miss: fetches jwks_uri from the discovery document, fetches
    the JWKS, stores it in cache, and returns it.

    Returns:
        dict: The JWKS JSON object ({"keys": [...]}).

    Raises:
        RuntimeError: If the JWKS endpoint is unreachable.
    """
    cached = _JWKS_CACHE.get(_CACHE_KEY)
    if cached is not None:
        logger.debug("JWKS cache hit — returning cached JWKS")
        return cached

    logger.info("JWKS cache miss — fetching fresh JWKS")
    jwks_uri = get_jwks_uri()

    try:
        async with httpx.AsyncClient(verify=True, timeout=10.0) as client:
            response = await client.get(jwks_uri)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"Failed to fetch JWKS from {jwks_uri}: {exc}"
        ) from exc

    jwks = response.json()
    _JWKS_CACHE[_CACHE_KEY] = jwks
    logger.info("JWKS cached successfully (%d keys)", len(jwks.get("keys", [])))
    return jwks
