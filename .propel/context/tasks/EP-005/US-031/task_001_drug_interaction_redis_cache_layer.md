---
id: TASK-001
title: "Drug Interaction Redis Cache Layer — Key Design and Client Wrapper"
user_story: US-031
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

# TASK-001: Drug Interaction Redis Cache Layer — Key Design and Client Wrapper

> **Story:** US-031 | **Epic:** EP-005 | **Sprint:** 2 | **Layer:** Backend | **Est:** 3 h  
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-031 requires all RxNav drug-interaction lookup results to be cached in Redis (Cloud Memorystore) with a 24-hour TTL to eliminate redundant API calls for the same drug pair. Redis is provisioned by US-001. The cache key must use a **sorted CUI pair** (`min(cui1,cui2):max(cui1,cui2)`) so that reversed pair order produces an identical key.

**Design references:**
- design.md §4.1 — Redis (Cloud Memorystore) as caching tier
- US-031 Technical Notes — Redis key: `drug-interaction:{sorted_pair}`, TTL=86400
- US-031 AC Scenario 2 — Cache hit must suppress RxNav API call

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| AC Scenario 2 | Cache hit returns stored result; no RxNav API call is made |

---

## Implementation Steps

### 1. Create module structure

```bash
mkdir -p backend/app/agents/medication_reconciliation/drug_interaction
touch backend/app/agents/medication_reconciliation/drug_interaction/__init__.py
touch backend/app/agents/medication_reconciliation/drug_interaction/cache.py
```

### 2. Implement `backend/app/agents/medication_reconciliation/drug_interaction/cache.py`

```python
"""Redis cache wrapper for drug-drug interaction lookup results.

Implements sorted CUI-pair key to guarantee cache-key symmetry regardless of
the order in which a drug pair is presented.

Design refs:
    US-031 AC Scenario 2 — Cache hit suppresses RxNav API call
    US-031 Technical Notes — key: drug-interaction:{min_cui}:{max_cui}, TTL=86400
    design.md §4.1        — Redis (Cloud Memorystore)
"""
from __future__ import annotations

import json
import logging
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 86_400  # 24 hours
_KEY_PREFIX = "drug-interaction"


def _build_cache_key(rxcui1: str, rxcui2: str) -> str:
    """Build a deterministic cache key from two RxCUIs.

    The key is order-independent: (A, B) and (B, A) yield the same key.

    Args:
        rxcui1: First RxNorm CUI string.
        rxcui2: Second RxNorm CUI string.

    Returns:
        Cache key string, e.g. ``drug-interaction:123:456``.
    """
    low, high = (rxcui1, rxcui2) if rxcui1 < rxcui2 else (rxcui2, rxcui1)
    return f"{_KEY_PREFIX}:{low}:{high}"


class DrugInteractionCache:
    """Thin async cache wrapper around a Redis connection.

    Args:
        redis: An initialised ``redis.asyncio.Redis`` client.
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def get(self, rxcui1: str, rxcui2: str) -> dict[str, Any] | None:
        """Return cached interaction data for a CUI pair, or ``None`` on miss.

        Args:
            rxcui1: First RxNorm CUI.
            rxcui2: Second RxNorm CUI.

        Returns:
            Deserialized interaction payload, or ``None`` if not cached.
        """
        key = _build_cache_key(rxcui1, rxcui2)
        raw = await self._redis.get(key)
        if raw is None:
            logger.debug("Cache miss for key=%s", key)
            return None
        logger.debug("Cache hit for key=%s", key)
        return json.loads(raw)

    async def set(
        self,
        rxcui1: str,
        rxcui2: str,
        data: dict[str, Any],
    ) -> None:
        """Store interaction data for a CUI pair with a 24-hour TTL.

        Args:
            rxcui1: First RxNorm CUI.
            rxcui2: Second RxNorm CUI.
            data: Serialisable interaction payload to cache.
        """
        key = _build_cache_key(rxcui1, rxcui2)
        await self._redis.set(key, json.dumps(data), ex=_CACHE_TTL_SECONDS)
        logger.debug("Cached interaction result key=%s ttl=%ds", key, _CACHE_TTL_SECONDS)
```

### 3. Register Redis dependency in `backend/app/core/dependencies.py`

Add (or update) the Redis async client factory:

```python
from redis.asyncio import Redis, from_url
from app.core.config import settings

_redis_client: Redis | None = None


async def get_redis() -> Redis:
    """FastAPI dependency — returns the shared async Redis client."""
    global _redis_client
    if _redis_client is None:
        _redis_client = from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client
```

---

## File Checklist

| File | Action |
|------|--------|
| `backend/app/agents/medication_reconciliation/drug_interaction/__init__.py` | Create (empty) |
| `backend/app/agents/medication_reconciliation/drug_interaction/cache.py` | Create |
| `backend/app/core/dependencies.py` | Update — add `get_redis` factory |

---

## Validation

- [ ] `_build_cache_key("789", "123")` == `_build_cache_key("123", "789")` (order-independent)
- [ ] `DrugInteractionCache.get()` returns `None` on cache miss
- [ ] `DrugInteractionCache.set()` stores JSON-serialised payload with TTL=86400
- [ ] `get_redis()` resolves to a single shared instance (no reconnect per request)
- [ ] No PHI stored in cache keys or values (only RxCUIs + interaction metadata)

---

## Definition of Done

- [ ] `cache.py` implemented and peer-reviewed
- [ ] `get_redis` dependency factory wired in `dependencies.py`
- [ ] Unit tests written in TASK-008
- [ ] No secrets or PHI in cache keys
