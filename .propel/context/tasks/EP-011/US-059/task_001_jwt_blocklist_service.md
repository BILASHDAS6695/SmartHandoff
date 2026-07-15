---
id: TASK-001
title: "Create `JwtBlocklistService` + Add `jti` Claim to JWT Issuance"
user_story: US-059
epic: EP-011
sprint: 1
layer: Backend / Auth
estimate: 1.5h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-056/TASK-004, US-001/TASK-001]
---

# TASK-001: Create `JwtBlocklistService` + Add `jti` Claim to JWT Issuance

> **Story:** US-059 | **Epic:** EP-011 | **Sprint:** 1 | **Layer:** Backend / Auth | **Est:** 1.5 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

US-059 requires two coordinated changes to `backend/app/core/auth/jwt.py`:

1. **`jti` claim** — The JWT issued by `issue_app_jwt()` (US-056/TASK-004) must include a `jti` (JWT ID) UUID so that individual tokens can be blocklisted by ID without invalidating all tokens for a user. The US-059 Technical Notes specify: *"JWT `jti` claim: UUID generated at JWT issuance time"*.

2. **`JwtBlocklistService`** — A Redis-backed service that adds a `jti` to the blocklist on logout or deprovisioning and checks whether a `jti` is blocked on every incoming request. The blocklist key TTL is set to the remaining lifetime of the token (`jwt_exp - current_time`) so Redis auto-expires entries when the token would have expired anyway, preventing unbounded blocklist growth (AC Scenario 2).

The Redis client connects to Cloud Memorystore (provisioned in US-001) via the `REDIS_URL` environment variable mounted from Secret Manager.

---

## Acceptance Criteria Addressed

| US-059 AC | Requirement |
|---|---|
| **Scenario 1** | `jti` blocklisted within 1 second of deprovision — this task provides `add_to_blocklist()` |
| **Scenario 2** | No >5ms latency impact on non-blocklisted tokens; Redis TTL prevents unbounded growth |
| **Scenario 4** | Logout adds JWT `jti` to blocklist — this task provides `add_to_blocklist()` |
| **DoD** | `jwt_blocklist:{jti}` Redis key with TTL = remaining JWT lifetime |

---

## Implementation Steps

### 1. Add Redis Dependency to `backend/requirements.txt`

Add the following line (if not already present from US-001):

```
# --- Redis / JWT blocklist (US-059) ---
redis[hiredis]>=5.0.0
```

> **Note:** `hiredis` is the C extension parser for redis-py — included to ensure the sub-millisecond Redis response target (AC Scenario 2, <5ms p99) is achievable even under load.

---

### 2. Create `backend/app/core/auth/jwt_blocklist.py`

```python
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
        socket_timeout=1,         # 1-second command timeout — guards the <5ms p99 target
        retry_on_timeout=False,   # fail fast; caller handles graceful degradation
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
```

---

### 3. Update `backend/app/core/auth/jwt.py` — Add `jti` Claim to `issue_app_jwt()`

Locate the `payload` dictionary in `issue_app_jwt()` and add `jti`:

```python
import uuid as _uuid   # add at top-of-file if not present

# Inside issue_app_jwt(), replace the payload construction block:
payload = {
    **app_claims,
    "jti": str(_uuid.uuid4()),  # unique token ID — enables per-token blocklisting
    "iat": now,
    "exp": now + _TOKEN_EXPIRY_SECONDS,
}
```

> **Why here, not US-056:** US-056/TASK-004 was authored before the blocklist design was finalised. This task patches the issuance in-place. The change is backward-compatible — `jti` is an optional JWT claim per RFC 7519.

---

### 4. Update `backend/app/core/auth/__init__.py`

Add `jwt_blocklist` to the package docstring:

```python
"""Authentication and authorisation package for SmartHandoff.

Modules:
    oidc          — OIDC discovery + JWKS caching (US-056/TASK-002)
    tokens        — id_token validation + amr MFA enforcement (US-056/TASK-003)
    jwt           — Application JWT issuance and bearer validation (US-056/TASK-004)
    jwt_blocklist — Redis-backed JWT revocation blocklist (US-059/TASK-001)
"""
```

---

## Validation

```bash
cd backend

# Confirm redis-py installs cleanly
pip install "redis[hiredis]>=5.0.0"

# Smoke-test blocklist module loads without error
python -c "from app.core.auth.jwt_blocklist import add_to_blocklist, is_blocklisted; print('Import: OK')"

# Confirm jti appears in issued JWTs (requires REDIS_URL and JWT_SIGNING_KEY set)
python -c "
from app.core.auth.jwt import issue_app_jwt, _jwt_signing_key
from jose import jwt as _jose_jwt
token = issue_app_jwt({'sub': 'test-sub', 'groups': ['smarthandoff-nurse'], 'email': 'x@test.com'})
payload = _jose_jwt.decode(token, _jwt_signing_key(), algorithms=['HS256'])
assert 'jti' in payload, 'jti claim missing'
print('jti claim present:', payload['jti'])
"
```
