"""Authentication router — POST /api/v1/auth/token, POST /api/v1/auth/logout.

Accepts an OIDC id_token from the Angular callback component, validates it,
enforces MFA, and issues a SmartHandoff application JWT.

Routes:
    POST /api/v1/auth/token   — exchange OIDC id_token for app JWT (US-056)
    POST /api/v1/auth/logout  — revoke current JWT via Redis blocklist (US-059)

Design refs:
    design.md §3.3 API Layer / Routers
    design.md §8.2 Authentication & Authorization Flow
    AIR-032, SEC-009, US-059
"""
from __future__ import annotations

import logging
from typing import Annotated

import redis
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.jwt import TokenClaims, get_current_user, issue_app_jwt
from app.core.auth.jwt_blocklist import add_to_blocklist
from app.core.auth.tokens import validate_id_token
from app.db.deps import get_write_db
from app.models.app_user import AppUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenRequest(BaseModel):
    id_token: str = Field(..., description="OIDC id_token from the identity provider")


class TokenResponse(BaseModel):
    access_token: str = Field(..., description="SmartHandoff application JWT")
    token_type: str = Field(default="bearer")
    expires_in: int = Field(default=28800, description="Token validity in seconds (8h)")


@router.post(
    "/token",
    response_model=TokenResponse,
    summary="Exchange OIDC id_token for SmartHandoff application JWT",
    description=(
        "Validates the OIDC id_token signature against the IdP JWKS, "
        "enforces MFA (amr claim), maps claims to SmartHandoff roles, "
        "and issues a HS256-signed application JWT."
    ),
)
async def exchange_token(
    body: TokenRequest,
    db: Annotated[AsyncSession, Depends(get_write_db)],
) -> TokenResponse:
    """Exchange an OIDC id_token for a SmartHandoff application JWT."""

    oidc_claims = await validate_id_token(body.id_token)
    app_token, jti = issue_app_jwt(oidc_claims)

    # Persist the issued jti so deprovisioning can blocklist it (US-059/TASK-004)
    try:
        await db.execute(
            sa_update(AppUser)
            .where(AppUser.idp_subject == oidc_claims["sub"])
            .values(current_jti=jti)
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to persist current_jti for sub=%s: %s",
            oidc_claims.get("sub"),
            exc,
            extra={"event_type": "jti_persist_failure"},
        )
        await db.rollback()

    return TokenResponse(access_token=app_token)


# ── POST /api/v1/auth/logout ──────────────────────────────────────────────────

@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    summary="Revoke the current JWT and end the session",
    response_description="Session terminated; JWT blocklisted",
)
async def logout(
    current_user: Annotated[TokenClaims, Depends(get_current_user)],
) -> dict:
    """Blocklist the current JWT and instruct the client to clear its session.

    The ``get_current_user`` dependency validates the Bearer token before
    this handler runs. A valid (non-expired, non-blocklisted) token is
    required — you cannot log out with an already-invalid token.

    After successful logout the client MUST discard its in-memory JWT.
    Any subsequent request with the same JWT returns 401 Unauthorized.

    Returns:
        JSON body ``{"message": "Logged out successfully"}``

    Raises:
        HTTP 401: Token invalid or already expired (raised by get_current_user).
        HTTP 503: Redis unavailable.
    """
    jti: str | None = current_user.jti
    exp: int | None = current_user.exp

    if not jti or not exp:
        # Token predates jti claim — cannot blocklist, but still respond 200
        # so the client can clear its local JWT and redirect to login.
        logger.warning(
            "Logout requested for token without jti claim: sub=%s",
            current_user.sub,
            extra={"event_type": "logout_no_jti", "sub": current_user.sub},
        )
        return {"message": "Logged out successfully"}

    try:
        add_to_blocklist(jti, exp)
    except redis.RedisError as exc:
        logger.error(
            "Redis error during logout blocklist write: jti=%s error=%s",
            jti,
            exc,
            extra={"event_type": "redis_error", "context": "logout", "jti": jti},
        )
        # Do NOT raise 503 here — the user's intent to log out must succeed
        # even if Redis is momentarily unavailable. Log the failure for ops.
        # The token will expire naturally within its 8-hour window.

    logger.info(
        "User logged out: sub=%s jti=%s",
        current_user.sub,
        jti,
        extra={
            "event_type": "user_logout",
            "sub": current_user.sub,
            "jti": jti,
        },
    )
    return {"message": "Logged out successfully"}
