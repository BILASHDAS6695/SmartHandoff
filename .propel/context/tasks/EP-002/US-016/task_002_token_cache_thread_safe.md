# TASK-002: Implement Thread-Safe TokenCache Dataclass with Expiry Buffer Logic

> **Story:** US-016 | **Epic:** EP-002 | **Sprint:** 1 | **Layer:** Backend | **Est:** 8 h  
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

This task implements an in-memory token cache with a 60-second expiry buffer to prevent token expiry mid-request. The cache uses `asyncio.Lock` for thread-safe access, preventing race conditions when multiple concurrent agent tasks attempt to refresh the token simultaneously.

**Design references:**
- US-016 AC Scenario 2 — Cached token reused without re-authentication
- US-016 AC Scenario 3 — Token refreshed before expiry buffer (60s)
- US-016 DoD — In-memory token cache with `access_token` and `expires_at` fields
- US-016 DoD — Token cache thread-safe via `asyncio.Lock`

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| AC Scenario 2 | TokenCache stores and returns valid cached tokens |
| AC Scenario 3 | TokenCache implements 60-second expiry buffer for auto-refresh |

---

## Implementation Steps

### 1. Implement `backend/app/core/fhir/token_cache.py`

Create the thread-safe token cache with expiry buffer logic:

```python
"""Thread-safe in-memory token cache for SMART on FHIR access tokens.

Design refs:
    US-016 AC Scenario 2 — cached token reused without re-authentication
    US-016 AC Scenario 3 — token refreshed before 60-second expiry buffer
    US-016 DoD           — asyncio.Lock for thread-safety
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


@dataclass
class TokenCacheEntry:
    """A cached FHIR access token with expiry timestamp.

    Attributes:
        access_token: The OAuth 2.0 access token string
        expires_at: UTC timestamp when the token expires (with 60s buffer already applied)
    """

    access_token: str
    expires_at: datetime  # UTC, with 60s buffer already applied


class TokenCache:
    """Thread-safe in-memory cache for SMART on FHIR access tokens.

    This cache stores a single access token with its expiry timestamp.
    The expiry includes a 60-second safety buffer to prevent token expiry mid-request.

    Thread safety:
        All operations are protected by an asyncio.Lock to prevent race conditions
        when multiple concurrent agent tasks attempt to refresh the token.

    Example:
        cache = TokenCache()
        await cache.set_token("token_abc", expires_in=3600)
        token = await cache.get_token()  # Returns "token_abc" if not expired
        await cache.clear()  # Invalidate cached token
    """

    def __init__(self, expiry_buffer_seconds: int = 60) -> None:
        """Initialize an empty token cache.

        Args:
            expiry_buffer_seconds: Number of seconds before actual expiry to consider
                                   the token expired (default: 60s per US-016 AC)
        """
        self._cache: TokenCacheEntry | None = None
        self._lock = asyncio.Lock()
        self._expiry_buffer = timedelta(seconds=expiry_buffer_seconds)
        logger.info(
            "TokenCache initialized with %ds expiry buffer",
            expiry_buffer_seconds,
        )

    async def get_token(self) -> str | None:
        """Retrieve the cached access token if it exists and is not expired.

        Returns:
            The cached access token, or None if no token is cached or it has expired

        Thread-safety:
            This method is thread-safe (protected by asyncio.Lock)
        """
        async with self._lock:
            if self._cache is None:
                logger.debug("Token cache miss: no token cached")
                return None

            now = datetime.now(timezone.utc)
            if now >= self._cache.expires_at:
                remaining = (self._cache.expires_at - now).total_seconds()
                logger.info(
                    "Token cache miss: token expired",
                    extra={
                        "event": "token_cache_expired",
                        "remaining_seconds": remaining,
                    },
                )
                self._cache = None
                return None

            remaining = (self._cache.expires_at - now).total_seconds()
            logger.debug(
                "Token cache hit: %ds remaining until expiry",
                remaining,
            )
            return self._cache.access_token

    async def set_token(self, access_token: str, expires_in: int) -> None:
        """Store a new access token in the cache with expiry buffer applied.

        Args:
            access_token: The OAuth 2.0 access token string
            expires_in: Token lifetime in seconds (as returned by the auth server)

        The actual cache expiry will be set to (now + expires_in - buffer) to ensure
        the token is refreshed before it expires.

        Thread-safety:
            This method is thread-safe (protected by asyncio.Lock)
        """
        async with self._lock:
            now = datetime.now(timezone.utc)
            # Apply the 60-second buffer by subtracting it from the actual expiry
            expires_at = now + timedelta(seconds=expires_in) - self._expiry_buffer
            self._cache = TokenCacheEntry(
                access_token=access_token,
                expires_at=expires_at,
            )
            logger.info(
                "Token cached with %ds lifetime (buffer-adjusted)",
                expires_in - self._expiry_buffer.total_seconds(),
                extra={
                    "event": "token_cached",
                    "original_expires_in": expires_in,
                    "buffer_seconds": self._expiry_buffer.total_seconds(),
                    "effective_expires_in": expires_in - self._expiry_buffer.total_seconds(),
                },
            )

    async def clear(self) -> None:
        """Clear the cached token (invalidate the cache).

        This is called when authentication fails or when the cached token is rejected
        by the FHIR server (e.g., revoked token).

        Thread-safety:
            This method is thread-safe (protected by asyncio.Lock)
        """
        async with self._lock:
            if self._cache is not None:
                logger.info("Token cache cleared")
                self._cache = None

    async def is_expired(self) -> bool:
        """Check if the cached token is expired (within the buffer window).

        Returns:
            True if no token is cached or the token is expired, False otherwise

        Thread-safety:
            This method is thread-safe (protected by asyncio.Lock)
        """
        token = await self.get_token()
        return token is None
```

