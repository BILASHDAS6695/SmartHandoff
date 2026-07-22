"""JWT token blocklist backed by Cloud Memorystore Redis.

Provides two operations used across the auth flow:
  - add_to_blocklist(jti, exp)  — called on logout and deprovisioning
  - is_blocklisted(jti)         — called in get_current_user() AFTER
                                  signature validation

Key schema:
    ``jwt_blocklist:{jti}``  →  value "1", TTL = (exp - now) seconds

TTL strategy:
    The TTL is set to the remaining lifetime of the token so that Redis
    auto-expires entries once the token would have expired anyway. This
    prevents unbounded growth (US-059 AC Scenario 2).

Security order (US-059 Technical Notes):
    is_blocklisted() is always called AFTER jwt.decode() confirms a valid
    signature. An invalid-signature token is rejected before hitting Redis.

Design refs:
    design.md §7.4 AIR-032  — SCIM deprovisioning / JWT revocation
    design.md §10.3          — Token blocklist caching strategy
    SEC-009, SEC-011, US-059
"""
from __future__ import annotations

import logging
import os
import time
from functools import lru_cache

import redis

logger = logging.getLogger(__name__)

_BLOCKLIST_KEY_PREFIX = "jwt_blocklist:"


@lru_cache(maxsize=1)
def _get_redis_client() -> redis.Redis:
    """Return a shared Redis client, lazily initialised.

    Connection parameters are read from REDIS_URL (format:
    ``redis://:password@host:port/0``), mounted from Secret Manager by
    Cloud Run. TLS is enabled when the URL scheme is ``rediss://``.

    Raises:
        RuntimeError: If REDIS_URL is not set.
    """
    url = os.environ.get("REDIS_URL", "")
    if not url:
        raise RuntimeError(
            "REDIS_URL environment variable is not set. "
            "Mount the 'smarthandoff-redis-url-{env}' Secret Manager secret."
        )
    client = redis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=1,        # 1-second command timeout — guards the <5ms p99 target
        retry_on_timeout=False,  # fail fast; caller handles graceful degradation
    )
    logger.info(
        "Redis client initialised",
        extra={"event_type": "redis_init"},
    )
    return client


def add_to_blocklist(jti: str, exp: int) -> None:
    """Add a JWT ID to the blocklist with TTL equal to its remaining lifetime.

    Called on:
      - ``POST /api/v1/auth/logout``          — user-initiated logout (TASK-003)
      - ``DELETE /api/v1/admin/users/{id}``   — admin deprovisioning (TASK-004)

    Args:
        jti: The ``jti`` claim value from the JWT payload (UUID string).
        exp: The ``exp`` claim value (Unix timestamp). Used to compute TTL.

    Side effects:
        Sets Redis key ``jwt_blocklist:{jti}`` with value ``"1"`` and TTL
        = max(exp - now, 1). If TTL would be ≤0 the token is already expired
        and no write is performed (it cannot be used anyway).

    Raises:
        redis.RedisError: Propagated to caller; TASK-003/TASK-004 log and
        continue — a Redis failure on logout/deprovision is preferable to
        blocking the user-facing operation, but the caller MUST log a warning.
    """
    now = int(time.time())
    ttl = exp - now
    if ttl <= 0:
        logger.debug(
            "Skipping blocklist write for already-expired jti=%s",
            jti,
            extra={"event_type": "blocklist_skip_expired"},
        )
        return

    key = f"{_BLOCKLIST_KEY_PREFIX}{jti}"
    client = _get_redis_client()
    client.setex(key, ttl, "1")
    logger.info(
        "JWT blocklisted: jti=%s ttl=%ds",
        jti,
        ttl,
        extra={"event_type": "jwt_blocklisted", "jti": jti, "ttl_seconds": ttl},
    )


def is_blocklisted(jti: str) -> bool:
    """Check whether a JWT ID is in the blocklist.

    Called in ``get_current_user()`` AFTER signature validation. Invalid
    signatures are rejected before this function is reached.

    Args:
        jti: The ``jti`` claim value from the decoded JWT payload.

    Returns:
        True if the token is blocklisted (→ caller raises 401).
        False if the token is not blocklisted (→ normal flow continues).

    Raises:
        redis.RedisError: Propagated to caller. ``get_current_user()``
        should raise HTTP 503 on Redis failure — failing open would be a
        security regression.
    """
    key = f"{_BLOCKLIST_KEY_PREFIX}{jti}"
    client = _get_redis_client()
    result = client.exists(key)
    return bool(result)
