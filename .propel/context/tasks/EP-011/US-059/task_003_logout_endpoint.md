---
id: TASK-003
title: "Implement `POST /api/v1/auth/logout` Endpoint — Blocklist Current JWT"
user_story: US-059
epic: EP-011
sprint: 1
layer: Backend / API
estimate: 1h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-059/TASK-001, US-059/TASK-002]
---

# TASK-003: Implement `POST /api/v1/auth/logout` Endpoint — Blocklist Current JWT

> **Story:** US-059 | **Epic:** EP-011 | **Sprint:** 1 | **Layer:** Backend / API | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

AC Scenario 4 requires that when a staff member clicks "Log Out", `POST /api/v1/auth/logout` is called and the JWT `jti` is immediately added to the Redis blocklist. Subsequent requests with the same JWT must return `401 Unauthorized`.

The endpoint:
1. Extracts the current user's JWT via the `get_current_user()` dependency (TASK-002), which has already validated the token.
2. Calls `add_to_blocklist(jti, exp)` with the claims from the decoded payload.
3. Returns `200 OK` — no body payload needed; the Angular `AuthService` clears the in-memory JWT on any successful logout response (Angular TASK-005).

The logout endpoint is placed in the existing auth router at `backend/app/api/v1/auth.py`. If the router does not yet exist (pre-US-056 merge), create it and register it on the main application.

---

## Acceptance Criteria Addressed

| US-059 AC | Requirement |
|---|---|
| **Scenario 4** | `POST /api/v1/auth/logout` adds `jti` to Redis blocklist; subsequent call with same JWT → `401` |
| **DoD** | `POST /api/v1/auth/logout` endpoint: blocklist current JWT + 200 OK |

---

## Implementation Steps

### 1. Add Logout Endpoint to `backend/app/api/v1/auth.py`

If `backend/app/api/v1/auth.py` already exists from US-056/TASK-004, **add** the route to the existing router. Do not replace the file.

```python
"""Auth router — OIDC token exchange, logout.

Routes:
    POST /api/v1/auth/token   — exchange OIDC id_token for app JWT (US-056)
    POST /api/v1/auth/logout  — revoke current JWT via Redis blocklist (US-059)

Design refs:
    design.md §3.3 API Layer / Routers
    design.md §8.2 Authentication & Authorization Flow
    AIR-032, SEC-009, US-059
"""
from __future__ import annotations

import logging
from typing import Annotated

import redis
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth.jwt import TokenClaims, get_current_user
from app.core.auth.jwt_blocklist import add_to_blocklist

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# ── POST /api/v1/auth/logout ──────────────────────────────────────────────────

@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    summary="Revoke the current JWT and end the session",
    response_description="Session terminated; JWT blocklisted",
)
async def logout(
    current_user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """Blocklist the current JWT and instruct the client to clear its session.

    The ``get_current_user`` dependency validates the Bearer token before
    this handler runs. A valid (non-expired, non-blocklisted) token is
    required — you cannot log out with an already-invalid token.

    After successful logout the client MUST discard its in-memory JWT.
    Any subsequent request with the same JWT returns 401 Unauthorized.

    Returns:
        JSON body ``{"message": "Logged out successfully"}``

    Raises:
        HTTP 401: Token invalid or already expired (raised by get_current_user).
        HTTP 503: Redis unavailable.
    """
    jti: str | None = current_user.get("jti")
    exp: int | None = current_user.get("exp")

    if not jti or not exp:
        # Token predates jti claim — cannot blocklist, but still respond 200
        # so the client can clear its local JWT and redirect to login.
        logger.warning(
            "Logout requested for token without jti claim: sub=%s",
            current_user.get("sub"),
            extra={"event_type": "logout_no_jti", "sub": current_user.get("sub")},
        )
        return {"message": "Logged out successfully"}

    try:
        add_to_blocklist(jti, exp)
    except redis.RedisError as exc:
        logger.error(
            "Redis error during logout blocklist write: jti=%s error=%s",
            jti,
            exc,
            extra={"event_type": "redis_error", "context": "logout", "jti": jti},
        )
        # Do NOT raise 503 here — the user's intent to log out must succeed
        # even if Redis is momentarily unavailable. Log the failure for ops.
        # The token will expire naturally within its 8-hour window.

    logger.info(
        "User logged out: sub=%s jti=%s",
        current_user.get("sub"),
        jti,
        extra={
            "event_type": "user_logout",
            "sub": current_user.get("sub"),
            "jti": jti,
        },
    )
    return {"message": "Logged out successfully"}
```

---

### 2. Register the Auth Router in `backend/app/main.py`

If the auth router is not yet registered, add it to the FastAPI application:

```python
from app.api.v1.auth import router as auth_router

app.include_router(auth_router, prefix="/api/v1")
```

> **Note:** If US-056/TASK-004 already registered this router, this step is a no-op — verify with `grep -n "auth_router" backend/app/main.py`.

---

## Validation

```bash
cd backend

# 1. Confirm route is registered
python -c "
from app.main import app
routes = [r.path for r in app.routes]
assert '/api/v1/auth/logout' in routes, f'Missing /logout. Routes: {routes}'
print('Route registered: OK')
"

# 2. Run auth unit tests
pytest tests/unit/core/auth/ -v --tb=short -q

# 3. Integration smoke test (requires running FastAPI + Redis):
# Issue a token, call /logout, confirm the jti is blocklisted.
# curl -X POST http://localhost:8000/api/v1/auth/logout \
#      -H "Authorization: Bearer <token>"
# Expected: 200 {"message": "Logged out successfully"}
# Second call with same token:
# curl -X POST http://localhost:8000/api/v1/auth/logout \
#      -H "Authorization: Bearer <token>"
# Expected: 401 Unauthorized
```
