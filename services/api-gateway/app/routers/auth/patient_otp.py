"""POST /api/v1/auth/patient/otp — OTP generation endpoint (US-052 TASK-002).

Generates a 6-digit OTP, stores its bcrypt hash in Redis (TTL=600s),
enforces rate limiting (max 5 attempts per hour), and triggers Twilio
OTP delivery via the Notification Service (US-064).

Design refs:
    US-052 AC Scenario 2 — rate limit: block on 6th attempt
    US-052 Technical Notes — bcrypt hash; secrets.randbelow; Redis key names
    design.md §3.1 Notification Service — OTP delivery via Twilio Verify
    US-064 — Twilio OTP delivery service
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from api_gateway.app.core.auth.portal_token import decode_portal_token
from api_gateway.app.core.redis import get_redis
from api_gateway.app.services.otp_service import (
    delete_otp_hash,
    generate_otp,
    get_remaining_attempts,
    hash_otp,
    increment_attempt_counter,
    is_rate_limited,
    store_otp_hash,
)
from api_gateway.app.services.notification_client import send_otp_notification

router = APIRouter(prefix="/api/v1/auth/patient", tags=["Patient Auth"])
log = logging.getLogger(__name__)


class OtpRequest(BaseModel):
    """Request body for POST /api/v1/auth/patient/otp."""
    portal_token: str = Field(..., description="Signed JWT from patient SMS link")


class OtpResponse(BaseModel):
    """Response body for POST /api/v1/auth/patient/otp."""
    message: str = Field(..., description="Confirmation message")


@router.post(
    "/otp",
    response_model=OtpResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate and send OTP to patient phone",
)
async def generate_otp_endpoint(
    body: OtpRequest,
    redis: Redis = Depends(get_redis),
) -> OtpResponse:
    """Generate a 6-digit OTP and send it via SMS (US-052 TASK-002).

    Request flow:
        1. Decode portal_token → extract patient_id, encounter_id
        2. Check rate limit — block if ≥ 5 attempts in the last 1 hour
        3. Generate OTP: secrets.randbelow(1_000_000), zero-padded
        4. Hash OTP with bcrypt (12 rounds)
        5. Store hash in Redis: otp:{portal_token}, TTL=600s
        6. Increment attempt counter: otp_attempts:{portal_token}, TTL=3600s
        7. Trigger Notification Service: POST /internal/notify/otp
        8. Return 200 {"message": "OTP sent..."}

    Rate limit (AC Scenario 2):
        - Key: otp_attempts:{portal_token}
        - Block at count ≥ 5 (6th request onwards)
        - Response: 429 with Retry-After header

    Args:
        body: OtpRequest with portal_token
        redis: Async Redis client for OTP and counter storage

    Returns:
        OtpResponse with confirmation message

    Raises:
        HTTPException 400 — invalid/malformed portal_token
        HTTPException 401 — expired portal_token
        HTTPException 429 — rate limit exceeded (5 OTP requests in 1 hour)
    """
    # 1. Decode portal token (raises 401 if expired or invalid)
    try:
        portal_claims = decode_portal_token(body.portal_token)
    except HTTPException:
        raise

    patient_id = portal_claims.patient_id
    encounter_id = portal_claims.encounter_id

    # 2. Check rate limit — block if 5 or more attempts in the last 1 hour
    is_blocked, retry_after = await is_rate_limited(redis, body.portal_token)
    if is_blocked:
        log.warning("otp_rate_limit_exceeded")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many OTP requests. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    # 3 & 4. Generate and hash OTP
    otp_plaintext = generate_otp()
    otp_hash = hash_otp(otp_plaintext)

    # 5. Store hashed OTP in Redis with 10-minute TTL
    await store_otp_hash(redis, body.portal_token, otp_hash)

    # 6. Increment rate limit counter
    await increment_attempt_counter(redis, body.portal_token)

    # 7. Trigger Notification Service to send OTP via Twilio (US-064)
    success = await send_otp_notification(
        patient_id=patient_id,
        otp=otp_plaintext,
    )

    if not success:
        # Log warning but don't fail the request — OTP is stored and can be retried
        # Notification delivery is handled asynchronously by the Notification Service
        log.warning(
            "otp_notification_dispatch_failed",
            extra={"encounter_id": encounter_id},
        )

    remaining = await get_remaining_attempts(redis, body.portal_token)
    log.info(
        "otp_requests_remaining",
        extra={
            "remaining_attempts": remaining,
            "encounter_id": encounter_id,
        },
    )

    return OtpResponse(message="OTP sent. Check your SMS.")
