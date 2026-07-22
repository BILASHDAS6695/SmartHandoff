---
id: TASK-004
title: "Implement `POST /api/v1/auth/token` Endpoint and Application JWT Issuance"
user_story: US-056
epic: EP-011
sprint: 1
layer: Backend
estimate: 3h
priority: Must Have
status: Done
date: 2026-07-22
assignee: Backend Engineer
upstream: [US-056/TASK-003, US-005]
---

# TASK-004: Implement `POST /api/v1/auth/token` Endpoint and Application JWT Issuance

> **Story:** US-056 | **Epic:** EP-011 | **Sprint:** 1 | **Layer:** Backend | **Est:** 3 h
> **Status:** Done | **Date:** 2026-07-22

---

## Context

After `validate_id_token()` (TASK-003) verifies the OIDC id_token and enforces MFA, the backend must:

1. **Map OIDC claims to application claims** — `sub → user_id`, IdP `groups` claim → SmartHandoff `role`, custom `units` claim
2. **Issue a SmartHandoff application JWT** — HS256-signed, `exp=8h`, using the `jwt-signing-key` from Secret Manager (US-005)
3. **Expose the exchange endpoint** — `POST /api/v1/auth/token` returns the application JWT to Angular

This task also implements the FastAPI `get_current_user()` dependency used by all protected routes to validate the application JWT on every request.

Design.md Section 3.3 API Layer middleware stack specifies: *"JWT Validator (python-jose)"* at position 4 in the request chain. The validator here operates on the **application JWT** (not the OIDC id_token).

---

## Acceptance Criteria Addressed

| US-056 AC | Requirement |
|---|---|
| **Scenario 1** | SmartHandoff issues an application JWT with role and unit claims; stored in Angular memory only (frontend task) |
| **DoD** | Application JWT issuance: `sub=user_id`, `role`, `units`, `exp=8h`, signed with HS256 |
| **DoD** | JWT claims mapping: `sub → user_id`, `groups → role`, custom `units` claim |

---

## Implementation Steps

### 1. Implement `backend/app/core/auth/jwt.py`

Replace the TASK-001 stub:

