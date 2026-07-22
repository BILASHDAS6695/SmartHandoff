"""Application JWT issuance and Bearer token validation.

SmartHandoff issues its own short-lived JWT after validating the OIDC
id_token. This decouples the application session from the IdP session and
allows role/unit claims to be augmented from the SmartHandoff user DB.

JWT spec (US-056 DoD):
    sub     = user_id (from OIDC sub claim, mapped via DB lookup)
    role    = SmartHandoff role string (mapped from OIDC groups claim)
    units   = list of unit codes the user is assigned to
    email   = user email (from OIDC email claim)
    iat     = issued-at timestamp (UTC)
    exp     = iat + 8 hours (28800 seconds)
    alg     = HS256

Signing key:
    Loaded from Secret Manager secret 'smarthandoff-jwt-signing-key-{environment}'.
    Mounted by Cloud Run as the JWT_SIGNING_KEY environment variable (US-005/TASK-003).
    Must be a minimum 32-byte (256-bit) random string.

Bearer validation (get_current_user):
    Used as a FastAPI dependency on every protected route.
    Verifies HS256 signature, exp, and required claims.
    Returns decoded claims dict; raises HTTP 401 on any failure.
"""
from __future__ import annotations

import logging
import os
import time
import uuid as _uuid
from datetime import datetime, timezone
from typing import Annotated

import redis as _redis
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, ConfigDict

from app.core.auth.jwt_blocklist import is_blocklisted

logger = logging.getLogger(__name__)

_ALGORITHM = "HS256"
_TOKEN_EXPIRY_SECONDS = 8 * 60 * 60  # 8 hours (US-056 DoD)

_bearer_scheme = HTTPBearer(auto_error=True)


# ── Token claims model (US-057) ───────────────────────────────────────────────

class TokenClaims(BaseModel):
    """Decoded and validated SmartHandoff application JWT payload.

    Used as the return type of get_current_user() and the RBAC dependency
    require_permission(), giving typed access to JWT claims in route handlers.
    """

    model_config = ConfigDict(extra="ignore")

    sub: str
    role: str
    units: list[str] = []
    email: str = ""
    jti: str | None = None
    iat: int = 0
    exp: int = 0


def _jwt_signing_key() -> str:
    """Return JWT_SIGNING_KEY from environment (mounted from Secret Manager)."""
    key = os.environ.get("JWT_SIGNING_KEY", "")
    if not key or len(key) < 32:
        raise RuntimeError(
            "JWT_SIGNING_KEY is not set or too short (minimum 32 characters). "
            "Mount it from Secret Manager 'smarthandoff-jwt-signing-key-{env}'."
        )
    return key


# ── Claims mapping helpers ─────────────────────────────────────────────────────

_ROLE_MAP: dict[str, str] = {
    # Map IdP group names to SmartHandoff role strings.
    # Keys must match the group names configured in the hospital IdP.
    "smarthandoff-admin":       "admin",
    "smarthandoff-physician":   "physician",
    "smarthandoff-nurse":       "nurse",
    "smarthandoff-pharmacist":  "pharmacist",
    "smarthandoff-bed-manager": "bed_manager",
}


def _map_role(groups: list[str]) -> str:
    """Map IdP groups to a SmartHandoff role string.

    Takes the first matching group in priority order (most privileged first).
    Returns "unknown" if no known group is found; callers should reject unknown roles.
    """
    for group in groups:
        if group in _ROLE_MAP:
            return _ROLE_MAP[group]
    return "unknown"


def _map_claims(oidc_claims: dict) -> dict:
    """Map OIDC id_token claims to SmartHandoff application JWT claims.

    Mapping spec (US-056 DoD):
        sub      → user_id  (OIDC subject identifier)
        groups   → role     (via _ROLE_MAP)
        units    → units    (custom claim set by IdP, default [])
        email    → email

    Args:
        oidc_claims: Decoded OIDC id_token claims dict.

    Returns:
        dict: Application claims ready for JWT encoding.

    Raises:
        HTTPException 403: If the role cannot be determined from IdP groups.
    """
    role = _map_role(oidc_claims.get("groups", []))
    if role == "unknown":
        logger.warning(
            "No recognised SmartHandoff group for sub=%s groups=%r",
            oidc_claims.get("sub"),
            oidc_claims.get("groups"),
            extra={"event_type": "auth_failure", "reason": "no_role"},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not assigned to a SmartHandoff role",
        )

    return {
        "sub": oidc_claims["sub"],           # user_id
        "role": role,
        "units": oidc_claims.get("units", []),
        "email": oidc_claims.get("email", ""),
    }


