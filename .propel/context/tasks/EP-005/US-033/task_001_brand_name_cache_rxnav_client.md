---
id: TASK-001
title: "Brand Name Redis Cache Layer + RxNav getDisplayTerms Client"
user_story: US-033
epic: EP-005
sprint: 2
layer: Backend
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-001]
---

# TASK-001: Brand Name Redis Cache Layer + RxNav `getDisplayTerms` Client

> **Story:** US-033 | **Epic:** EP-005 | **Sprint:** 2 | **Layer:** Backend | **Est:** 3 h  
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-033 AC Scenario 2 requires that every drug in the patient summary is presented using its brand name (e.g., `Furosemide (Lasix)`) with a plain-language description. The RxNav `getDisplayTerms` REST endpoint provides brand names for a given RxNorm CUI. Drug brand names rarely change, so the lookup result must be cached in Redis (Cloud Memorystore) with a **7-day TTL** to avoid redundant API calls across many patients.

Cache key pattern: `drug-brand:{rxcui}` — one key per drug, TTL = 604 800 s (7 days).

**Design references:**
- US-033 Technical Notes — Brand name lookup cache: Redis TTL=7 days
- US-033 AC Scenario 2 — `Furosemide (Lasix) — a water pill to reduce fluid buildup`
- design.md §4.1 — Drug Interaction DB: RxNav / OpenFDA API; Redis (Cloud Memorystore)

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| AC Scenario 2 | Brand name + plain description enriched from RxNav; cache prevents repeat lookups |

---

## Implementation Steps

### 1. Create module structure

```bash
mkdir -p backend/app/agents/medication_reconciliation/brand_name
touch backend/app/agents/medication_reconciliation/brand_name/__init__.py
touch backend/app/agents/medication_reconciliation/brand_name/cache.py
touch backend/app/agents/medication_reconciliation/brand_name/rxnav_client.py
```

### 2. Implement `backend/app/agents/medication_reconciliation/brand_name/cache.py`

```python
"""Redis cache wrapper for RxNav drug brand name lookups.

Uses a per-CUI key with a 7-day TTL because brand names are stable and do not
change frequently. Avoids redundant RxNav API calls across patient summaries.

Design refs:
    US-033 Technical Notes  — Redis TTL=7 days for brand name cache
    US-033 AC Scenario 2    — brand name enrichment for every medication
    design.md §4.1          — Redis (Cloud Memorystore) caching tier
"""
from __future__ import annotations

import json
import logging
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_KEY_PREFIX = "drug-brand"
_CACHE_TTL_SECONDS = 604_800  # 7 days


def _build_key(rxcui: str) -> str:
    """Build a Redis key for a drug brand name lookup.

    Args:
        rxcui: RxNorm CUI string.

    Returns:
        Cache key string, e.g. ``drug-brand:12345``.
    """
    return f"{_KEY_PREFIX}:{rxcui}"


class BrandNameCache:
    """Async cache wrapper for drug brand name results.

    Args:
        redis: An initialised ``redis.asyncio.Redis`` client.
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def get(self, rxcui: str) -> dict[str, Any] | None:
        """Return cached brand name payload for a CUI, or ``None`` on miss.

        Args:
            rxcui: RxNorm CUI string.

        Returns:
            Deserialized payload ``{"brand_name": str, "plain_description": str}``,
            or ``None`` on cache miss.
        """
        key = _build_key(rxcui)
        raw = await self._redis.get(key)
        if raw is None:
            logger.debug("Brand name cache miss: key=%s", key)
            return None
        logger.debug("Brand name cache hit: key=%s", key)
        return json.loads(raw)

    async def set(self, rxcui: str, data: dict[str, Any]) -> None:
        """Store brand name payload for a CUI with a 7-day TTL.

        Args:
            rxcui: RxNorm CUI string.
            data: Serialisable payload ``{"brand_name": str, "plain_description": str}``.
        """
        key = _build_key(rxcui)
        await self._redis.set(key, json.dumps(data), ex=_CACHE_TTL_SECONDS)
        logger.debug("Cached brand name: key=%s ttl=%ds", key, _CACHE_TTL_SECONDS)
```

### 3. Implement `backend/app/agents/medication_reconciliation/brand_name/rxnav_client.py`

