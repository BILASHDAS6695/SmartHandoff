"""Portal token validation for patient OTP authentication (US-065).

The portal_token is a short-lived JWT issued by the patient portal
authentication flow (US-052) that contains the patient's phone number
and portal session ID.

This module validates the token signature, expiry, and extracts claims
for OTP delivery.
"""
from __future__ import annotations

import os
from typing import NamedTuple

from fastapi import HTTPException, status
from jose import JWTError, jwt


class PortalTokenClaims(NamedTuple):
    """Validated claims extracted from a portal_token."""

    patient_id: str
    """Patient identifier (MRN or internal patient ID)."""

    phone_number: str
    """Patient's phone number in E.164 format (e.g., +12345678901)."""

    portal_session_id: str
    """Unique session ID from the patient portal."""

    email: str | None
    """Optional patient email address for notification fallbacks (US-064)."""


def _get_portal_secret() -> str:
    """Return the PORTAL_JWT_SECRET from environment.

    Raises:
        RuntimeError: If PORTAL_JWT_SECRET is not set.
    """
    secret = os.environ.get("PORTAL_JWT_SECRET", "")
    if not secret:
        raise RuntimeError(
            "PORTAL_JWT_SECRET environment variable is not set. "
            "Mount it from GCP Secret Manager."
        )
    return secret


def validate_portal_token(token: str) -> PortalTokenClaims:
    """Validate a portal_token JWT and return its claims.

    Args:
        token: The portal_token JWT string from the patient portal.

    Returns:
        PortalTokenClaims: Validated claims containing patient_id, phone_number,
                          and portal_session_id.

    Raises:
        HTTPException 401: If the token is invalid, expired, or missing
                          required claims.
    """
    secret = _get_portal_secret()

    try:
        # Decode and verify the JWT
        # python-jose automatically checks signature, exp, nbf
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_nbf": False,  # Portal tokens may not include nbf
                "require_exp": True,
            },
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired portal token",
        ) from exc

    # Extract required claims
    patient_id = claims.get("patient_id")
    phone_number = claims.get("phone_number")
    portal_session_id = claims.get("portal_session_id")

    if not patient_id or not phone_number or not portal_session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Portal token missing required claims",
        )

    # Validate E.164 phone number format (basic check)
    if not phone_number.startswith("+") or len(phone_number) < 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid phone number format in portal token",
        )

    email: str | None = claims.get("email")

    return PortalTokenClaims(
        patient_id=patient_id,
        phone_number=phone_number,
        portal_session_id=portal_session_id,
        email=email,
    )