# ── JWT issuance ───────────────────────────────────────────────────────────────

def issue_app_jwt(oidc_claims: dict) -> tuple[str, str]:
    """Issue a SmartHandoff application JWT from validated OIDC claims.

    Args:
        oidc_claims: Decoded and validated OIDC id_token claims (from TASK-003).

    Returns:
        tuple[str, str]: (signed JWT string, jti UUID string).

    Raises:
        HTTPException 403: If role mapping fails.
    """
    app_claims = _map_claims(oidc_claims)
    now = int(datetime.now(tz=timezone.utc).timestamp())
    jti = str(_uuid.uuid4())  # unique token ID — enables per-token blocklisting (US-059)

    payload = {
        **app_claims,
        "jti": jti,
        "iat": now,
        "exp": now + _TOKEN_EXPIRY_SECONDS,
    }

    token = jwt.encode(payload, _jwt_signing_key(), algorithm=_ALGORITHM)
    logger.info(
        "Application JWT issued for sub=%s role=%s jti=%s exp_in=%ds",
        app_claims["sub"],
        app_claims["role"],
        jti,
        _TOKEN_EXPIRY_SECONDS,
        extra={"event_type": "jwt_issued", "jti": jti},
    )
    return token, jti


# ── Bearer validation (FastAPI dependency) ────────────────────────────────────

async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
) -> TokenClaims:
    """FastAPI dependency: validate SmartHandoff application JWT from Bearer header.

    Inject this dependency on all protected routes:

        @router.get("/patients")
        async def list_patients(user: Annotated[TokenClaims, Depends(get_current_user)]):
            ...

    Returns:
        TokenClaims: Decoded JWT payload (includes sub, role, units, email, exp).

    Raises:
        HTTPException 401: If the token is missing, expired, or invalid.
    """
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            _jwt_signing_key(),
            algorithms=[_ALGORITHM],
            options={"verify_exp": True},
        )
    except JWTError as exc:
        logger.warning(
            "Bearer JWT validation failed: %s",
            type(exc).__name__,
            extra={"event_type": "auth_failure", "reason": "invalid_bearer"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    # ── Blocklist check (US-059) — MUST be after signature validation ──────────
    jti: str | None = payload.get("jti")
    if jti:
        try:
            if is_blocklisted(jti):
                logger.warning(
                    "Blocklisted JWT presented: jti=%s sub=%s",
                    jti,
                    payload.get("sub"),
                    extra={
                        "event_type": "auth_failure",
                        "reason": "token_blocklisted",
                        "jti": jti,
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired access token",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        except _redis.RedisError as exc:
            # Fail-closed: Redis unavailable means we cannot confirm
            # the token is not revoked — treat as a service error.
            logger.error(
                "Redis unavailable during blocklist check: %s",
                exc,
                extra={"event_type": "redis_error", "context": "blocklist_check"},
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service temporarily unavailable",
            ) from exc
    else:
        # Token predates jti claim introduction — allow through with warning.
        # Remove this branch after all pre-jti tokens have expired (8 hours
        # after TASK-001 is deployed).
        logger.warning(
            "JWT without jti claim from sub=%s — cannot blocklist-check; "
            "token will expire naturally in %d seconds",
            payload.get("sub"),
            max(payload.get("exp", 0) - int(time.time()), 0),
            extra={"event_type": "auth_warning", "reason": "missing_jti"},
        )

    # ── Required claims presence ───────────────────────────────────────────────
    for required_claim in ("sub", "role", "exp"):
        if required_claim not in payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired access token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return TokenClaims(**payload)
