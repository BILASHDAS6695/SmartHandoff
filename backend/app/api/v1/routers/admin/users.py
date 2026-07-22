"""Admin user management router — RBAC-protected endpoints.

Routes:
    GET    /api/v1/admin/users            — list users
    GET    /api/v1/admin/users/{user_id}  — get single user
    POST   /api/v1/admin/users            — create user
    PATCH  /api/v1/admin/users/{user_id}  — update user
    DELETE /api/v1/admin/users/{user_id}  — deprovision user + blocklist JWT (US-059)

Design refs:
    design.md §3.3 Routers — /admin/users
    design.md §8.3 RBAC — Admin role required
    AIR-032, SEC-009, US-059, US-060
"""
from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.jwt import TokenClaims
from app.core.auth.rbac import require_permission
from app.db.deps import get_write_db
from app.models.app_user import AppUser
from app.services.deprovision_service import deprovision_user as _deprovision_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


@router.get("")
async def list_users(
    current_user: Annotated[TokenClaims, Depends(require_permission("user", "list"))],
) -> dict:
    """List users — requires user:list permission (ADMIN only)."""
    return {"users": [], "user": current_user.sub}


@router.get("/{user_id}")
async def get_user(
    user_id: uuid.UUID,
    current_user: Annotated[TokenClaims, Depends(require_permission("user", "read"))],
) -> dict:
    """Get a single user — requires user:read permission (ADMIN only)."""
    return {"user_id": str(user_id), "user": current_user.sub}


@router.post("")
async def create_user(
    current_user: Annotated[TokenClaims, Depends(require_permission("user", "write"))],
) -> dict:
    """Create a user — requires user:write permission (ADMIN only)."""
    return {"created": True, "user": current_user.sub}


@router.patch("/{user_id}")
async def update_user(
    user_id: uuid.UUID,
    current_user: Annotated[TokenClaims, Depends(require_permission("user", "write"))],
) -> dict:
    """Update a user — requires user:write permission (ADMIN only)."""
    return {"user_id": str(user_id), "user": current_user.sub}


# ── DELETE /api/v1/admin/users/{user_id} ─────────────────────────────────────

@router.delete(
    "/{user_id}",
    status_code=status.HTTP_200_OK,
    summary="Deprovision a user — blocklist their active JWT and disable login",
)
async def deprovision_user(
    user_id: Annotated[uuid.UUID, Path(description="UUID of the user to deprovision")],
    current_user: Annotated[TokenClaims, Depends(require_permission("user", "write"))],
    db: Annotated[AsyncSession, Depends(get_write_db)],
) -> dict:
    """Deprovision a staff user.

    Delegates to :func:`app.services.deprovision_service.deprovision_user` which:
        1. Looks up the target user in ``app_user``.
        2. Blocklists the active JWT (if present) via Redis.
        3. Sets ``app_user.deprovisioned_at`` = now (UTC).
        4. Writes an ``AuditLog`` entry.

    The ``require_permission("user", "write")`` dependency enforces that
    only ADMIN role callers can reach this endpoint (design.md §8.3).

    Raises:
        HTTP 404: User not found.
        HTTP 503: Redis unavailable (blocklist write failed — fail-closed).

    Note:
        Already-deprovisioned users are handled idempotently — no error is raised.
    """
    try:
        await _deprovision_user(user_id, db=db)
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    logger.info(
        "User deprovisioned via admin endpoint: user_id=%s by admin=%s",
        user_id,
        current_user.sub,
        extra={
            "event_type": "user_deprovisioned",
            "target_user_id": str(user_id),
            "admin_sub": current_user.sub,
        },
    )
    return {"message": "User deprovisioned successfully", "user_id": str(user_id)}
