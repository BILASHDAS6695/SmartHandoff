---
id: TASK-001
title: "Portal Token Validator — Decode & Validate Signed JWT in SMS Link"
user_story: US-052
epic: EP-010
sprint: 2
layer: Backend / Middleware
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [SEC-003, AIR-043]
---

# TASK-001: Portal Token Validator — Decode & Validate Signed JWT in SMS Link

> **Story:** US-052 | **Epic:** EP-010 | **Sprint:** 2 | **Layer:** Backend / Middleware | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

The SMS sent to a discharged patient contains a unique portal link such as:

```
https://app.smarthandoff.health/portal?token=<portal_token>
```

The `portal_token` is a **signed JWT** (HS256) — not a UUID — that encodes:

| Claim | Value |
|---|---|
| `sub` | `patient_id` (UUID) |
| `encounter_id` | `encounter_id` (UUID) |
| `exp` | `now + 24 hours` |
| `purpose` | `"portal_access"` |

This task implements `decode_portal_token()` — the shared utility consumed by both
`POST /api/v1/auth/patient/otp` (TASK-002) and `POST /api/v1/auth/patient/verify`
(TASK-003). It validates the signature and expiry of the portal token **before** any
OTP generation or Redis interaction occurs.

**Design references:**

- design.md §8.2 — patient JWT scoping; portal token carries `encounter_id`
- design.md §3.3 — middleware stack: JWT Validator runs before RBAC enforcer
- US-052 Technical Notes — "Portal token: signed JWT in the SMS link (not a UUID); encodes `patient_id` + `encounter_id` + 24h expiry"
- SEC-003 — all tokens signed with secret from GCP Secret Manager

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|---|---|
| Scenario 1 | Portal token decoded to extract `patient_id` + `encounter_id` before OTP flow |
| Scenario 3 | Expired portal token rejected with 401 before reaching OTP handler |
| Scenario 4 | `encounter_id` extracted from portal token — used downstream for scope enforcement |

---

## Implementation Steps

### 1. Create module structure

```bash
mkdir -p api-gateway/app/core/auth
touch api-gateway/app/core/auth/portal_token.py
touch api-gateway/app/core/auth/__init__.py
```

### 2. Implement `api-gateway/app/core/auth/portal_token.py`

```python
"""Portal token decoder for patient SMS-link authentication (US-052).

The portal token is a HS256-signed JWT embedded in the SMS link sent to
discharged patients. It encodes patient_id, encounter_id, and a 24-hour
expiry. This utility is consumed by:

    - POST /api/v1/auth/patient/otp   (TASK-002) — before OTP generation
    - POST /api/v1/auth/patient/verify (TASK-003) — before OTP verification

Design refs:
    US-052 Technical Notes — portal token structure
    design.md §8.2 — patient JWT encounter scope
    SEC-003 — signing secret from GCP Secret Manager
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import HTTPException, status
from jose import ExpiredSignatureError, JWTError, jwt

from api_gateway.app.core.config import settings  # PORTAL_TOKEN_SECRET

log = logging.getLogger(__name__)

_ALGORITHM = "HS256"
_PURPOSE = "portal_access"


@dataclass(frozen=True, slots=True)
class PortalTokenClaims:
    """Decoded and validated claims extracted from a portal token."""

    patient_id: str       # UUID string
    encounter_id: str     # UUID string


def decode_portal_token(raw_token: str) -> PortalTokenClaims:
    """Decode and validate the portal JWT from the patient's SMS link.

    Validates:
        - HS256 signature using PORTAL_TOKEN_SECRET from Secret Manager
        - Token expiry (24-hour window set at send time)
        - `purpose` claim equals "portal_access" (prevents reuse of
          patient JWTs issued by /verify as portal tokens)

    Returns:
        PortalTokenClaims with patient_id and encounter_id strings.

    Raises:
        HTTPException 401 — expired token, invalid signature, or missing claims.
        HTTPException 400 — malformed JWT structure.

    Security note:
        All error paths return the same 401 message to prevent token
        structure enumeration (OWASP A01).
    """
    try:
        payload = jwt.decode(
            raw_token,
            settings.PORTAL_TOKEN_SECRET,
            algorithms=[_ALGORITHM],
        )
    except ExpiredSignatureError:
        log.warning("portal_token_expired")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Portal link has expired. Please request a new link from your care team.",
        )
    except JWTError:
        log.warning("portal_token_invalid")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid portal link. Please use the link from your SMS.",
        )

    # Validate purpose claim — prevents patient JWTs from being used as portal tokens
    if payload.get("purpose") != _PURPOSE:
        log.warning("portal_token_wrong_purpose", extra={"purpose": payload.get("purpose")})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid portal link. Please use the link from your SMS.",
        )

    patient_id: str | None = payload.get("sub")
    encounter_id: str | None = payload.get("encounter_id")

    if not patient_id or not encounter_id:
        log.warning("portal_token_missing_claims")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid portal link. Please use the link from your SMS.",
        )

    log.info(
        "portal_token_decoded",
        extra={"encounter_id": encounter_id},
        # patient_id intentionally omitted from structured logs (PHI)
    )

    return PortalTokenClaims(patient_id=patient_id, encounter_id=encounter_id)
```

### 3. Add `PORTAL_TOKEN_SECRET` to settings

```python
# In api-gateway/app/core/config.py — extend existing Settings class

class Settings(BaseSettings):
    # ... existing fields ...

    # Loaded from GCP Secret Manager via Secret Manager environment injection
    # Secret name: smarthandoff-portal-token-secret
    PORTAL_TOKEN_SECRET: str = Field(..., description="HS256 signing secret for portal tokens")
```

### 4. Add secret to GCP Secret Manager (Terraform)

```hcl
# In infra/terraform/modules/secrets/main.tf — add alongside existing secrets

resource "google_secret_manager_secret" "portal_token_secret" {
  secret_id = "smarthandoff-portal-token-secret"
  project   = var.project_id

  replication {
    auto {}
  }

  labels = {
    service     = "api-gateway"
    sensitivity = "high"
    purpose     = "portal-token-signing"
  }
}
```

---

## Validation Checklist

- [ ] `python -m py_compile api-gateway/app/core/auth/portal_token.py` — zero errors
- [ ] Valid portal token (not expired, correct purpose) → returns `PortalTokenClaims` with correct `patient_id` and `encounter_id`
- [ ] Expired portal token → HTTP 401 with message "Portal link has expired..."
- [ ] Tampered signature → HTTP 401 with message "Invalid portal link..."
- [ ] Token missing `encounter_id` claim → HTTP 401
- [ ] Patient-scoped JWT passed as portal token (wrong `purpose` claim) → HTTP 401
- [ ] `patient_id` does NOT appear in any structured log field (PHI safety)

---

## Dependencies

| Dependency | Type | Reason |
|---|---|---|
| `python-jose[cryptography]` | Package | JWT decode (already in project per design.md §4.1) |
| `PORTAL_TOKEN_SECRET` | GCP Secret Manager | HS256 signing key injected at Cloud Run deploy time |
| `api_gateway.app.core.config.Settings` | Module | Existing settings class; extend with new field |
