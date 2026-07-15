---
id: TASK-002
title: "Implement SCIM Bearer Token Authentication (`verify_scim_token` FastAPI Dependency)"
user_story: US-060
epic: EP-011
sprint: 2
layer: Backend / Auth
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-060/TASK-001, US-056/TASK-001]
---

# TASK-002: Implement SCIM Bearer Token Authentication (`verify_scim_token` FastAPI Dependency)

> **Story:** US-060 | **Epic:** EP-011 | **Sprint:** 2 | **Layer:** Backend / Auth | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

SCIM 2.0 endpoints use a **separate authentication mechanism** from staff JWTs. The hospital IdP authenticates its SCIM provisioning requests using a long-lived bearer token (90-day rotation), which is distinct from the short-lived (15-minute) staff access JWTs validated by `get_current_user()`.

US-060 Technical Notes specify: *"SCIM bearer token: separate from staff JWTs; long-lived (90-day rotation); stored in Secret Manager"*. AC Scenario 3 requires that unauthenticated SCIM requests return `401 Unauthorized`.

Design.md §7.4 AIR-032 and SEC-011 (zero hardcoded credentials, TR-021) require the SCIM token to be stored in GCP Secret Manager and loaded at startup — never hardcoded.

This task creates a FastAPI dependency `verify_scim_token` that:
1. Reads the `Authorization: Bearer <token>` header from the incoming request.
2. Compares it via `hmac.compare_digest` (constant-time, prevents timing attacks) against the SCIM client secret loaded from Secret Manager.
3. Raises `HTTPException(401)` on mismatch or missing header.

---

## Acceptance Criteria Addressed

| US-060 AC | Requirement |
|---|---|
| **Scenario 3** | Unauthenticated SCIM POST → `401 Unauthorized`; bearer token required and validated |
| **DoD** | SCIM bearer token authentication: configurable SCIM client secret in Secret Manager |

---

## Implementation Steps

### 1. Add Secret Manager Binding for SCIM Token

In `backend/app/core/config.py` (or equivalent settings module), add the SCIM client secret to the settings pulled from Secret Manager at startup:

```python
# backend/app/core/config.py  (add to existing Settings class)

class Settings(BaseSettings):
    # ... existing fields ...

    # SCIM 2.0 authentication (US-060)
    # Loaded from GCP Secret Manager: projects/{project}/secrets/scim-client-secret
    SCIM_CLIENT_SECRET: str = Field(
        ...,
        description=(
            "Long-lived bearer token issued to the hospital IdP for SCIM provisioning. "
            "90-day rotation. Stored in GCP Secret Manager as 'scim-client-secret'."
        ),
    )
```

The Secret Manager binding in Cloud Run mounts this as an environment variable named `SCIM_CLIENT_SECRET` (TR-021 — no hardcoded credentials).

---

### 2. Create `backend/app/api/v1/admin/scim/scim_auth.py`

```python
"""SCIM 2.0 bearer token authentication dependency.

The SCIM client secret is separate from staff JWTs (US-060 Technical Notes).
It is a long-lived bearer token (90-day rotation) stored in GCP Secret Manager
and mounted as the SCIM_CLIENT_SECRET environment variable in Cloud Run.

Security properties:
  - hmac.compare_digest prevents timing-based token enumeration attacks
  - No token value exposed in error responses or logs (SEC-011)
  - Invalid requests return 401 with the standard WWW-Authenticate header

Design refs:
    design.md §7.4 AIR-032  — SCIM bearer token authentication
    TR-021                   — zero hardcoded credentials
    SEC-011                  — secrets in Secret Manager only
    US-060 AC Scenario 3     — unauthenticated SCIM → 401
"""
from __future__ import annotations

import hmac
import logging

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


async def verify_scim_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> None:
    """FastAPI dependency that validates the SCIM bearer token.

    Usage:
        @router.post("/Users", dependencies=[Depends(verify_scim_token)])

    Raises:
        HTTPException 401 if the token is absent or does not match the
        configured SCIM_CLIENT_SECRET.

    Security:
        hmac.compare_digest is used to prevent timing-oracle attacks.
        The actual token is never logged or included in error details.
    """
    settings = get_settings()

    if credentials is None:
        _reject(request)

    provided = credentials.credentials  # type: ignore[union-attr]
    expected = settings.SCIM_CLIENT_SECRET

    if not hmac.compare_digest(
        provided.encode("utf-8"),
        expected.encode("utf-8"),
    ):
        _reject(request)


def _reject(request: Request) -> None:
    """Log the rejection and raise 401 without leaking token details."""
    logger.warning(
        "SCIM auth failure",
        extra={
            "event": "scim_auth_failure",
            "client_ip": request.client.host if request.client else "unknown",
            # No token value logged (SEC-011)
        },
    )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="SCIM authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )
```

---

## Files Created / Modified

| File | Action |
|---|---|
| `backend/app/api/v1/admin/scim/scim_auth.py` | **Create** |
| `backend/app/core/config.py` | **Modify** — add `SCIM_CLIENT_SECRET` field |

---

## Validation

```bash
# Confirm SCIM_CLIENT_SECRET field present in settings
cd backend
python -c "
import os; os.environ.setdefault('SCIM_CLIENT_SECRET', 'test-scim-token')
from app.core.config import get_settings
s = get_settings()
print('SCIM secret loaded, length:', len(s.SCIM_CLIENT_SECRET))
"

# Confirm hmac.compare_digest rejects mismatched tokens
python -c "
import hmac
assert not hmac.compare_digest(b'wrong', b'correct'), 'Should reject'
assert hmac.compare_digest(b'same', b'same'), 'Should accept'
print('hmac.compare_digest behaves correctly')
"
```
