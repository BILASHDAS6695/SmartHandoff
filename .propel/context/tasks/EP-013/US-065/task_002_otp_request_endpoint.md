---
id: TASK-002
title: "Implement `POST /api/v1/auth/patient/otp` — OTP Request Endpoint"
user_story: US-065
epic: EP-013
sprint: 2
layer: Backend / API
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-065/TASK-001]
---

# TASK-002: Implement `POST /api/v1/auth/patient/otp` — OTP Request Endpoint

> **Story:** US-065 | **Epic:** EP-013 | **Sprint:** 2 | **Layer:** Backend / API | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

This endpoint is the patient-facing OTP request trigger. It must:

1. Validate the incoming `portal_token` (issued by the patient portal auth flow — US-052).
2. Enforce rate limiting (max 5 OTPs per phone per hour) **before** calling Twilio, to prevent SMS cost abuse and credential enumeration.
3. Call Twilio Verify `verifications.create()` (not raw Twilio SMS) to send the 6-digit code.
4. Store a bcrypt hash of the OTP in Redis with a 10-minute TTL.
5. Return `202 Accepted` (no OTP value in the response body).

The endpoint is on the `auth` router, which is already registered at `/api/v1/auth` (established in the auth infrastructure from US-057/US-059). Twilio credentials (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_VERIFY_SID`) are sourced from GCP Secret Manager via `settings` (provisioned in US-064).

---

## Acceptance Criteria Addressed

| US-065 AC | Scenario |
|---|---|
| **Scenario 1** | Twilio Verify sends SMS within 30 s; OTP hash in Redis TTL=600s; returns `202 Accepted` |
| **Scenario 2** | 6th request in 60 min → `429 Too Many Requests` + `Retry-After: 3600`; no Twilio call |
| **DoD** | Rate limit key: `otp_rate:{phone_hash}` TTL=3600 s; OTP hash stored (not plaintext) |

---

## Implementation Steps

### 1. Create `backend/app/routers/auth_patient_otp.py`

```python
"""
POST /api/v1/auth/patient/otp

Sends a Twilio Verify OTP to the phone number associated with the
validated portal token.  Rate-limited to 5 requests/phone/hour.

References: US-065 AC Scenario 1 & 2, AIR-043, SEC-003.
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from app.core.auth.portal_token import validate_portal_token, PortalTokenClaims
from app.core.auth.otp_helpers import (
    otp_redis_key,
    rate_limit_redis_key,
    hash_otp,
    OTP_TTL_SECONDS,
    RATE_LIMIT_TTL_SECONDS,
    RATE_LIMIT_MAX,
)
from app.core.config import settings
from app.dependencies.redis import get_redis          # AsyncRedis client
from app.dependencies.twilio import get_twilio_client  # Twilio Client

router = APIRouter(prefix="/auth/patient", tags=["Patient Auth"])


class OTPRequest(BaseModel):
    portal_token: str


@router.post("/otp", status_code=202)
async def request_otp(
    body: OTPRequest,
    response: Response,
    redis=Depends(get_redis),
    twilio=Depends(get_twilio_client),
) -> dict:
    """Request an OTP code delivered via Twilio Verify SMS.

    Returns 202 Accepted on success.
    Returns 429 Too Many Requests if the rate limit is exceeded.
    """
    # 1. Validate portal token and extract phone number
    claims: PortalTokenClaims = validate_portal_token(body.portal_token)
    phone: str = claims.phone_number

    # 2. Rate limit check — BEFORE calling Twilio (AC Scenario 2)
    rate_key = rate_limit_redis_key(phone)
    current_count: int = await redis.incr(rate_key)

    if current_count == 1:
        # First request in the window — set TTL
        await redis.expire(rate_key, RATE_LIMIT_TTL_SECONDS)

    if current_count > RATE_LIMIT_MAX:
        ttl: int = await redis.ttl(rate_key)
        retry_after = ttl if ttl > 0 else RATE_LIMIT_TTL_SECONDS
        raise HTTPException(
            status_code=429,
            detail="Too many OTP requests. Please wait before trying again.",
            headers={"Retry-After": str(retry_after)},
        )

    # 3. Send OTP via Twilio Verify (AC Scenario 1)
    verification = twilio.verify.v2.services(
        settings.TWILIO_VERIFY_SID
    ).verifications.create(to=phone, channel="sms")

    if verification.status not in ("pending", "approved"):
        raise HTTPException(
            status_code=502,
            detail="OTP delivery failed. Please try again.",
        )

    # 4. Store bcrypt hash of the Twilio-generated OTP in Redis
    #    Twilio Verify manages the actual code; we hash the SID as the
    #    session anchor so the verify endpoint can locate the right session.
    #    The OTP code itself is verified by Twilio in TASK-003.
    otp_key = otp_redis_key(body.portal_token)
    await redis.set(otp_key, verification.sid, ex=OTP_TTL_SECONDS)

    return {"status": "otp_sent"}
```

> **Note on bcrypt storage:** Twilio Verify owns the OTP code and its own internal hash. Our Redis entry stores the Twilio **verification SID** (not the code) as the session anchor for the verify step. The verification SID is non-sensitive (not the code) and expires with the OTP TTL. This is the correct Twilio Verify integration pattern — the raw OTP is never transmitted back to our server, so bcrypt-hashing an OTP we never receive is not applicable here. The DoD item "bcrypt stored, NOT plaintext" applies to the `POST /verify` flow (TASK-003) where Twilio returns the verified status.

### 2. Register router in `backend/app/main.py`

```python
from app.routers.auth_patient_otp import router as patient_otp_router

app.include_router(patient_otp_router, prefix="/api/v1")
```

### 3. Create `backend/app/dependencies/twilio.py`

```python
"""Twilio client dependency — singleton per process."""

from functools import lru_cache
from twilio.rest import Client
from app.core.config import settings


@lru_cache(maxsize=1)
def _twilio_client() -> Client:
    return Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)


async def get_twilio_client() -> Client:
    return _twilio_client()
```

### 4. Add Twilio settings to `app/core/config.py`

```python
# In Settings class (sourced from Secret Manager via env injection)
TWILIO_ACCOUNT_SID: str
TWILIO_AUTH_TOKEN: str
TWILIO_VERIFY_SID: str   # Service SID from the Twilio Verify product
```

### 5. Add `twilio` to `requirements.txt`

```
twilio>=9.0.0
```

---

## Validation

```bash
# Integration smoke test (requires Redis + Twilio test credentials)
curl -X POST http://localhost:8000/api/v1/auth/patient/otp \
  -H "Content-Type: application/json" \
  -d '{"portal_token": "<valid-test-portal-token>"}'
# Expected: HTTP 202 {"status": "otp_sent"}

# Rate limit test — repeat 6 times with same portal token
for i in $(seq 1 6); do
  curl -s -o /dev/null -w "%{http_code}\n" \
    -X POST http://localhost:8000/api/v1/auth/patient/otp \
    -H "Content-Type: application/json" \
    -d '{"portal_token": "<valid-test-portal-token>"}'
done
# Expected last response: 429
```

---

## Files Touched

| File | Action |
|---|---|
| `backend/app/routers/auth_patient_otp.py` | Create |
| `backend/app/dependencies/twilio.py` | Create |
| `backend/app/main.py` | Register router |
| `backend/app/core/config.py` | Add Twilio + Verify SID settings |
| `backend/requirements.txt` | Add `twilio>=9.0.0` |

---

## Definition of Done Checklist

- [ ] `POST /api/v1/auth/patient/otp` returns `202 Accepted` on valid request
- [ ] Twilio `verifications.create()` called with `channel="sms"`
- [ ] Verification SID stored in Redis key `otp:{SHA-256(portal_token)}` with TTL=600s
- [ ] Rate limit counter incremented at `otp_rate:{phone_hash}` with TTL=3600s
- [ ] 6th request within the window returns `429` with `Retry-After` header
- [ ] No OTP code or plaintext phone number stored in Redis keys
- [ ] Twilio credentials sourced from `settings` (Secret Manager) — no hardcoded values
