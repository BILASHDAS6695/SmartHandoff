---
id: TASK-002
title: "Implement OIDC Discovery Fetch and JWKS Caching in `app/core/auth/oidc.py`"
user_story: US-056
epic: EP-011
sprint: 1
layer: Backend
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-056/TASK-001]
---

# TASK-002: Implement OIDC Discovery Fetch and JWKS Caching in `app/core/auth/oidc.py`

> **Story:** US-056 | **Epic:** EP-011 | **Sprint:** 1 | **Layer:** Backend | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

AIR-030 specifies: *"FastAPI backend fetches OIDC discovery document at startup; JWKS endpoint cached with 1-hour TTL for JWT verification."*

The Technical Notes in US-056 prescribe the exact caching implementation: `module-level TTLCache(maxsize=1, ttl=3600) from cachetools`. This task implements the full `app/core/auth/oidc.py` module replacing the TASK-001 stubs.

The JWKS is fetched lazily (not at import time) so that the service can start without an IdP connection and the `IDP_BASE_URL` environment variable is resolved at call time. This is important for Cloud Run cold starts where the IdP may not yet be reachable during container initialisation.

AC Scenario 3 specifically tests that the JWKS is **not** fetched on every request — this is the core behaviour enforced by `TTLCache`.

---

## Acceptance Criteria Addressed

| US-056 AC | Requirement |
|---|---|
| **Scenario 3** | JWKS cache returns cached JWKS if last refreshed <1h ago; fresh fetch otherwise; never fetched per-request |
| **DoD** | FastAPI OIDC middleware: JWKS cache (1h TTL) |

---

## Implementation Steps

### 1. Implement `backend/app/core/auth/oidc.py`

Replace the TASK-001 stub entirely with the following implementation:

```python
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
```

### 2. Expose `_JWKS_CACHE` for Test Injection

Tests (TASK-007) need to clear or inspect the cache. Add this to `app/core/auth/__init__.py` so tests can access it without reaching into private internals:

```python
# Exported for testing only — do not use in production code
from app.core.auth.oidc import _JWKS_CACHE as _oidc_jwks_cache  # noqa: F401
```

> **Note:** This is intentionally a test-only escape hatch. In production code, always call `fetch_jwks()`.

### 3. Add `IDP_BASE_URL` to Cloud Run Environment Variable Spec

The Cloud Run `api-gateway` service must have `IDP_BASE_URL` injected at deploy time. This is a non-sensitive configuration value (it is a public OIDC issuer URL, not a secret) so it is set as a plain environment variable, not via Secret Manager.

In `infra/terraform/modules/cloud_run/variables.tf`, confirm or add:

```hcl
variable "env_vars" {
  type        = map(string)
  description = "Non-sensitive environment variables to inject into the Cloud Run service"
  default     = {}
}
```

In `infra/terraform/environments/dev/main.tf`, the `api-gateway` Cloud Run service call should pass:

```hcl
module "api_gateway" {
  # ... existing args ...
  env_vars = {
    IDP_BASE_URL = var.idp_base_url
  }
}
```

Add `idp_base_url` to `infra/terraform/environments/dev/variables.tf`:

```hcl
variable "idp_base_url" {
  type        = string
  description = "Base URL of the hospital identity provider (OIDC issuer)"
}
```

And to `infra/terraform/environments/dev/terraform.tfvars.example`:

```
idp_base_url = "https://idp.hospital.example.com"
```

Repeat the same pattern for `staging` and `prod` environment directories.

---

## Validation

```bash
cd backend

# 1. Confirm imports resolve
python -c "from app.core.auth.oidc import fetch_jwks, get_jwks_uri, _JWKS_CACHE; print('OK')"

# 2. Confirm TTLCache is configured correctly
python -c "
from app.core.auth.oidc import _JWKS_CACHE
assert _JWKS_CACHE.maxsize == 1, 'maxsize must be 1'
assert _JWKS_CACHE.ttl == 3600, 'ttl must be 3600'
print('JWKS cache config OK')
"

# 3. Confirm IDP_BASE_URL error is raised when unset
python -c "
import os; os.environ.pop('IDP_BASE_URL', None)
from app.core.auth.oidc import get_jwks_uri
try:
    get_jwks_uri()
    assert False, 'Should have raised'
except RuntimeError as e:
    assert 'IDP_BASE_URL' in str(e)
    print('IDP_BASE_URL guard OK')
"
```

All three commands must exit with code 0.

---

## Files Touched

| File | Action |
|---|---|
| `backend/app/core/auth/oidc.py` | Replace TASK-001 stub with full implementation |
| `backend/app/core/auth/__init__.py` | Add `_oidc_jwks_cache` re-export for test access |
| `infra/terraform/modules/cloud_run/variables.tf` | Confirm/add `env_vars` variable |
| `infra/terraform/environments/dev/main.tf` | Add `idp_base_url` to `api-gateway` env_vars |
| `infra/terraform/environments/dev/variables.tf` | Add `idp_base_url` variable |
| `infra/terraform/environments/dev/terraform.tfvars.example` | Add `idp_base_url` example |
| `infra/terraform/environments/staging/main.tf` | Same as dev |
| `infra/terraform/environments/staging/variables.tf` | Same as dev |
| `infra/terraform/environments/staging/terraform.tfvars.example` | Same as dev |
| `infra/terraform/environments/prod/main.tf` | Same as dev |
| `infra/terraform/environments/prod/variables.tf` | Same as dev |
| `infra/terraform/environments/prod/terraform.tfvars.example` | Same as dev |

---

## Definition of Done Checklist

- [ ] `app/core/auth/oidc.py` fully implemented (not a stub)
- [ ] `_JWKS_CACHE` is `TTLCache(maxsize=1, ttl=3600)` — verified by validation step 2
- [ ] `IDP_BASE_URL` missing raises `RuntimeError` — verified by validation step 3
- [ ] `fetch_jwks()` is async; `get_jwks_uri()` is synchronous (for simplicity)
- [ ] TLS verification enabled (`verify=True`) on all outbound httpx calls
- [ ] `idp_base_url` Terraform variable added to all three environments
- [ ] No `IDP_BASE_URL` value hardcoded in any source or Terraform file

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| US-056/TASK-001 | Upstream task | `cachetools` and `authlib` must be installed |
