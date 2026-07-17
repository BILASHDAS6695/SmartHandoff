---
id: TASK-003
title: "POST /api/v1/auth/patient/verify — Validate OTP Hash & Issue Patient-Scoped JWT"
user_story: US-052
epic: EP-010
sprint: 2
layer: Backend / API
estimate: 2.5h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-052/TASK-001, US-052/TASK-002]
---

# TASK-003: POST /api/v1/auth/patient/verify — Validate OTP Hash & Issue Patient-Scoped JWT

> **Story:** US-052 | **Epic:** EP-010 | **Sprint:** 2 | **Layer:** Backend / API | **Est:** 2.5 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This task implements `POST /api/v1/auth/patient/verify` — the second step in the OTP
passwordless flow. The patient enters the 6-digit OTP in the Angular `PatientOtpComponent`
(TASK-005), which calls this endpoint.

### Endpoint behaviour

```
POST /api/v1/auth/patient/verify
Body: { "portal_token": "<signed_jwt>", "otp": "123456" }

1. Decode portal_token → extract patient_id, encounter_id (TASK-001)
2. GET otp:{portal_token} from Redis
   → key missing / TTL expired → 401 "OTP has expired. Please request a new code."
3. bcrypt.checkpw(otp, stored_hash)
   → mismatch → 401 "Invalid OTP. Please try again."
4. DELETE otp:{portal_token} from Redis (one-time use)
5. Issue patient JWT:
     {sub: patient_id, encounter_id, exp: now+3600, role: "patient"}
6. Write HIPAA audit event: {encounter_id, event="PATIENT_AUTH_SUCCESS"}
7. Return HTTP 200 {"access_token": "<jwt>", "token_type": "bearer", "expires_in": 3600}
```

**JWT claims (US-052 DoD):**

| Claim | Value |
|---|---|
| `sub` | `patient_id` (UUID string) |
| `encounter_id` | encounter UUID string |
| `role` | `"patient"` |
| `exp` | `now + 3600` seconds (60 minutes) |
| Algorithm | HS256 |

**Expiry handling (US-052 AC Scenario 3):**

Redis key `otp:{portal_token}` is set with TTL=600 s by TASK-002.
If the patient submits the OTP after 10 minutes, the key will be absent from Redis.
The endpoint returns `401` with the exact message:
`"OTP has expired. Please request a new code."`

**Design references:**

- US-052 Technical Notes — bcrypt.checkpw; JWT claims; HS256
- US-052 AC Scenario 1 — JWT returned within 30 s of SMS link tap
- US-052 AC Scenario 3 — expired OTP → 401 with specific message
- US-052 AC Scenario 4 — JWT carries encounter_id claim for downstream enforcement
- design.md §8.2 — patient JWT scope; encounter_id claim required
- design.md §10.1 — HIPAA audit: encounter_id + event type; no OTP value in log

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|---|---|
| Scenario 1 | JWT issued on successful OTP match; 60-minute expiry; `encounter_id` claim present |
| Scenario 3 | Redis key absent after TTL expiry → 401 "OTP has expired. Please request a new code." |
| Scenario 4 | JWT contains `encounter_id` claim used by `PatientEncounterScopeMiddleware` (TASK-004) |

---

## Implementation Steps

### 1. Create module

```bash
touch api-gateway/app/routers/auth/patient_verify.py
touch api-gateway/app/services/patient_jwt_service.py
```

### 2. Implement `api-gateway/app/services/patient_jwt_service.py`

```python
"""Patient JWT issuance for the OTP passwordless auth flow (US-052).

Issues a short-lived patient-scoped JWT after successful OTP verification.
The JWT encodes patient_id (sub), encounter_id, and role='patient'.

Design refs:
    US-052 DoD — HS256; sub=patient_id; encounter_id; exp=60 min
    US-052 AC Scenario 1 — JWT returned within 30 s of SMS tap
    US-052 AC Scenario 4 — encounter_id claim enforced by middleware (TASK-004)
    design.md §8.2 — patient JWT scope
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import jwt

from api_gateway.app.core.config import settings

_ALGORITHM = "HS256"
_EXPIRY_MINUTES = 60


def issue_patient_jwt(patient_id: str, encounter_id: str) -> str:
    """Issue a patient-scoped HS256 JWT with encounter_id and 60-minute expiry.

    Claims:
        sub          — patient_id (UUID string)
        encounter_id — encounter UUID string
        role         — "patient"
        exp          — UTC timestamp 60 minutes from now
        iat          — UTC timestamp now

    Returns:
        Signed JWT string.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": patient_id,
        "encounter_id": encounter_id,
        "role": "patient",
        "iat": now,
        "exp": now + timedelta(minutes=_EXPIRY_MINUTES),
    }
    return jwt.encode(payload, settings.PATIENT_JWT_SECRET, algorithm=_ALGORITHM)
```

### 3. Implement `api-gateway/app/routers/auth/patient_verify.py`

