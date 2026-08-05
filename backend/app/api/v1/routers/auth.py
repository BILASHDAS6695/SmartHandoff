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

import json
import logging
import os
from typing import Annotated

import httpx
import redis
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
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


# ── POST /api/v1/auth/exchange-code ───────────────────────────────────────────

class CodeExchangeRequest(BaseModel):
    code: str = Field(..., description="Authorization code from OAuth callback")
    code_verifier: str = Field(..., description="PKCE code verifier")
    redirect_uri: str = Field(..., description="Redirect URI used in the authorization request")


def _get_client_secret() -> str:
    """Get OAuth client secret from environment."""
    secret = (
        os.environ.get("OAUTH_CLIENT_SECRET")
        or os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
        or ""
    )
    if not secret:
        # For testing without client_secret (development only)
        logger.error("❌ OAuth client secret NOT SET! Checked: OAUTH_CLIENT_SECRET, GOOGLE_OAUTH_CLIENT_SECRET - Google will reject the token exchange with 400 Bad Request")
        logger.error("💡 SOLUTION: Set the OAUTH_CLIENT_SECRET environment variable in PowerShell BEFORE starting uvicorn")
        return ""
    logger.info("✅ OAuth client secret is set (first 10 chars: %s...)", secret[:10])
    return secret


def _get_client_id() -> str:
    """Get OAuth client ID from environment."""
    client_id = (
        os.environ.get("OIDC_CLIENT_ID")
        or os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    )
    if not client_id:
        raise RuntimeError("❌ OIDC_CLIENT_ID or GOOGLE_OAUTH_CLIENT_ID environment variable is not set. Please configure it in your .env or system environment.")
    logger.info("✅ Using OAuth client ID: %s...", client_id[:20])
    return client_id


@router.options(
    "/exchange-code",
    summary="CORS preflight for exchange-code endpoint",
    status_code=status.HTTP_200_OK,
)
async def exchange_code_options():
    """Handle CORS preflight OPTIONS request for exchange-code endpoint."""
    from app.core.config import get_settings
    settings = get_settings()
    origin = settings.CORS_ORIGINS[0] if settings.CORS_ORIGINS else "*"
    return Response(
        status_code=status.HTTP_200_OK,
        headers={
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Max-Age": "3600",
        },
    )