```python
"""Async client for the RxNav getDisplayTerms endpoint.

Endpoint: GET https://rxnav.nlm.nih.gov/REST/rxcui/{rxcui}/property.json?propName=RxNorm%20Name

Also calls the brand name synonym endpoint:
    GET https://rxnav.nlm.nih.gov/REST/rxcui/{rxcui}/related.json?tty=BN

Design refs:
    US-033 Definition of Done — Drug brand name lookup: RxNav getDisplayTerms API
    US-033 AC Scenario 2      — Furosemide (Lasix) — a water pill to reduce fluid buildup
    design.md §4.1            — httpx async client stack
"""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

_RXNAV_BASE_URL = "https://rxnav.nlm.nih.gov/REST"
_REQUEST_TIMEOUT_SECONDS = 8.0


class RxNavBrandNameError(Exception):
    """Raised when the RxNav brand name lookup fails or returns no result."""


async def fetch_brand_name(rxcui: str) -> str | None:
    """Fetch the preferred brand name synonym for a given RxNorm CUI.

    Calls ``GET /rxcui/{rxcui}/related.json?tty=BN`` and returns the first
    brand-name concept found, or ``None`` if no brand is available (generics).

    Args:
        rxcui: RxNorm CUI string.

    Returns:
        Brand name string (e.g. ``"Lasix"``), or ``None``.

    Raises:
        RxNavBrandNameError: On HTTP error or unexpected response structure.
    """
    url = f"{_RXNAV_BASE_URL}/rxcui/{rxcui}/related.json"
    params = {"tty": "BN"}
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RxNavBrandNameError(
            f"RxNav brand name HTTP {exc.response.status_code} for rxcui={rxcui}"
        ) from exc
    except httpx.RequestError as exc:
        raise RxNavBrandNameError(
            f"RxNav brand name request failed for rxcui={rxcui}: {exc}"
        ) from exc

    data = response.json()
    concept_groups = (
        data.get("relatedGroup", {})
        .get("conceptGroup", [])
    )
    for group in concept_groups:
        for concept in group.get("conceptProperties", []):
            name = concept.get("name")
            if name:
                logger.debug("RxNav brand name resolved: rxcui=%s brand=%s", rxcui, name)
                return name

    logger.debug("No brand name found for rxcui=%s (generic drug)", rxcui)
    return None
```

### 4. Integrate cache + client in a facade `BrandNameEnricher`

Add `backend/app/agents/medication_reconciliation/brand_name/enricher.py`:

```python
"""Brand name enrichment facade — cache-aside pattern for RxNav lookups.

For each drug in the medication list, this enricher:
  1. Checks the Redis cache (TTL=7 days).
  2. On miss, calls RxNav getDisplayTerms.
  3. Stores result in cache.
  4. Returns ``{"brand_name": str | None, "plain_description": str}`` per drug.

Design refs:
    US-033 Technical Notes — brand name cache, Redis TTL=7 days
    US-033 AC Scenario 2   — "Furosemide (Lasix) — a water pill to reduce fluid buildup"
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.agents.medication_reconciliation.brand_name.cache import BrandNameCache
from app.agents.medication_reconciliation.brand_name.rxnav_client import (
    RxNavBrandNameError,
    fetch_brand_name,
)

logger = logging.getLogger(__name__)


@dataclass
class BrandNameResult:
    """Brand name enrichment result for a single drug.

    Attributes:
        rxcui: RxNorm CUI of the drug.
        generic_name: Generic drug name (input).
        brand_name: Brand name if found (e.g. ``"Lasix"``), else ``None``.
    """

    rxcui: str
    generic_name: str
    brand_name: str | None


class BrandNameEnricher:
    """Cache-aside brand name enrichment using RxNav.

    Args:
        cache: ``BrandNameCache`` instance backed by Redis.
    """

    def __init__(self, cache: BrandNameCache) -> None:
        self._cache = cache

    async def enrich(self, rxcui: str, generic_name: str) -> BrandNameResult:
        """Return brand name for a drug, using cache or RxNav.

        Args:
            rxcui: RxNorm CUI string.
            generic_name: Generic drug name (used as fallback display label).

        Returns:
            ``BrandNameResult`` with ``brand_name`` populated if available.
        """
        cached = await self._cache.get(rxcui)
        if cached is not None:
            return BrandNameResult(
                rxcui=rxcui,
                generic_name=generic_name,
                brand_name=cached.get("brand_name"),
            )

        brand_name: str | None = None
        try:
            brand_name = await fetch_brand_name(rxcui)
        except RxNavBrandNameError as exc:
            logger.warning("Brand name lookup failed for rxcui=%s: %s", rxcui, exc)

        await self._cache.set(rxcui, {"brand_name": brand_name})
        return BrandNameResult(rxcui=rxcui, generic_name=generic_name, brand_name=brand_name)
```

---

## File Checklist

| File | Action |
|------|--------|
| `backend/app/agents/medication_reconciliation/brand_name/__init__.py` | Create (empty) |
| `backend/app/agents/medication_reconciliation/brand_name/cache.py` | Create |
| `backend/app/agents/medication_reconciliation/brand_name/rxnav_client.py` | Create |
| `backend/app/agents/medication_reconciliation/brand_name/enricher.py` | Create |

---

## Validation

- [ ] `BrandNameCache.get()` returns `None` on cache miss; returns dict on hit
- [ ] `BrandNameCache.set()` stores JSON with TTL = 604 800 s (7 days)
- [ ] `fetch_brand_name()` returns first BN concept name from RxNav response
- [ ] `fetch_brand_name()` returns `None` gracefully for generic-only drugs (no BN group)
- [ ] `fetch_brand_name()` raises `RxNavBrandNameError` on HTTP 4xx / 5xx
- [ ] `BrandNameEnricher.enrich()` does NOT call RxNav when cache hit
- [ ] No PHI in cache keys or values (only RxCUI + brand name string)

---

## Definition of Done

- [ ] All four files created and peer-reviewed
- [ ] `get_redis` dependency factory from US-031 TASK-001 reused (no duplication)
- [ ] Unit tests written in TASK-006
- [ ] No secrets in code; RxNav is a public API — no auth key required