```python
"""POST /api/v1/auth/patient/verify — OTP verification + JWT issuance (US-052).

Validates the 6-digit OTP against the bcrypt hash stored in Redis by
POST /api/v1/auth/patient/otp (TASK-002), then issues a patient-scoped JWT.

Design refs:
    US-052 AC Scenario 1 — JWT issued within 30 s of SMS tap
    US-052 AC Scenario 3 — expired OTP → 401 "OTP has expired..."
    US-052 Technical Notes — bcrypt.checkpw; OTP not logged; one-time use
    design.md §8.2 — patient JWT encounter_id claim
    design.md §10.1 — HIPAA audit: encounter_id + event; no OTP in log
"""
from __future__ import annotations

import logging

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from api_gateway.app.core.auth.portal_token import PortalTokenClaims, decode_portal_token
from api_gateway.app.core.audit import write_audit_event
from api_gateway.app.core.redis import get_redis
from api_gateway.app.services.patient_jwt_service import issue_patient_jwt

router = APIRouter(prefix="/api/v1/auth/patient", tags=["Patient Auth"])
log = logging.getLogger(__name__)

_OTP_KEY_PREFIX = "otp:"


class VerifyRequest(BaseModel):
    portal_token: str
    otp: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 3600


@router.post(
    "/verify",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify OTP and issue patient-scoped JWT",
)
async def verify_otp(
    body: VerifyRequest,
    redis: Redis = Depends(get_redis),
) -> TokenResponse:
    """Validate OTP hash from Redis and issue a 60-minute patient JWT.

    Steps:
        1. Decode portal_token → extract patient_id, encounter_id
        2. Fetch OTP hash from Redis (key: otp:{portal_token})
        3. Absent key → 401 "OTP has expired..."
        4. bcrypt.checkpw — mismatch → 401 "Invalid OTP..."
        5. DELETE OTP key (one-time use)
        6. Issue patient JWT (sub, encounter_id, role, exp)
        7. Write HIPAA audit event
        8. Return TokenResponse

    Security:
        OTP plaintext is NEVER written to any log.
        OTP key deleted immediately after successful verification (one-time use).
        All 401 paths use distinct messages per US-052 Scenario 3 spec.
    """
    # Step 1 — validate portal token
    claims: PortalTokenClaims = decode_portal_token(body.portal_token)

    otp_redis_key = f"{_OTP_KEY_PREFIX}{body.portal_token}"

    # Step 2 — retrieve stored hash
    stored_hash: bytes | None = await redis.get(otp_redis_key)

    # Step 3 — absent = expired (key TTL elapsed)
    if stored_hash is None:
        log.info(
            "otp_expired_or_not_found",
            extra={"encounter_id": claims.encounter_id},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="OTP has expired. Please request a new code.",
        )

    # Step 4 — verify bcrypt hash
    otp_matches = bcrypt.checkpw(body.otp.encode(), stored_hash)
    if not otp_matches:
        log.warning(
            "otp_mismatch",
            extra={"encounter_id": claims.encounter_id},
            # submitted OTP value intentionally excluded from logs
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid OTP. Please try again.",
        )

    # Step 5 — delete OTP key (one-time use; prevent replay)
    await redis.delete(otp_redis_key)

    # Step 6 — issue patient JWT
    access_token = issue_patient_jwt(
        patient_id=claims.patient_id,
        encounter_id=claims.encounter_id,
    )

    # Step 7 — HIPAA audit log (no OTP value, no patient_id in log)
    await write_audit_event(
        event_type="PATIENT_AUTH_SUCCESS",
        encounter_id=claims.encounter_id,
        extra={},
    )

    log.info(
        "patient_auth_success",
        extra={"encounter_id": claims.encounter_id},
    )

    return TokenResponse(access_token=access_token)
```

### 4. Register routers in FastAPI app

```python
# In api-gateway/app/main.py — add both auth routers
from api_gateway.app.routers.auth.patient_otp import router as otp_router
from api_gateway.app.routers.auth.patient_verify import router as verify_router

app.include_router(otp_router)
app.include_router(verify_router)
```

### 5. Add `PATIENT_JWT_SECRET` to settings

```python
# In api-gateway/app/core/config.py — extend Settings

class Settings(BaseSettings):
    # ... existing fields ...

    # Loaded from GCP Secret Manager
    # Secret name: smarthandoff-patient-jwt-secret
    PATIENT_JWT_SECRET: str = Field(..., description="HS256 signing secret for patient JWTs")
```

---

## Validation Checklist

- [ ] `python -m py_compile api-gateway/app/routers/auth/patient_verify.py` — zero errors
- [ ] `python -m py_compile api-gateway/app/services/patient_jwt_service.py` — zero errors
- [ ] Correct OTP submitted within 10 min → HTTP 200 with `access_token` JWT
- [ ] Decoded JWT contains claims: `sub`, `encounter_id`, `role=patient`, `exp` (60 min from now)
- [ ] OTP Redis key deleted after successful verify (subsequent verify with same OTP → 401 expired)
- [ ] Redis key absent (expired TTL) → HTTP 401 `"OTP has expired. Please request a new code."`
- [ ] Wrong OTP submitted → HTTP 401 `"Invalid OTP. Please try again."`
- [ ] OTP value does NOT appear in any log entry
- [ ] `patient_id` does NOT appear in any log entry
- [ ] HIPAA audit event `PATIENT_AUTH_SUCCESS` written with `encounter_id`

---

## Dependencies

| Dependency | Type | Reason |
|---|---|---|
| US-052/TASK-001 | Task | `decode_portal_token()` |
| US-052/TASK-002 | Task | Redis key `otp:{portal_token}` written by OTP endpoint |
| `bcrypt` | Package | `checkpw()` for hash verification |
| `python-jose` | Package | JWT encoding |
| `PATIENT_JWT_SECRET` | GCP Secret Manager | HS256 signing key for patient JWTs |
