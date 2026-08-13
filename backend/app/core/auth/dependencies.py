"""Authentication dependencies for FastAPI route protection.

Provides:
  - get_current_internal_service: validates service-to-service JWT for internal endpoints.
  - get_current_staff_user: alias to get_current_user with explicit naming.
  - get_current_patient_user: validates patient JWT and fetches patient entity.
  - require_role: factory function for role-based access control.

US-022 Security:
  Internal endpoints (like POST /api/v1/signalr/task-updated) must be callable
  only by other SmartHandoff services (AI agents) within the VPC. This is enforced
  by a combination of:
    1. Cloud Run ingress: internal-only (blocks public internet traffic).
    2. JWT validation with "scope: internal" claim (validates caller identity).

Internal JWT spec:
    sub     = service name (e.g., "coordinator-agent", "bed-management-agent")
    scope   = "internal"
    iat     = issued-at timestamp (UTC)
    exp     = iat + 1 hour
    alg     = HS256

Signing key:
    Uses the same JWT_SIGNING_KEY as user JWTs (from Secret Manager).
    This is acceptable because the "scope" claim differentiates internal from
    user tokens — the signature validation alone is insufficient for access control.
"""
from __future__ import annotations

import logging
import uuid
from typing import Annotated, TYPE_CHECKING

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select

from app.core.auth.jwt import _ALGORITHM, _jwt_signing_key, get_current_user, TokenClaims

if TYPE_CHECKING:
    from app.models.patient import Patient

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=True)


async def get_current_internal_service(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
) -> None:
    """FastAPI dependency: validate internal service-to-service JWT.

    Verifies the Bearer token has "scope: internal" claim. Raises 401 if:
      - Token is missing or malformed.
      - Token signature is invalid.
      - Token is expired.
      - Token does not contain "scope: internal" claim.

    Inject this dependency on internal-only endpoints:

        @router.post("/internal-endpoint")
        async def internal_handler(
            _caller: Annotated[None, Depends(get_current_internal_service)]
        ):
            ...

    Returns:
        None — the dependency is used for access control only; the caller service
        identity (sub claim) is not currently returned but could be if needed.

    Raises:
        HTTPException 401: If the token is missing, expired, invalid, or not internal-scoped.
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
            "Internal service JWT validation failed: %s",
            type(exc).__name__,
            extra={"event_type": "auth_failure", "reason": "invalid_internal_token"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired service token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    # ── Scope claim validation ─────────────────────────────────────────────────
    scope = payload.get("scope")
    if scope != "internal":
        logger.warning(
            "JWT presented to internal endpoint with scope=%r (expected 'internal')",
            scope,
            extra={
                "event_type": "auth_failure",
                "reason": "invalid_scope",
                "sub": payload.get("sub"),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired service token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.debug(
        "Internal service JWT validated: sub=%s",
        payload.get("sub"),
        extra={"event_type": "internal_auth_success", "service": payload.get("sub")},
    )
    # Return None — the dependency is for access control only.


# Alias for explicit naming in routes that require staff user authentication
async def get_current_staff_user(
    user: Annotated[TokenClaims, Depends(get_current_user)],
) -> TokenClaims:
    """Alias to get_current_user with explicit naming for staff-authenticated endpoints.

    Use this on endpoints that require a staff member (not internal service) to be authenticated:

        @router.get("/patients")
        async def list_patients(
            user: Annotated[TokenClaims, Depends(get_current_staff_user)]
        ):
            ...

    This is semantically identical to get_current_user but makes the intent clearer
    in the route signature.
    """
    return user


async def get_current_patient_user(
    user: Annotated[TokenClaims, Depends(get_current_user)],
) -> "Patient":
    """FastAPI dependency: validate patient JWT and fetch patient entity.

    Use this on patient portal endpoints that require:
      1. Valid JWT with role="PATIENT"
      2. Patient entity fetched from database

    Rejects staff JWTs with 403 Forbidden.

    Usage:
        @router.patch("/portal/preferences")
        async def update_preferences(
            current_patient: Annotated[Patient, Depends(get_current_patient_user)],
            db: AsyncSession = Depends(get_write_db),
        ):
            ...

    Returns:
        Patient: The patient ORM entity identified by JWT sub claim.

    Raises:
        HTTPException 403: If the JWT role is not "PATIENT".
        HTTPException 404: If the patient entity is not found in the database.

    Design refs:
        US-067 TASK-005 (portal preferences endpoint)
    """
    # Import here to avoid circular dependency
    from app.db.deps import get_write_db
    from app.models.patient import Patient

    # Enforce PATIENT role
    if user.role != "PATIENT":
        logger.warning(
            "Patient endpoint accessed with non-PATIENT role %r",
            user.role,
            extra={
                "event_type": "auth_failure",
                "reason": "invalid_role",
                "user_id": user.sub,
                "role": user.role,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is only accessible to patients",
        )

    # Convert sub claim to UUID
    try:
        patient_id = uuid.UUID(user.sub)
    except (ValueError, AttributeError):
        logger.warning(
            "Invalid patient_id in JWT sub claim: %r",
            user.sub,
            extra={"event_type": "auth_failure", "reason": "invalid_patient_id"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid patient identifier in token",
        )

    # Fetch patient entity from database
    async for db in get_write_db():
        result = await db.execute(
            select(Patient).where(Patient.id == patient_id)
        )
        patient: Patient | None = result.scalar_one_or_none()

        if patient is None:
            logger.warning(
                "Patient not found for ID in JWT: %s",
                patient_id,
                extra={"event_type": "auth_failure", "reason": "patient_not_found"},
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient record not found",
            )

        return patient


def require_role(allowed_roles: list[str]):
    """FastAPI dependency factory: enforce role-based access control.

    Returns a dependency that validates the current user's JWT role is in the
    allowed list. Raises 403 Forbidden if the role is not permitted.

    Usage:
        STAFF_ROLES = ["NURSE", "PHYSICIAN", "CARE_COORDINATOR", "ADMIN"]

        @router.get("/notifications")
        async def list_notifications(
            current_user: Annotated[TokenClaims, Depends(require_role(STAFF_ROLES))]
        ):
            ...

    Args:
        allowed_roles: List of role strings that are permitted to access the endpoint.

    Returns:
        A FastAPI dependency function that validates the user's role.

    Raises:
        HTTPException 403: If the user's role is not in the allowed list.

    Design refs:
        US-067 TASK-004, SEC-006 (RBAC)
    """
    async def role_checker(
        user: Annotated[TokenClaims, Depends(get_current_user)],
    ) -> TokenClaims:
        if user.role not in allowed_roles:
            logger.warning(
                "Access denied: user role %r not in allowed roles %r",
                user.role,
                allowed_roles,
                extra={
                    "event_type": "rbac_failure",
                    "user_role": user.role,
                    "allowed_roles": allowed_roles,
                    "user_id": user.sub,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: role {user.role} not permitted for this endpoint",
            )
        return user

    return role_checker