```python
"""Application JWT issuance and Bearer token validation.

SmartHandoff issues its own short-lived JWT after validating the OIDC
id_token. This decouples the application session from the IdP session and
allows role/unit claims to be augmented from the SmartHandoff user DB.

JWT spec (US-056 DoD):
    sub     = user_id (from OIDC sub claim, mapped via DB lookup)
    role    = SmartHandoff role string (mapped from OIDC groups claim)
    units   = list of unit codes the user is assigned to
    email   = user email (from OIDC email claim)
    iat     = issued-at timestamp (UTC)
    exp     = iat + 8 hours (28800 seconds)
    alg     = HS256

Signing key:
    Loaded from Secret Manager secret 'smarthandoff-jwt-signing-key-{environment}'.
    Mounted by Cloud Run as the JWT_SIGNING_KEY environment variable (US-005/TASK-003).
    Must be a minimum 32-byte (256-bit) random string.

Bearer validation (get_current_user):
    Used as a FastAPI dependency on every protected route.
    Verifies HS256 signature, exp, and required claims.
    Returns decoded claims dict; raises HTTP 401 on any failure.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

logger = logging.getLogger(__name__)

_ALGORITHM = "HS256"
_TOKEN_EXPIRY_SECONDS = 8 * 60 * 60  # 8 hours (US-056 DoD)

_bearer_scheme = HTTPBearer(auto_error=True)


def _jwt_signing_key() -> str:
    """Return JWT_SIGNING_KEY from environment (mounted from Secret Manager)."""
    key = os.environ.get("JWT_SIGNING_KEY", "")
    if not key or len(key) < 32:
        raise RuntimeError(
            "JWT_SIGNING_KEY is not set or too short (minimum 32 characters). "
            "Mount it from Secret Manager 'smarthandoff-jwt-signing-key-{env}'."
        )
    return key


# ── Claims mapping helpers ─────────────────────────────────────────────────────

_ROLE_MAP: dict[str, str] = {
    # Map IdP group names to SmartHandoff role strings.
    # Keys must match the group names configured in the hospital IdP.
    "smarthandoff-admin":       "admin",
    "smarthandoff-physician":   "physician",
    "smarthandoff-nurse":       "nurse",
    "smarthandoff-pharmacist":  "pharmacist",
    "smarthandoff-bed-manager": "bed_manager",
}


def _map_role(groups: list[str]) -> str:
    """Map IdP groups to a SmartHandoff role string.

    Takes the first matching group in priority order (most privileged first).
    Returns "unknown" if no known group is found; callers should reject unknown roles.
    """
    for group in groups:
        if group in _ROLE_MAP:
            return _ROLE_MAP[group]
    return "unknown"


def _map_claims(oidc_claims: dict) -> dict:
    """Map OIDC id_token claims to SmartHandoff application JWT claims.

    Mapping spec (US-056 DoD):
        sub      → user_id  (OIDC subject identifier)
        groups   → role     (via _ROLE_MAP)
        units    → units    (custom claim set by IdP, default [])
        email    → email

    Args:
        oidc_claims: Decoded OIDC id_token claims dict.

    Returns:
        dict: Application claims ready for JWT encoding.

    Raises:
        HTTPException 403: If the role cannot be determined from IdP groups.
    """
    role = _map_role(oidc_claims.get("groups", []))
    if role == "unknown":
        logger.warning(
            "No recognised SmartHandoff group for sub=%s groups=%r",
            oidc_claims.get("sub"),
            oidc_claims.get("groups"),
            extra={"event_type": "auth_failure", "reason": "no_role"},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not assigned to a SmartHandoff role",
        )

    return {
        "sub": oidc_claims["sub"],           # user_id
        "role": role,
        "units": oidc_claims.get("units", []),
        "email": oidc_claims.get("email", ""),
    }


# ── JWT issuance ───────────────────────────────────────────────────────────────

def issue_app_jwt(oidc_claims: dict) -> str:
    """Issue a SmartHandoff application JWT from validated OIDC claims.

    Args:
        oidc_claims: Decoded and validated OIDC id_token claims (from TASK-003).

    Returns:
        str: Signed JWT string.

    Raises:
        HTTPException 403: If role mapping fails.
    """
    app_claims = _map_claims(oidc_claims)
    now = int(datetime.now(tz=timezone.utc).timestamp())

    payload = {
        **app_claims,
        "iat": now,
        "exp": now + _TOKEN_EXPIRY_SECONDS,
    }

    token = jwt.encode(payload, _jwt_signing_key(), algorithm=_ALGORITHM)
    logger.info(
        "Application JWT issued for sub=%s role=%s exp_in=%ds",
        app_claims["sub"],
        app_claims["role"],
        _TOKEN_EXPIRY_SECONDS,
        extra={"event_type": "jwt_issued"},
    )
    return token


# ── Bearer validation (FastAPI dependency) ────────────────────────────────────

async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
) -> dict:
    """FastAPI dependency: validate SmartHandoff application JWT from Bearer header.

    Inject this dependency on all protected routes:

        @router.get("/patients")
        async def list_patients(user: Annotated[dict, Depends(get_current_user)]):
            ...

    Returns:
        dict: Decoded JWT payload (includes sub, role, units, email, exp).

    Raises:
        HTTPException 401: If the token is missing, expired, or invalid.
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

    # Validate required claims are present
    for required_claim in ("sub", "role", "exp"):
        if required_claim not in payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token claims",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return payload
```

### 2. Create `backend/app/api/v1/routers/auth.py`

```python
"""Authentication router — POST /api/v1/auth/token.

Accepts an OIDC id_token from the Angular callback component, validates it,
enforces MFA, and issues a SmartHandoff application JWT.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.auth.jwt import issue_app_jwt
from app.core.auth.tokens import validate_id_token

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenRequest(BaseModel):
    id_token: str = Field(..., description="OIDC id_token from the identity provider")


class TokenResponse(BaseModel):
    access_token: str = Field(..., description="SmartHandoff application JWT")
    token_type: str = Field(default="bearer")
    expires_in: int = Field(default=28800, description="Token validity in seconds (8h)")


@router.post(
    "/token",
    response_model=TokenResponse,
    summary="Exchange OIDC id_token for SmartHandoff application JWT",
    description=(
        "Validates the OIDC id_token signature against the IdP JWKS, "
        "enforces MFA (amr claim), maps claims to SmartHandoff roles, "
        "and issues a HS256-signed application JWT."
    ),
)
async def exchange_token(body: TokenRequest) -> TokenResponse:
    """Exchange an OIDC id_token for a SmartHandoff application JWT."""
    oidc_claims = await validate_id_token(body.id_token)
    app_token = issue_app_jwt(oidc_claims)
    return TokenResponse(access_token=app_token)
```

