"""SCIM 2.0 bearer token authentication dependency.

The SCIM client secret is separate from staff JWTs (US-060 Technical Notes).
It is a long-lived bearer token (90-day rotation) stored in GCP Secret Manager
and mounted as the SCIM_CLIENT_SECRET environment variable in Cloud Run.

Security properties:
  - hmac.compare_digest prevents timing-based token enumeration attacks
  - No token value exposed in error responses or logs (SEC-011)
  - Invalid requests return 401 with the standard WWW-Authenticate header

Design refs:
    design.md §7.4 AIR-032  — SCIM bearer token authentication
    TR-021                   — zero hardcoded credentials
    SEC-011                  — secrets in Secret Manager only
    US-060 AC Scenario 3     — unauthenticated SCIM → 401
"""
from __future__ import annotations

import hmac
import logging

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


async def verify_scim_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> None:
    """FastAPI dependency that validates the SCIM bearer token.

    Usage::
        @router.post("/Users", dependencies=[Depends(verify_scim_token)])

    Raises:
        HTTPException 401 if the token is absent or does not match the
        configured SCIM_CLIENT_SECRET.

    Security:
        ``hmac.compare_digest`` is used to prevent timing-oracle attacks.
        The actual token is never logged or included in error details.
    """
    settings = get_settings()

    if credentials is None:
        _reject(request)

    provided: str = credentials.credentials  # type: ignore[union-attr]
    expected: str = settings.SCIM_CLIENT_SECRET

    if not hmac.compare_digest(
        provided.encode("utf-8"),
        expected.encode("utf-8"),
    ):
        _reject(request)


def _reject(request: Request) -> None:
    """Log the rejection and raise 401 without leaking token details."""
    logger.warning(
        "SCIM auth failure",
        extra={
            "event": "scim_auth_failure",
            "client_ip": request.client.host if request.client else "unknown",
            # Token value intentionally NOT logged (SEC-011)
        },
    )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="SCIM authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )
