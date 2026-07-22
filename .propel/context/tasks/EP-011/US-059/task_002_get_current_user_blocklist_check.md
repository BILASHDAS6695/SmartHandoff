---
id: TASK-002
title: "Update `get_current_user()` — Redis Blocklist Check After Signature Validation"
user_story: US-059
epic: EP-011
sprint: 1
layer: Backend / Auth
estimate: 1h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-059/TASK-001]
---

# TASK-002: Update `get_current_user()` — Redis Blocklist Check After Signature Validation

> **Story:** US-059 | **Epic:** EP-011 | **Sprint:** 1 | **Layer:** Backend / Auth | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

The FastAPI `get_current_user()` dependency (defined in `backend/app/core/auth/jwt.py`, US-056/TASK-004) validates the Bearer JWT on every protected request. After signature validation it currently returns the decoded payload unconditionally.

This task inserts the Redis blocklist check **after** `jwt.decode()` succeeds — matching the security ordering specified in US-059 Technical Notes: *"blocklist check must happen AFTER signature validation — invalid signatures still rejected first."*

The check calls `is_blocklisted(jti)` from TASK-001. If the `jti` is on the blocklist the dependency raises `HTTP 401` before the router handler is invoked, satisfying AC Scenario 1 (rejected within 1 second) and AC Scenario 4 (rejected after logout).

A missing `jti` claim (token issued before TASK-001 patched `issue_app_jwt`) is treated as a legacy unrevocable token and **allowed through with a warning** — this prevents a hard lockout during the deployment window when old tokens are still in circulation. The warning surfaces in Cloud Logging for monitoring.

---

## Acceptance Criteria Addressed

| US-059 AC | Requirement |
|---|---|
| **Scenario 1** | Next API call with deprovisioned JWT returns `401 Unauthorized` within 1 second |
| **Scenario 2** | `is_blocklisted()` checked on every request; non-blocked tokens see <5ms overhead |
| **Scenario 4** | API call with logged-out JWT returns `401 Unauthorized` |
| **DoD** | FastAPI JWT middleware: `if redis.sismember("jwt_blocklist", jti): raise HTTPException(401)` |

---

## Implementation Steps

### 1. Update `backend/app/core/auth/jwt.py` — `get_current_user()` Function

Locate `get_current_user()` in `backend/app/core/auth/jwt.py` and replace it with the version below. The only net-new logic is the `jti` extraction and `is_blocklisted()` call inserted after the existing `jwt.decode()` block.

```python
import redis as _redis   # add at top of file if not present

from app.core.auth.jwt_blocklist import is_blocklisted   # add import


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
) -> dict:
    """FastAPI dependency: validate SmartHandoff application JWT from Bearer header.

    Validation order (US-059 Technical Notes — security-critical):
        1. HS256 signature + expiry verified by jose.jwt.decode()
        2. Redis blocklist checked for jti (after valid signature confirmed)
        3. Required claims presence validated
        4. Decoded payload returned to router handler

    Returns:
        dict: Decoded JWT payload (includes sub, role, units, email, jti, exp).

    Raises:
        HTTPException 401: Signature invalid, token expired, or token blocklisted.
        HTTPException 503: Redis unavailable (fail-closed — security requirement).
    """
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            _jwt_signing_key(),
            algorithms=[_ALGORITHM],
            options={"verify_exp": True},
        )
    except JWTError as exc:
        logger.warning(
            "Bearer JWT validation failed: %s",
            type(exc).__name__,
            extra={"event_type": "auth_failure", "reason": "invalid_bearer"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    # ── Blocklist check (US-059) — MUST be after signature validation ──────────
    jti: str | None = payload.get("jti")
    if jti:
        try:
            if is_blocklisted(jti):
                logger.warning(
                    "Blocklisted JWT presented: jti=%s sub=%s",
                    jti,
                    payload.get("sub"),
                    extra={
                        "event_type": "auth_failure",
                        "reason": "token_blocklisted",
                        "jti": jti,
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired access token",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        except _redis.RedisError as exc:
            # Fail-closed: Redis unavailable means we cannot confirm
            # the token is not revoked — treat as a service error.
            logger.error(
                "Redis unavailable during blocklist check: %s",
                exc,
                extra={"event_type": "redis_error", "context": "blocklist_check"},
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service temporarily unavailable",
            ) from exc
    else:
        # Token predates jti claim introduction — allow through with warning.
        # Remove this branch after all pre-jti tokens have expired (8 hours
        # after TASK-001 is deployed).
        logger.warning(
            "JWT without jti claim from sub=%s — cannot blocklist-check; "
            "token will expire naturally in %d seconds",
            payload.get("sub"),
            max(payload.get("exp", 0) - int(time.time()), 0),
            extra={"event_type": "auth_warning", "reason": "missing_jti"},
        )

    # ── Required claims presence ───────────────────────────────────────────────
    for required_claim in ("sub", "role", "exp"):
        if required_claim not in payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired access token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return payload
```

> **Import note:** Add `import time` at the top of `jwt.py` if not already present (used for the legacy-token warning log).

---

## Validation

```bash
cd backend

# 1. Confirm the module still imports cleanly
python -c "from app.core.auth.jwt import get_current_user; print('Import: OK')"

# 2. Run existing auth unit tests — no regressions expected
pytest tests/unit/core/auth/ -v --tb=short -q

# 3. Manual integration check with a real token (requires REDIS_URL + JWT_SIGNING_KEY):
# Issue a token, blocklist its jti manually, then confirm 401 on re-use.
python -c "
import os, time, uuid
os.environ.setdefault('REDIS_URL', 'redis://localhost:6379/0')
os.environ.setdefault('JWT_SIGNING_KEY', 'test-key-32-chars-minimum-padding')
from app.core.auth.jwt import issue_app_jwt
from app.core.auth.jwt_blocklist import add_to_blocklist, is_blocklisted
from jose import jwt as _jose_jwt

token = issue_app_jwt({'sub': 'u1', 'groups': ['smarthandoff-nurse'], 'email': 'n@test.com'})
payload = _jose_jwt.decode(token, os.environ['JWT_SIGNING_KEY'], algorithms=['HS256'])
jti = payload['jti']

print('Before blocklist:', is_blocklisted(jti))   # False
add_to_blocklist(jti, payload['exp'])
print('After blocklist:', is_blocklisted(jti))    # True
"
```