### 3. Register the Auth Router in `backend/app/main.py`

In the FastAPI application factory, include the auth router **without** the `get_current_user` dependency (auth endpoints are public by design):

```python
from app.api.v1.routers.auth import router as auth_router

app.include_router(auth_router, prefix="/api/v1")
```

> All other routers must include `Depends(get_current_user)` either at the router level or on individual endpoints.

### 4. Set `JWT_SIGNING_KEY` Cloud Run Secret Mount

The `jwt-signing-key` Secret Manager secret created in US-001/TASK-001 must be mounted as `JWT_SIGNING_KEY` in the `api-gateway` Cloud Run service. This should already be configured via the `cloud_run` module secret mounts (US-005/TASK-003). Verify the following is present in the `api-gateway` service definition:

```hcl
secret_env_vars = [
  {
    env_var_name = "JWT_SIGNING_KEY"
    secret_name  = "smarthandoff-jwt-signing-key-${var.environment}"
    version      = "latest"
  }
]
```

If this mount is missing, add it — do not hardcode the key value.

---

## Validation

```bash
cd backend

# 1. Import check
python -c "
from app.core.auth.jwt import issue_app_jwt, get_current_user
from app.api.v1.routers.auth import router
print('Auth imports OK')
"

# 2. JWT issuance produces a valid token structure
JWT_SIGNING_KEY=testkey_minimum_32_chars_exactly python -c "
from app.core.auth.jwt import issue_app_jwt
from jose import jwt
import os

token = issue_app_jwt({
    'sub': 'user-123',
    'groups': ['smarthandoff-physician'],
    'units': ['4B', '5A'],
    'email': 'dr.jones@hospital.example.com',
})
claims = jwt.decode(token, os.environ['JWT_SIGNING_KEY'], algorithms=['HS256'])
assert claims['role'] == 'physician'
assert claims['sub'] == 'user-123'
assert claims['exp'] - claims['iat'] == 28800
print('JWT issuance OK')
"

# 3. Unknown role raises 403
JWT_SIGNING_KEY=testkey_minimum_32_chars_exactly python -c "
from fastapi import HTTPException
from app.core.auth.jwt import issue_app_jwt
try:
    issue_app_jwt({'sub': 'u1', 'groups': ['unknown-group'], 'email': ''})
    assert False
except HTTPException as e:
    assert e.status_code == 403
    print('Role rejection OK')
"
```

---

## Files Touched

| File | Action |
|---|---|
| `backend/app/core/auth/jwt.py` | Replace TASK-001 stub with full implementation |
| `backend/app/api/v1/routers/auth.py` | Create auth router with `POST /token` endpoint |
| `backend/app/main.py` | Register auth router under `/api/v1` |

---

## Definition of Done Checklist

- [ ] `app/core/auth/jwt.py` fully implemented; `issue_app_jwt()` and `get_current_user()` not stubs
- [ ] JWT payload contains: `sub`, `role`, `units`, `email`, `iat`, `exp` (exp = iat + 28800)
- [ ] HS256 algorithm used; RS256 is NOT used for application JWTs
- [ ] `JWT_SIGNING_KEY` minimum length check (32 chars) raises `RuntimeError` if violated
- [ ] `POST /api/v1/auth/token` returns `{"access_token": "...", "token_type": "bearer", "expires_in": 28800}`
- [ ] Unknown IdP group → 403 (not 401)
- [ ] `get_current_user()` dependency available for import by other routers
- [ ] Auth router registered in `app/main.py`
- [ ] `JWT_SIGNING_KEY` Secret Manager mount verified in Cloud Run terraform config

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| US-056/TASK-003 | Upstream task | `validate_id_token()` must be implemented before the token endpoint can call it |
| US-005 | Story | `jwt-signing-key` must exist in Secret Manager and be mounted as `JWT_SIGNING_KEY` |
| US-001/TASK-001 | Task | `secrets` Terraform module creates the `jwt-signing-key` Secret Manager secret |
