---
id: TASK-003
title: "Implement `id_token` Signature Validation and `amr` MFA Enforcement in `app/core/auth/tokens.py`"
user_story: US-056
epic: EP-011
sprint: 1
layer: Backend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-056/TASK-002]
---

# TASK-003: Implement `id_token` Signature Validation and `amr` MFA Enforcement in `app/core/auth/tokens.py`

> **Story:** US-056 | **Epic:** EP-011 | **Sprint:** 1 | **Layer:** Backend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

Once the JWKS is available (TASK-002), the backend must validate the OIDC `id_token` presented by Angular after the IdP redirect. This task implements two responsibilities in `app/core/auth/tokens.py`:

1. **Signature validation** — decode and verify the `id_token` JWT against the cached JWKS using `python-jose`, checking issuer, audience, expiry, and algorithm.
2. **`amr` MFA enforcement** — after signature validation, check that the `amr` claim contains the string `"mfa"` (AIR-033). If absent, return `401 Unauthorized` with message `"MFA required"` (AC Scenario 2).

The `POST /api/v1/auth/token` endpoint (TASK-004) calls `validate_id_token()` as its first step.

Design.md Section 8.2 specifies the `amr` check: *"Backend validates `amr` claim includes `mfa` for all staff roles"*.

---

## Acceptance Criteria Addressed

| US-056 AC | Requirement |
|---|---|
| **Scenario 1** | FastAPI validates OIDC `id_token`, checks `amr` claim contains `mfa` |
| **Scenario 2** | `amr: ["password"]` (no MFA) → 401 Unauthorized with message "MFA required" |
| **DoD** | FastAPI OIDC middleware: `id_token` signature validation, `amr` claim check |

---

## Implementation Steps

### 1. Implement `backend/app/core/auth/tokens.py`

Replace the TASK-001 stub entirely:

```python
"""OIDC id_token validation and amr MFA enforcement.

Validates a staff member's OIDC id_token against the cached JWKS (TASK-002)
and enforces MFA by checking the amr claim (AIR-033, SEC-001).

The id_token is a short-lived JWT issued by the hospital identity provider
after a successful OIDC authorisation code flow. Angular sends this token
to POST /api/v1/auth/token; the backend validates it here before issuing
the application JWT.

Security requirements:
    - Signature verified against JWKS (RS256 expected from enterprise IdP)
    - Issuer must match IDP_BASE_URL (prevents token substitution attacks)
    - Audience must match OIDC_CLIENT_ID (prevents id_token reuse from another app)
    - expiry enforced by python-jose (raises JWTError on exp violation)
    - amr claim must contain "mfa" — missing MFA → 401 (AIR-033)
"""
from __future__ import annotations

import logging
import os

from fastapi import HTTPException, status
from jose import JWTError, jwk, jwt

from app.core.auth.oidc import fetch_jwks

logger = logging.getLogger(__name__)


def _oidc_client_id() -> str:
    """Return OIDC_CLIENT_ID from environment."""
    client_id = os.environ.get("OIDC_CLIENT_ID", "")
    if not client_id:
        raise RuntimeError(
            "OIDC_CLIENT_ID environment variable is not set."
        )
    return client_id


def _idp_issuer() -> str:
    """Return the expected issuer (same as IDP_BASE_URL without trailing slash)."""
    issuer = os.environ.get("IDP_BASE_URL", "").rstrip("/")
    if not issuer:
        raise RuntimeError("IDP_BASE_URL environment variable is not set.")
    return issuer


def _extract_public_keys(jwks: dict) -> list[dict]:
    """Extract individual JWK key dicts from a JWKS document."""
    return jwks.get("keys", [])


async def validate_id_token(id_token: str) -> dict:
    """Validate the OIDC id_token and enforce MFA via amr claim.

    Steps:
        1. Fetch cached JWKS (no network call on cache hit).
        2. Decode and verify id_token signature, issuer, audience, expiry.
        3. Check amr claim contains "mfa".
        4. Return the decoded claims dict.

    Args:
        id_token: The raw OIDC id_token JWT string received from the Angular
                  callback after IdP redirect.

    Returns:
        dict: Decoded and verified claims from the id_token.

    Raises:
        HTTPException 401: If the token is invalid, expired, has wrong issuer/
                           audience, or is missing the mfa amr claim.
    """
    # 1. Fetch JWKS (TTL-cached by TASK-002)
    try:
        jwks = await fetch_jwks()
    except RuntimeError as exc:
        logger.error("JWKS fetch failed during id_token validation: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable",
        ) from exc

    keys = _extract_public_keys(jwks)
    if not keys:
        logger.error("JWKS returned empty key set")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable",
        )

    # 2. Decode and verify the id_token
    # python-jose will try each key in the JWKS until one verifies the signature
    claims: dict | None = None
    last_error: JWTError | None = None

    for key_data in keys:
        try:
            public_key = jwk.construct(key_data)
            claims = jwt.decode(
                id_token,
                public_key,
                algorithms=["RS256"],
                audience=_oidc_client_id(),
                issuer=_idp_issuer(),
                options={"verify_exp": True},
            )
            break  # Signature verified
        except JWTError as exc:
            last_error = exc
            continue

    if claims is None:
        logger.warning(
            "id_token validation failed: %s",
            str(last_error),
            extra={"event_type": "auth_failure", "reason": "invalid_token"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired identity token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. Enforce MFA via amr claim (AIR-033, SEC-001, AC Scenario 2)
    amr: list[str] = claims.get("amr", [])
    if "mfa" not in amr:
        logger.warning(
            "id_token rejected: amr claim %r does not contain 'mfa'",
            amr,
            extra={"event_type": "auth_failure", "reason": "mfa_required"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="MFA required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.info(
        "id_token validated successfully for sub=%s",
        claims.get("sub", "unknown"),
        extra={"event_type": "auth_success"},
    )
    return claims
```

