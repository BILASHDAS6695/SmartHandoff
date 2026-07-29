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
