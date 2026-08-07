"""
POST /api/v1/auth/patient/otp — OTP Request Endpoint

Sends a Twilio Verify OTP to the phone number associated with the
validated portal token. Rate-limited to 5 requests/phone/hour.

References: US-065 AC Scenario 1 & 2, AIR-043, SEC-003.
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from app.core.auth.portal_token import validate_portal_token, PortalTokenClaims
from app.core.auth.otp_helpers import (
    otp_redis_key,
    rate_limit_redis_key,
    OTP_TTL_SECONDS,
    RATE_LIMIT_TTL_SECONDS,
    RATE_LIMIT_MAX,
)
from app.dependencies.redis import get_redis
from app.dependencies.twilio import get_twilio_client
from app.services.patient_notification_publisher import PatientNotificationPublisher

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/patient", tags=["Patient Auth"])


class OTPRequest(BaseModel):
    """Request body for OTP delivery."""

    portal_token: str
    """Portal authentication token containing phone number claim."""


def _get_twilio_verify_sid() -> str:
    """Return TWILIO_VERIFY_SID from environment.

    Raises:
        RuntimeError: If TWILIO_VERIFY_SID is not set.
    """
    sid = os.environ.get("TWILIO_VERIFY_SID", "")
    if not sid:
        raise RuntimeError(
            "TWILIO_VERIFY_SID environment variable is not set. "
            "Mount it from GCP Secret Manager."
        )
    return sid


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

    Args:
        body: Request containing the portal_token.
        response: FastAPI Response object (for setting headers).
        redis: Async Redis client dependency.
        twilio: Twilio REST API client dependency.

    Returns:
        dict: {"status": "otp_sent"} on success.

    Raises:
        HTTPException 401: Invalid or expired portal token.
        HTTPException 429: Rate limit exceeded (>5 requests/hour per phone).
        HTTPException 502: Twilio Verify API failure.
    """
    # 1. Validate portal token and extract phone number
    claims: PortalTokenClaims = validate_portal_token(body.portal_token)
    phone: str = claims.phone_number

    logger.info(
        "OTP request received",
        extra={
            "event_type": "otp_request",
            "portal_session_id": claims.portal_session_id,
            # phone number NOT logged (PHI)
        },
    )

    # 2. Rate limit check — BEFORE calling Twilio (AC Scenario 2)
    rate_key = rate_limit_redis_key(phone)
    current_count: int = await redis.incr(rate_key)

    if current_count == 1:
        # First request in the window — set TTL
        await redis.expire(rate_key, RATE_LIMIT_TTL_SECONDS)

    if current_count > RATE_LIMIT_MAX:
        ttl: int = await redis.ttl(rate_key)
        retry_after = ttl if ttl > 0 else RATE_LIMIT_TTL_SECONDS

        logger.warning(
            "OTP rate limit exceeded",
            extra={
                "event_type": "otp_rate_limit_exceeded",
                "current_count": current_count,
                "retry_after": retry_after,
                "portal_session_id": claims.portal_session_id,
            },
        )

        raise HTTPException(
            status_code=429,
            detail="Too many OTP requests. Please wait before trying again.",
            headers={"Retry-After": str(retry_after)},
        )

    # 3. Send OTP via Twilio Verify (primary channel — US-065)
    verify_sid = _get_twilio_verify_sid()

    try:
        verification = twilio.verify.v2.services(
            verify_sid
        ).verifications.create(to=phone, channel="sms")
    except Exception as exc:
        logger.error(
            "Twilio Verify API call failed",
            extra={
                "event_type": "twilio_verify_failed",
                "error": str(exc),
                "portal_session_id": claims.portal_session_id,
            },
        )
        raise HTTPException(
            status_code=502,
            detail="OTP delivery service temporarily unavailable.",
        ) from exc

    if verification.status not in ("pending", "approved"):
        logger.error(
            "Twilio Verify returned unexpected status",
            extra={
                "event_type": "twilio_verify_unexpected_status",
                "status": verification.status,
                "portal_session_id": claims.portal_session_id,
            },
        )
        raise HTTPException(
            status_code=502,
            detail="OTP delivery failed. Please try again.",
        )

    # 3b. Fallback email notification when patient has an email on file (US-064)
    #     This is sent in addition to Twilio Verify SMS so the patient also sees
    #     an email alert about the portal login attempt. Uses notification-svc.
    if claims.patient_id and getattr(claims, "email", None):
        try:
            notifier = PatientNotificationPublisher()
            await notifier.send_email(
                email=claims.email,
                subject="SmartHandoff portal login code requested",
                body=(
                    "A login code was just requested for your SmartHandoff patient portal. "
                    "If this wasn't you, contact your care team."
                ),
                patient_id=claims.patient_id,
                priority="HIGH",
                urgency_override=True,
            )
        except Exception as exc:
            logger.error(
                "Failed to send OTP email notification",
                extra={
                    "event_type": "otp_email_notification_failed",
                    "error": str(exc),
                    "portal_session_id": claims.portal_session_id,
                },
            )

    # 4. Store verification SID in Redis
    #    Twilio Verify manages the actual OTP code and its own internal hash.
    #    Our Redis entry stores the Twilio verification SID as the session
    #    anchor for the verify step (TASK-003). The OTP code itself is never
    #    transmitted back to our server — Twilio verifies it in TASK-003.
    otp_key = otp_redis_key(body.portal_token)
    await redis.set(otp_key, verification.sid, ex=OTP_TTL_SECONDS)

    logger.info(
        "OTP sent successfully",
        extra={
            "event_type": "otp_sent",
            "verification_sid": verification.sid,
            "portal_session_id": claims.portal_session_id,
            "ttl_seconds": OTP_TTL_SECONDS,
        },
    )

    return {"status": "otp_sent"}
