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
