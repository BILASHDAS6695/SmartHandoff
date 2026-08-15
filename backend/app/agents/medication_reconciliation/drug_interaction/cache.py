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

    Example::
        >>> _build_cache_key("789", "123")
        'drug-interaction:123:789'
        >>> _build_cache_key("123", "789")
        'drug-interaction:123:789'
    """
    low, high = (rxcui1, rxcui2) if rxcui1 < rxcui2 else (rxcui2, rxcui1)
    return f"{_KEY_PREFIX}:{low}:{high}"


class DrugInteractionCache:
    """Thin async cache wrapper around a Redis connection.

    Provides get/set operations for drug interaction lookup results with
    automatic key normalization (sorted CUI pairs) and 24-hour TTL.

    Args:
        redis: An initialised ``redis.asyncio.Redis`` client.

    Example::
        from redis.asyncio import Redis
        from app.agents.medication_reconciliation.drug_interaction.cache import DrugInteractionCache

        redis = Redis(host="localhost", port=6379, decode_responses=True)
        cache = DrugInteractionCache(redis)

        # Store interaction result
        await cache.set("123", "456", {"severity": "major"})

        # Retrieve (order-independent)
        result = await cache.get("456", "123")  # Same as ("123", "456")
    """

    def __init__(self, redis: Redis | None = None) -> None:
        self._redis = redis
        # Fallback in-memory cache when Redis is not configured (local dev).
        self._memory: dict[str, dict[str, Any]] = {}

    async def get(self, rxcui1: str, rxcui2: str) -> dict[str, Any] | None:
        """Return cached interaction data for a CUI pair, or ``None`` on miss.

        Args:
            rxcui1: First RxNorm CUI.
            rxcui2: Second RxNorm CUI.

        Returns:
            Deserialized interaction payload, or ``None`` if not cached.

        Example::
            result = await cache.get("123", "456")
            if result is None:
                # Cache miss — fetch from RxNav API
                result = await fetch_from_rxnav(rxcui1, rxcui2)
                await cache.set(rxcui1, rxcui2, result)
        """
        key = _build_cache_key(rxcui1, rxcui2)
        if self._redis is None:
            return self._memory.get(key)
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

        Note:
            The cached data must be JSON-serializable. Store only
            interaction metadata, not PHI (patient names, MRNs, etc.).

        Example::
            interaction_data = {
                "severity": "major",
                "description": "Increased bleeding risk",
                "source": "rxnav",
            }
            await cache.set("123", "456", interaction_data)
        """
        key = _build_cache_key(rxcui1, rxcui2)
        if self._redis is None:
            self._memory[key] = data
            return
        await self._redis.set(key, json.dumps(data), ex=_CACHE_TTL_SECONDS)
        logger.debug("Cached interaction result key=%s ttl=%ds", key, _CACHE_TTL_SECONDS)
