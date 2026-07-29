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
from api_gateway.app.services.otp_service import (
    delete_otp_hash,
    get_otp_hash,
)

router = APIRouter(prefix="/api/v1/auth/patient", tags=["Patient Auth"])
log = logging.getLogger(__name__)


class VerifyRequest(BaseModel):
    """Request body for POST /api/v1/auth/patient/verify."""
    portal_token: str = Field(..., description="Signed JWT from patient SMS link")
    otp: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$", description="6-digit OTP")


class TokenResponse(BaseModel):
    """Response body for POST /api/v1/auth/patient/verify."""
    access_token: str = Field(..., description="Patient JWT (60-minute expiry)")
    token_type: str = Field("bearer", description="Token type")
    expires_in: int = Field(3600, description="Token expiry in seconds")


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
    """Validate OTP hash from Redis and issue a 60-minute patient JWT (US-052 TASK-003).

    Request flow:
        1. Decode portal_token → extract patient_id, encounter_id (TASK-001)
        2. Retrieve OTP hash from Redis: otp:{portal_token}
           → Missing or expired → 401 "OTP has expired. Please request a new code."
        3. Validate OTP: bcrypt.checkpw(otp_plaintext, stored_hash)
           → Mismatch → 401 "Invalid OTP. Please try again."
        4. Delete OTP hash from Redis (one-time use enforcement)
        5. Issue patient JWT with encounter_id claim (60-minute expiry)
        6. Write HIPAA audit event: PATIENT_AUTH_SUCCESS
        7. Return 200 {"access_token": "<jwt>", ...}

    AC Scenario 1 — JWT returned within 30 s of SMS link tap
    AC Scenario 3 — Expired OTP → 401 with specific message
    AC Scenario 4 — JWT contains encounter_id claim for downstream enforcement

    Args:
        body: VerifyRequest with portal_token and 6-digit OTP
        redis: Async Redis client for OTP hash retrieval and deletion

    Returns:
        TokenResponse with access_token (JWT), token_type, expires_in

    Raises:
        HTTPException 400 — invalid/malformed portal_token or OTP format
        HTTPException 401 — expired portal_token, expired OTP, or OTP mismatch
    """
    # 1. Decode portal token (raises 401 if expired or invalid)
    try:
        portal_claims: PortalTokenClaims = decode_portal_token(body.portal_token)
    except HTTPException:
        raise

    patient_id = portal_claims.patient_id
    encounter_id = portal_claims.encounter_id

    # 2. Retrieve OTP hash from Redis
    stored_otp_hash: bytes | None = await get_otp_hash(redis, body.portal_token)
    if stored_otp_hash is None:
        log.warning("otp_not_found_or_expired", extra={"encounter_id": encounter_id})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="OTP has expired. Please request a new code.",
        )

    # 3. Validate OTP: bcrypt.checkpw(plaintext, hash)
    otp_is_valid = bcrypt.checkpw(body.otp.encode(), stored_otp_hash)
    if not otp_is_valid:
        log.warning("otp_mismatch", extra={"encounter_id": encounter_id})
        # Do NOT delete the OTP hash on mismatch — allow multiple attempts
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid OTP. Please try again.",
        )

    # 4. Delete OTP hash (one-time use enforcement)
    await delete_otp_hash(redis, body.portal_token)

    # 5. Issue patient JWT with encounter_id claim
    access_token = issue_patient_jwt(patient_id, encounter_id)

    # 6. Write HIPAA audit event
    await write_audit_event(
        event_type="PATIENT_AUTH_SUCCESS",
        encounter_id=encounter_id,
        patient_id=patient_id,
    )

    log.info(
        "patient_jwt_issued",
        extra={"encounter_id": encounter_id},
        # patient_id intentionally omitted (PHI)
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=3600,
    )