### 2. Update `backend/app/core/fhir/__init__.py`

Export the TokenCache class:

```python
"""FHIR authentication and API client.

Provides SMART on FHIR OAuth 2.0 authentication with token caching.
"""
from app.core.fhir.discovery import discover_smart_config, get_token_endpoint
from app.core.fhir.exceptions import FHIRAuthenticationError
from app.core.fhir.token_cache import TokenCache, TokenCacheEntry

__all__ = [
    "FHIRAuthenticationError",
    "TokenCache",
    "TokenCacheEntry",
    "discover_smart_config",
    "get_token_endpoint",
]
```

---

## Files Modified / Created

| File | Change Type | Lines (approx) |
|------|-------------|----------------|
| `backend/app/core/fhir/token_cache.py` | Created | 140 |
| `backend/app/core/fhir/__init__.py` | Modified | +2 lines |

**Total:** ~142 lines

---

## Verification

### Manual testing

```python
# Test in Python REPL or pytest
import asyncio
from app.core.fhir.token_cache import TokenCache

async def test_cache():
    cache = TokenCache(expiry_buffer_seconds=60)
    
    # Test cache miss
    token = await cache.get_token()
    assert token is None, "Empty cache should return None"
    
    # Test cache set and hit
    await cache.set_token("token_abc", expires_in=3600)
    token = await cache.get_token()
    assert token == "token_abc", "Cache should return stored token"
    
    # Test expiry buffer (token with 50s remaining should be expired)
    await cache.set_token("token_short", expires_in=50)
    token = await cache.get_token()
    assert token is None, "Token within expiry buffer should be expired"
    
    # Test clear
    await cache.set_token("token_xyz", expires_in=3600)
    await cache.clear()
    token = await cache.get_token()
    assert token is None, "Cleared cache should return None"
    
    print("All cache tests passed!")

asyncio.run(test_cache())
```

### Code review checklist

- [ ] `asyncio.Lock` used for all cache operations (get, set, clear)
- [ ] Expiry buffer (60s) correctly subtracted from `expires_in` in `set_token()`
- [ ] `datetime.now(timezone.utc)` used for all timestamp comparisons (no naive datetimes)
- [ ] Logging at appropriate levels (INFO for cache state changes, DEBUG for hits/misses)
- [ ] No PHI in logs (token values never logged, only metadata)
- [ ] `is_expired()` method delegates to `get_token()` for consistency

---

## Definition of Done Checklist

- [ ] `TokenCacheEntry` dataclass implemented with `access_token` and `expires_at`
- [ ] `TokenCache` class implemented with `asyncio.Lock` for thread-safety
- [ ] `get_token()` method returns None for expired tokens (within 60s buffer)
- [ ] `set_token()` method applies 60-second expiry buffer
- [ ] `clear()` method invalidates cached token
- [ ] `is_expired()` method checks token expiry
- [ ] All methods log cache operations (no PHI in logs)
- [ ] Module exports updated in `__init__.py`
- [ ] Manual verification with test script
- [ ] Code passes `ruff check` and `mypy` validation
- [ ] Code reviewed and approved

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 | Task | Exceptions module must exist |
| Python 3.11+ | Runtime | asyncio.Lock, timezone-aware datetime |

---

## Notes

- **Expiry buffer rationale:** The 60-second buffer ensures tokens are refreshed before they expire, preventing mid-request failures during FHIR API calls that may take several seconds.
- **Single token cache:** This cache stores only one token (the current FHIR access token). Multiple EHR instances would require separate FHIRAuthClient instances with their own caches.
- **Thread safety:** `asyncio.Lock` prevents race conditions when multiple agent tasks attempt to refresh the token simultaneously (e.g., 6 agents starting at the same time after a cold start).
- **Memory safety:** The cache is in-memory only and lost on container restart. This is acceptable because token refresh is fast (typically <500ms).
- **Unit tests:** Deferred to TASK-004 (comprehensive unit test suite with time mocking).
