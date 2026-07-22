---
id: TASK-001
title: "Add Python OIDC/JWT Dependencies and Scaffold `app/core/auth/` Package"
user_story: US-056
epic: EP-011
sprint: 1
layer: Backend
estimate: 1h
priority: Must Have
status: Done
date: 2026-07-22
assignee: Backend Engineer
upstream: []
---

# TASK-001: Add Python OIDC/JWT Dependencies and Scaffold `app/core/auth/` Package

> **Story:** US-056 | **Epic:** EP-011 | **Sprint:** 1 | **Layer:** Backend | **Est:** 1 h
> **Status:** Done | **Date:** 2026-07-22

---

## Context

US-056 requires three Python libraries not yet in `backend/requirements.txt`:

| Library | Role |
|---|---|
| `python-jose[cryptography]` | RS256/HS256 JWT decoding; per Technical Notes |
| `cachetools` | `TTLCache(maxsize=1, ttl=3600)` for JWKS caching; per Technical Notes |
| `authlib` | OIDC discovery document fetch and SMART on FHIR OAuth2 (AIR-030) |

Before TASK-002 and TASK-003 can implement logic, these libraries must be pinned and the `app/core/auth/` package skeleton must exist so all subsequent tasks have a stable import path.

---

## Acceptance Criteria Addressed

| US-056 DoD Item | Requirement |
|---|---|
| FastAPI OIDC middleware | Requires `python-jose` and `cachetools` to be installed |
| JWT issuance (HS256) | Requires `python-jose` |

---

## Implementation Steps

### 1. Pin Libraries in `backend/requirements.txt`

Add the following entries. Use minimum-version pins to guarantee security-patched releases; Artifact Registry scanning (TR-019) rejects CRITICAL CVEs in earlier builds:

```
# --- Authentication & JWT (US-056) ---
python-jose[cryptography]>=3.3.0
cachetools>=5.3.0
authlib>=1.3.0
```

> **Note:** `authlib>=1.3.0` may already be present if the FHIR integration (AIR-010) was added earlier. If it is, skip that line — do not duplicate it.

> **Security note:** `python-jose[cryptography]>=3.3.0` is the minimum that fixes the known RSA key confusion vulnerability in earlier 3.x releases. The `[cryptography]` extra installs the `cryptography` backend (already present from US-007), avoiding the `rsa` extra which uses an unmaintained RSA library.

### 2. Create `backend/app/core/auth/` Package Skeleton

Create the following files:

#### `backend/app/core/auth/__init__.py`

```python
"""Authentication and authorisation package for SmartHandoff.

Modules:
    oidc    — OIDC discovery + JWKS caching (TASK-002)
    tokens  — id_token validation + amr MFA enforcement (TASK-003)
    jwt     — Application JWT issuance and bearer validation (TASK-004)
"""
```

#### `backend/app/core/auth/oidc.py` (skeleton)

```python
"""OIDC discovery and JWKS caching.

Implemented in TASK-002. This skeleton ensures TASK-003+ can import
from this module before TASK-002 is complete.
"""
from __future__ import annotations


def get_jwks_uri() -> str:  # pragma: no cover
    """Fetch OIDC discovery document and return jwks_uri. Implemented in TASK-002."""
    raise NotImplementedError("Implemented in TASK-002")


async def fetch_jwks() -> dict:  # pragma: no cover
    """Return cached or fresh JWKS. TTL=3600s. Implemented in TASK-002."""
    raise NotImplementedError("Implemented in TASK-002")
```

#### `backend/app/core/auth/tokens.py` (skeleton)

```python
"""OIDC id_token validation and amr MFA enforcement.

Implemented in TASK-003. This skeleton ensures TASK-004 can import
from this module before TASK-003 is complete.
"""
from __future__ import annotations


async def validate_id_token(id_token: str) -> dict:  # pragma: no cover
    """Validate OIDC id_token signature + claims. Implemented in TASK-003.

    Returns:
        Decoded claims dict on success.
    Raises:
        fastapi.HTTPException 401 on any validation failure.
    """
    raise NotImplementedError("Implemented in TASK-003")
```

#### `backend/app/core/auth/jwt.py` (skeleton)

```python
"""Application JWT issuance and bearer token validation.

Implemented in TASK-004. This skeleton ensures route modules can import
from here before TASK-004 is complete.
"""
from __future__ import annotations


def issue_app_jwt(claims: dict) -> str:  # pragma: no cover
    """Issue a SmartHandoff application JWT. Implemented in TASK-004."""
    raise NotImplementedError("Implemented in TASK-004")


async def get_current_user() -> dict:  # pragma: no cover
    """FastAPI dependency: validates Bearer JWT, returns user claims. TASK-004."""
    raise NotImplementedError("Implemented in TASK-004")
```

### 3. Verify Imports Are Resolvable

Run a quick smoke check to confirm the package structure is importable before any logic is written:

```bash
cd backend
pip install -r requirements.txt
python -c "
from jose import jwt, JWTError
from cachetools import TTLCache
from authlib.integrations.httpx_client import AsyncOAuth2Client
from app.core.auth import oidc, tokens, jwt as auth_jwt
print('All auth imports OK')
"
```

Expected output: `All auth imports OK`

---

## Validation

```bash
cd backend
pip install -r requirements.txt
python -c "from jose import jwt; from cachetools import TTLCache; print('OK')"
```

Both commands must exit with code 0.

---

## Files Touched

| File | Action |
|---|---|
| `backend/requirements.txt` | Add `python-jose[cryptography]>=3.3.0`, `cachetools>=5.3.0`, `authlib>=1.3.0` |
| `backend/app/core/auth/__init__.py` | Create with package docstring |
| `backend/app/core/auth/oidc.py` | Create with stub functions |
| `backend/app/core/auth/tokens.py` | Create with stub function |
| `backend/app/core/auth/jwt.py` | Create with stub functions |

---

## Definition of Done Checklist

- [ ] `python-jose[cryptography]>=3.3.0` present in `backend/requirements.txt`
- [ ] `cachetools>=5.3.0` present in `backend/requirements.txt`
- [ ] `authlib>=1.3.0` present in `backend/requirements.txt` (no duplicate if already exists)
- [ ] `backend/app/core/auth/__init__.py` exists
- [ ] `backend/app/core/auth/oidc.py` exists with `get_jwks_uri()` and `fetch_jwks()` stubs
- [ ] `backend/app/core/auth/tokens.py` exists with `validate_id_token()` stub
- [ ] `backend/app/core/auth/jwt.py` exists with `issue_app_jwt()` and `get_current_user()` stubs
- [ ] `pip install -r requirements.txt` succeeds in CI
- [ ] No hardcoded credentials in any committed file

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| US-007/TASK-001 | Upstream task | `cryptography` library already pinned; `python-jose[cryptography]` reuses same backend |