### 2. Add `OIDC_CLIENT_ID` to Cloud Run Environment Variable Spec

`OIDC_CLIENT_ID` is the OAuth2 client ID registered with the hospital IdP. It is **not** a secret (it is a public identifier in the OIDC spec), so it is passed as a plain env var, not from Secret Manager.

In each environment's `terraform.tfvars.example`:

```
oidc_client_id = "smarthandoff-api-gateway"
```

Add to each environment's `variables.tf`:

```hcl
variable "oidc_client_id" {
  type        = string
  description = "OIDC client ID registered with the hospital identity provider"
}
```

Pass to `api-gateway` Cloud Run `env_vars` alongside `IDP_BASE_URL`:

```hcl
env_vars = {
  IDP_BASE_URL   = var.idp_base_url
  OIDC_CLIENT_ID = var.oidc_client_id
}
```

---

## Validation

```bash
cd backend

# 1. Confirm imports resolve
python -c "from app.core.auth.tokens import validate_id_token; print('Import OK')"

# 2. Confirm MFA enforcement is explicit
grep -n '"mfa" not in amr' backend/app/core/auth/tokens.py
# Expected: one match

# 3. Confirm 401 detail text matches AC exactly
grep -n '"MFA required"' backend/app/core/auth/tokens.py
# Expected: one match
```

---

## Files Touched

| File | Action |
|---|---|
| `backend/app/core/auth/tokens.py` | Replace TASK-001 stub with full implementation |
| `infra/terraform/environments/dev/variables.tf` | Add `oidc_client_id` variable |
| `infra/terraform/environments/dev/terraform.tfvars.example` | Add `oidc_client_id` example |
| `infra/terraform/environments/dev/main.tf` | Add `OIDC_CLIENT_ID` to api-gateway env_vars |
| `infra/terraform/environments/staging/variables.tf` | Same as dev |
| `infra/terraform/environments/staging/terraform.tfvars.example` | Same as dev |
| `infra/terraform/environments/staging/main.tf` | Same as dev |
| `infra/terraform/environments/prod/variables.tf` | Same as dev |
| `infra/terraform/environments/prod/terraform.tfvars.example` | Same as dev |
| `infra/terraform/environments/prod/main.tf` | Same as dev |

---

## Definition of Done Checklist

- [ ] `app/core/auth/tokens.py` fully implemented (not a stub)
- [ ] Signature verified against JWKS with `RS256` algorithm
- [ ] Issuer validated against `IDP_BASE_URL`
- [ ] Audience validated against `OIDC_CLIENT_ID`
- [ ] `amr` missing or not containing `"mfa"` → `HTTP 401` with detail `"MFA required"`
- [ ] JWT expiry validated (`verify_exp=True`)
- [ ] No PHI logged — only `sub` (user ID) appears in log messages
- [ ] `OIDC_CLIENT_ID` Terraform variable added to all three environments

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| US-056/TASK-002 | Upstream task | `fetch_jwks()` must be implemented before `validate_id_token()` can call it |
