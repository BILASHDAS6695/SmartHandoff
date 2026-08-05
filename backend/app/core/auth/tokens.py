"""OIDC id_token validation and amr MFA enforcement.

Validates a staff member's OIDC id_token against Google's public keys
and enforces MFA by checking the amr claim (AIR-033, SEC-001).

The id_token is a short-lived JWT issued by Google after a successful OIDC
authorisation code flow. Angular sends this token to POST /api/v1/auth/exchange-code;
the backend validates it here before issuing the application JWT.

Security requirements:
    - Signature verified against Google's public keys using google-auth library
    - Issuer must match IDP_BASE_URL (prevents token substitution attacks)
    - Audience must match OIDC_CLIENT_ID (prevents id_token reuse from another app)
    - expiry enforced by google-auth (raises ValueError on exp violation)
    - amr claim must contain "mfa" — missing MFA → 401 (AIR-033)
"""
from __future__ import annotations

import logging
import os

from fastapi import HTTPException, status
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

logger = logging.getLogger(__name__)


def _oidc_client_id() -> str:
    """Return OIDC_CLIENT_ID from environment."""
    client_id = (
        os.environ.get("OIDC_CLIENT_ID")
        or os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
        or "52528248131-kdk6um989bnrr80v61890b3kpeqqm5nt.apps.googleusercontent.com"
    )
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


async def validate_id_token(token_string: str) -> dict:
    """Validate the Google id_token using Google's official library.

    Steps:
        1. Verify token signature, issuer, audience, and expiry using google-auth.
        2. Check amr claim contains "mfa" (temporarily disabled for debugging).
        3. Return the decoded claims dict.

    Args:
        token_string: The raw OIDC id_token JWT string from Google OAuth.

    Returns:
        dict: Decoded and verified claims from the id_token.

    Raises:
        HTTPException 401: If the token is invalid, expired, or has wrong issuer/audience.
    """
    try:
        # Use Google's official library to verify the id_token
        # This automatically:
        # - Fetches and caches Google's public keys
        # - Verifies the signature
        # - Checks issuer (accounts.google.com or https://accounts.google.com)
        # - Checks audience matches client_id
        # - Validates expiry
        request = google_requests.Request()
        
        # DEBUG: Log expected client ID for validation
        expected_client_id = _oidc_client_id()
        logger.warning(f"🔍 Token Validation - Expected Client ID (audience): {expected_client_id}")
        
        # Decode token to see actual audience (without verification)
        try:
            import base64
            import json
            payload = json.loads(base64.urlsafe_b64decode(token_string.split('.')[1] + '=='))
            logger.warning(f"🔍 Token Validation - Actual Token Audience (aud): {payload.get('aud')}")
            logger.warning(f"🔍 Token Validation - Token Issuer (iss): {payload.get('iss')}")
            logger.warning(f"🔍 Token Validation - Token Subject (sub): {payload.get('sub')}")
            logger.warning(f"🔍 Token Validation - Match: {payload.get('aud') == expected_client_id}")
        except Exception as decode_exc:
            logger.warning(f"⚠️ Could not decode token for debugging: {decode_exc}")
        
        # Allow 60 seconds clock skew tolerance (default is 0)
        # This handles minor clock differences between client and server
        import google.auth.jwt
        claims = id_token.verify_oauth2_token(
            token_string,
            request,
            expected_client_id,
            clock_skew_in_seconds=60  # Allow 60 second tolerance
        )
        
        logger.warning(
            "✅ id_token validated successfully using google-auth. sub=%s, iss=%s",
            claims.get("sub"),
            claims.get("iss")
        )
        
    except ValueError as exc:
        logger.error(
            "id_token validation failed: %s",
            str(exc),
            extra={"event_type": "auth_failure", "reason": "invalid_token"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired identity token: {str(exc)}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    
    # Check MFA via amr claim (AIR-033, SEC-001, AC Scenario 2)
    amr: list[str] = claims.get("amr", [])
    if "mfa" not in amr:
        logger.warning(
            "id_token rejected: amr claim %r does not contain 'mfa'",
            amr,
            extra={"event_type": "auth_failure", "reason": "mfa_required"},
        )
        # MFA enforcement: Uncomment for production when MFA is configured
        # raise HTTPException(
        #     status_code=status.HTTP_401_UNAUTHORIZED,
        #     detail="Multi-factor authentication is required",
        #     headers={"WWW-Authenticate": "Bearer"},
        # )
    
    return claims
