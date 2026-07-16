---
id: TASK-003
title: "Implement `POST /api/v1/auth/patient/verify` — OTP Verification & JWT Issuance"
user_story: US-065
epic: EP-013
sprint: 2
layer: Backend / API
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-065/TASK-001, US-065/TASK-002]
---

# TASK-003: Implement `POST /api/v1/auth/patient/verify` — OTP Verification & JWT Issuance

> **Story:** US-065 | **Epic:** EP-013 | **Sprint:** 2 | **Layer:** Backend / API | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

This endpoint completes the OTP authentication flow. The patient submits the 6-digit code they received via SMS. The endpoint must:

1. Look up the Twilio verification SID from Redis using the portal token.
2. Call Twilio Verify `verification_checks.create()` to validate the code against Twilio's own hash store.
3. Track failed attempts in a Redis counter (`otp_failures:{otp_key}`); invalidate the OTP after 3 failures.
4. Return `401 Unauthorized` with `{"error": "otp_expired", ...}` if the Redis key no longer exists (TTL elapsed).
5. Return `401 Unauthorized` with `{"error": "invalid_otp", "attempts_remaining": N}` for wrong codes.
6. On success: delete the OTP and failures keys from Redis; issue a short-lived JWT for patient portal access.

The JWT is issued using the existing `app/core/auth/jwt.py` module (established in US-057/US-059 — `create_access_token`).

---

## Acceptance Criteria Addressed

| US-065 AC | Scenario |
|---|---|
| **Scenario 3** | Wrong OTP → `401` + `{"error": "invalid_otp", "attempts_remaining": N}`; Redis counter increments; OTP invalidated at 3 failures |
| **Scenario 4** | OTP expired (TTL elapsed) → `401` + `{"error": "otp_expired", "message": "Please request a new code"}`; no JWT issued |
| **DoD** | Fetch hash from Redis; call Twilio `verification_checks.create()`; issue JWT on success |

---

## Implementation Steps

### 1. Create `backend/app/routers/auth_patient_verify.py`

```python
"""
POST /api/v1/auth/patient/verify

Verifies the patient-submitted OTP code against Twilio Verify and
issues a JWT on success.

References: US-065 AC Scenario 3 & 4, AIR-043, SEC-003.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.auth.jwt import create_access_token
from app.core.auth.portal_token import validate_portal_token, PortalTokenClaims
from app.core.auth.otp_helpers import (
    otp_redis_key,
    failures_redis_key,
    rate_limit_redis_key,
    MAX_FAILED_ATTEMPTS,
    OTP_TTL_SECONDS,
)
from app.core.config import settings
from app.dependencies.redis import get_redis
from app.dependencies.twilio import get_twilio_client

router = APIRouter(prefix="/auth/patient", tags=["Patient Auth"])


class OTPVerifyRequest(BaseModel):
    portal_token: str
    otp_code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


@router.post("/verify")
async def verify_otp(
    body: OTPVerifyRequest,
    redis=Depends(get_redis),
    twilio=Depends(get_twilio_client),
) -> dict:
    """Verify the OTP code and return a JWT on success.

    Possible error responses:
    - 401 otp_expired  — Redis TTL elapsed (key absent)
    - 401 invalid_otp  — Wrong code; includes remaining attempts
    - 401 invalid_otp  — No attempts remaining (OTP invalidated)
    """
    # 1. Validate portal token
    claims: PortalTokenClaims = validate_portal_token(body.portal_token)
    phone: str = claims.phone_number

    otp_key = otp_redis_key(body.portal_token)
    fail_key = failures_redis_key(body.portal_token)

    # 2. Check OTP session exists in Redis (expiry guard — AC Scenario 4)
    verification_sid: bytes | None = await redis.get(otp_key)
    if verification_sid is None:
        raise HTTPException(
            status_code=401,
            detail={"error": "otp_expired", "message": "Please request a new code"},
        )

    # 3. Check failure counter — prevent brute-force even if Redis key present
    failure_count: int = int(await redis.get(fail_key) or 0)
    if failure_count >= MAX_FAILED_ATTEMPTS:
        # OTP was already invalidated on the 3rd failure; treat as expired
        await redis.delete(otp_key, fail_key)
        raise HTTPException(
            status_code=401,
            detail={"error": "otp_expired", "message": "Please request a new code"},
        )

    # 4. Verify code with Twilio Verify (Twilio owns the hash)
    check = twilio.verify.v2.services(
        settings.TWILIO_VERIFY_SID
    ).verification_checks.create(
        to=phone,
        code=body.otp_code,
    )

    if check.status != "approved":
        # 5. Increment failure counter with OTP TTL so counter expires with OTP
        new_failures: int = await redis.incr(fail_key)
        if new_failures == 1:
            await redis.expire(fail_key, OTP_TTL_SECONDS)

        remaining: int = MAX_FAILED_ATTEMPTS - new_failures

        if remaining <= 0:
            # Invalidate OTP immediately on 3rd failure (AC Scenario 3)
            await redis.delete(otp_key, fail_key)
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "invalid_otp",
                    "attempts_remaining": 0,
                },
            )

        raise HTTPException(
            status_code=401,
            detail={
                "error": "invalid_otp",
                "attempts_remaining": remaining,
            },
        )

    # 6. OTP verified — clean up Redis and issue JWT
    await redis.delete(otp_key, fail_key)

    access_token = create_access_token(
        subject=claims.patient_id,
        extra_claims={"role": "PATIENT", "phone": phone},
    )

    return {"access_token": access_token, "token_type": "bearer"}
```

### 2. Register router in `backend/app/main.py`

```python
from app.routers.auth_patient_verify import router as patient_verify_router

app.include_router(patient_verify_router, prefix="/api/v1")
```

---

## Validation

```bash
# Happy path — valid code (requires Twilio test credentials with magic code "000000")
curl -X POST http://localhost:8000/api/v1/auth/patient/verify \
  -H "Content-Type: application/json" \
  -d '{"portal_token": "<valid-token>", "otp_code": "000000"}'
# Expected: HTTP 200 {"access_token": "...", "token_type": "bearer"}

# Wrong code — first attempt
curl -X POST http://localhost:8000/api/v1/auth/patient/verify \
  -H "Content-Type: application/json" \
  -d '{"portal_token": "<valid-token>", "otp_code": "999999"}'
# Expected: HTTP 401 {"error": "invalid_otp", "attempts_remaining": 2}

# Expired token — request verify after Redis TTL elapsed
# Expected: HTTP 401 {"error": "otp_expired", "message": "Please request a new code"}
```

---

## Files Touched

| File | Action |
|---|---|
| `backend/app/routers/auth_patient_verify.py` | Create |
| `backend/app/main.py` | Register router |

---

## Definition of Done Checklist

- [ ] `POST /api/v1/auth/patient/verify` calls Twilio `verification_checks.create()`
- [ ] Missing Redis key → `401` with `{"error": "otp_expired"}`
- [ ] Wrong code → `401` with `{"error": "invalid_otp", "attempts_remaining": N}`
- [ ] `otp_failures:{otp_key}` counter incremented on each failure; TTL matches OTP TTL
- [ ] After 3 failures: both `otp:` and `otp_failures:` keys deleted; subsequent verify returns expired
- [ ] On success: both keys deleted; JWT issued using `create_access_token`
- [ ] No OTP code or plaintext phone stored in Redis at any point