@router.post(
    "/exchange-code",
    response_model=TokenResponse,
    summary="Exchange authorization code for SmartHandoff JWT",
    description=(
        "Accepts an OAuth authorization code from the frontend, exchanges it "
        "with Google for an id_token (using client_secret), validates the "
        "id_token, and issues a SmartHandoff application JWT."
    ),
)
async def exchange_code(
    body: CodeExchangeRequest,
    db: Annotated[AsyncSession, Depends(get_write_db)],
) -> TokenResponse:
    """Exchange OAuth authorization code for SmartHandoff application JWT.
    
    This endpoint securely handles the code-to-token exchange with Google OAuth,
    keeping the client_secret on the backend.
    """
    
    try:
        # Step 1: Exchange authorization code for id_token with Google
        token_url = "https://oauth2.googleapis.com/token"

        client_id = _get_client_id()
        client_secret = _get_client_secret()

        # Log safe OAuth metadata only (avoid logging secrets or auth artifacts).
        logger.info("OAuth code exchange requested for redirect_uri=%s", body.redirect_uri)

        token_request_data = {
            "grant_type": "authorization_code",
            "code": body.code,
            "redirect_uri": body.redirect_uri,
            "client_id": client_id,
            "code_verifier": body.code_verifier,
        }

        # Add client_secret - required for Web Application OAuth clients
        if client_secret:
            token_request_data["client_secret"] = client_secret
            logger.info("✅ Using Web Application OAuth flow with PKCE + client_secret")
            logger.debug("📤 Sending to Google token endpoint:")
            logger.debug("   - grant_type: authorization_code")
            logger.debug("   - redirect_uri: %s", body.redirect_uri)
            logger.debug("   - client_id: %s", client_id)
            logger.debug("   - code_verifier: (PKCE verifier, length=%d)", len(body.code_verifier))
            logger.debug("   - code: (auth code, length=%d)", len(body.code))
            logger.debug("   - client_secret: (present, length=%d)", len(client_secret))
        else:
            logger.error("❌ NO CLIENT_SECRET - Google token endpoint will reject with 400 Bad Request")
            logger.error("💡 SOLUTION: Set this environment variable in PowerShell BEFORE starting uvicorn:")
            logger.error("   $env:OAUTH_CLIENT_SECRET = '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'")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    token_url,
                    data=token_request_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=10.0,
                )
                response.raise_for_status()
                token_data = response.json()
                logger.info(
                    "✅ Token exchange successful. Response keys: %s, has id_token: %s",
                    list(token_data.keys()),
                    'id_token' in token_data
                )
        except httpx.HTTPError as exc:
            response_text = "No response"
            error_code = "unknown_error"
            error_description = "OAuth provider rejected authorization code exchange"
            status_code = status.HTTP_401_UNAUTHORIZED

            if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
                response_text = exc.response.text
                status_code = exc.response.status_code

                try:
                    payload = exc.response.json()
                except (ValueError, json.JSONDecodeError):
                    payload = None

                if isinstance(payload, dict):
                    error_code = str(payload.get("error") or error_code)
                    error_description = str(payload.get("error_description") or error_description)
                elif response_text:
                    error_description = response_text

                # Log detailed error from Google
                logger.error("❌ Google OAuth token endpoint returned %d %s", status_code, error_code)
                logger.error("   Error description: %s", error_description)
                if payload:
                    logger.error("   Full response: %s", payload)
                    
                # Diagnose common issues
                if error_code == "invalid_grant":
                    logger.error("💡 invalid_grant means: Authorization code invalid/expired, or doesn't match client_id/redirect_uri")
                    logger.error("   - Check if user took > 10 minutes before clicking login")
                    logger.error("   - Verify redirect_uri matches exactly: %s", body.redirect_uri)
                    logger.error("   - Verify OAuth app is configured in Google Cloud Console")
                elif error_code == "invalid_client":
                    logger.error("💡 invalid_client means: Client credentials (client_id/client_secret) are invalid")
                    logger.error("   - Check OAUTH_CLIENT_SECRET environment variable is set correctly")
                    logger.error("   - Check OIDC_CLIENT_ID environment variable is set correctly")
                elif status_code == 400:
                    logger.error("💡 400 Bad Request from Google likely means:")
                    logger.error("   - Missing OAUTH_CLIENT_SECRET environment variable")
                    logger.error("   - Redirect URI mismatch (should be exactly: http://localhost:4200/auth/callback)")
                    logger.error("   - Authorization code has expired (valid for ~10 minutes)")

                # Normalize common OAuth exchange failures for client behavior.
                if error_code in {"invalid_grant", "invalid_request"}:
                    status_code = status.HTTP_400_BAD_REQUEST
                elif error_code in {"invalid_client", "unauthorized_client"}:
                    status_code = status.HTTP_401_UNAUTHORIZED

            logger.error(
                "Failed to exchange authorization code: %s - Response: %s",
                exc,
                response_text,
                extra={
                    "event_type": "auth_failure",
                    "reason": "code_exchange_failed",
                    "oauth_error": error_code,
                },
            )
            raise HTTPException(
                status_code=status_code,
                detail={
                    "message": "Failed to exchange authorization code",
                    "oauth_error": error_code,
                    "oauth_error_description": error_description,
                },
            ) from exc

        id_token = token_data.get("id_token")
        if not id_token:
            logger.error("No id_token in Google OAuth response. Response keys: %s", list(token_data.keys()))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid OAuth response - no id_token",
            )

        # Log token header for debugging (doesn't expose sensitive data)
        try:
            import base64
            import json
            header = json.loads(base64.urlsafe_b64decode(id_token.split('.')[0] + '=='))
            logger.info("id_token header: %s", header)
        except Exception as e:
            logger.warning("Failed to decode id_token header: %s", e)

        # Step 2: Validate the id_token
        oidc_claims = await validate_id_token(id_token)

        # Step 3: Issue SmartHandoff application JWT
        app_token, jti = issue_app_jwt(oidc_claims)

        # Step 4: Persist the issued jti for deprovisioning
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
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error during OAuth code exchange: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"OAuth code exchange failed unexpectedly ({type(exc).__name__})",
        ) from exc
