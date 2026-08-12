"""Admin user management router — RBAC-protected endpoints.

Routes:
    GET    /api/v1/admin/users            — list users
    GET    /api/v1/admin/users/{user_id}  — get single user
    POST   /api/v1/admin/users            — create user
    PATCH  /api/v1/admin/users/{user_id}  — update user
    DELETE /api/v1/admin/users/{user_id}  — deprovision user + blocklist JWT (US-059)
    POST   /api/v1/admin/users/{user_id}/re-enable  — re-enable a deprovisioned user

Design refs:
    design.md §3.3 Routers — /admin/users
    design.md §8.3 RBAC — Admin role required
    AIR-032, SEC-009, US-059, US-060
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.jwt import TokenClaims
from app.core.auth.rbac import load_rbac_matrix, require_permission
from app.db.deps import get_read_db, get_write_db
from app.models.app_user import AppUser
from app.schemas.user import (
    BulkRoleAssignRequest,
    BulkRoleAssignResponse,
    BulkRoleAssignResult,
    UserCreateRequest,
    UserListResponse,
    UserResponse,
    UserUpdateRequest,
)
from app.services.deprovision_service import deprovision_user as _deprovision_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


def _get_valid_roles() -> frozenset[str]:
    """Return lowercase role names from the RBAC permission matrix.

    Keeps admin user roles consistent with ``rbac_permissions.yaml``.
    """
    matrix = load_rbac_matrix()
    return frozenset(role.lower() for role in matrix.keys())


def _raise_for_invalid_role(role: str) -> None:
    """Validate role against the RBAC matrix roles."""
    valid = _get_valid_roles()
    if role not in valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role '{role}'. Allowed: {sorted(valid)}",
        )


# ── GET /api/v1/admin/users ──────────────────────────────────────────────────

@router.get(
    "",
    response_model=UserListResponse,
    summary="List staff users (ADMIN only)",
)
async def list_users(
    current_user: Annotated[TokenClaims, Depends(require_permission("user", "list"))],
    db: Annotated[AsyncSession, Depends(get_read_db)],
) -> UserListResponse:
    """List all staff users from ``app_user``.

    Requires ``user:list`` permission, which is restricted to the ADMIN role.
    """
    total_result = await db.execute(select(func.count()).select_from(AppUser))
    total: int = total_result.scalar_one()

    rows_result = await db.execute(select(AppUser).order_by(AppUser.full_name))
    rows = rows_result.scalars().all()

    return UserListResponse(
        users=[UserResponse.model_validate(row) for row in rows],
        total=total,
    )


# ── GET /api/v1/admin/users/{user_id} ────────────────────────────────────────

@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Get a single staff user (ADMIN only)",
)
async def get_user(
    user_id: uuid.UUID,
    current_user: Annotated[TokenClaims, Depends(require_permission("user", "read"))],
    db: Annotated[AsyncSession, Depends(get_read_db)],
) -> UserResponse:
    """Return a single ``app_user`` record by UUID."""
    result = await db.execute(select(AppUser).where(AppUser.id == user_id))
    user: AppUser | None = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return UserResponse.model_validate(user)


# ── POST /api/v1/admin/users ─────────────────────────────────────────────────

@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a staff user (ADMIN only)",
)
async def create_user(
    payload: UserCreateRequest,
    current_user: Annotated[TokenClaims, Depends(require_permission("user", "write"))],
    db: Annotated[AsyncSession, Depends(get_write_db)],
) -> UserResponse:
    """Create a new ``app_user`` record via the admin UI.

    ``idp_subject`` is derived deterministically from the supplied email so
    the record is consistent with OIDC-provisioned users while remaining
    editable in the admin panel before first login.
    """
    _raise_for_invalid_role(payload.role)

    existing_result = await db.execute(
        select(AppUser).where(AppUser.email == payload.email)
    )
    if existing_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )

    idp_subject = f"admin-created:{payload.email}"
    new_user = AppUser(
        id=uuid.uuid4(),
        idp_subject=idp_subject,
        email=str(payload.email),
        full_name=payload.full_name,
        role=payload.role,
        unit=payload.unit,
        is_active=True,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    logger.info(
        "User created via admin endpoint: user_id=%s by admin=%s",
        new_user.id,
        current_user.sub,
        extra={
            "event_type": "user_created",
            "target_user_id": str(new_user.id),
            "admin_sub": current_user.sub,
        },
    )
    return UserResponse.model_validate(new_user)


# ── PATCH /api/v1/admin/users/{user_id} ──────────────────────────────────────

@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    summary="Update a staff user (ADMIN only)",
)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdateRequest,
    current_user: Annotated[TokenClaims, Depends(require_permission("user", "write"))],
    db: Annotated[AsyncSession, Depends(get_write_db)],
) -> UserResponse:
    """Partially update an ``app_user`` record."""
    result = await db.execute(select(AppUser).where(AppUser.id == user_id))
    user: AppUser | None = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    updates = payload.model_dump(exclude_unset=True)

    if "role" in updates:
        _raise_for_invalid_role(updates["role"])

    if "email" in updates and updates["email"] != user.email:
        email_check = await db.execute(
            select(AppUser).where(
                AppUser.email == updates["email"],
                AppUser.id != user_id,
            )
        )
        if email_check.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this email already exists",
            )

    for field, value in updates.items():
        setattr(user, field, value)

    await db.commit()
    await db.refresh(user)

    logger.info(
        "User updated via admin endpoint: user_id=%s by admin=%s",
        user_id,
        current_user.sub,
        extra={
            "event_type": "user_updated",
            "target_user_id": str(user_id),
            "admin_sub": current_user.sub,
        },
    )
    return UserResponse.model_validate(user)


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
        HTTP 409: User is already deprovisioned.
        HTTP 503: Redis unavailable (blocklist write failed — fail-closed).
    """
    result = await db.execute(select(AppUser).where(AppUser.id == user_id))
    user: AppUser | None = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if user.deprovisioned_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already deprovisioned",
        )

    try:
        await _deprovision_user(user_id, db=db)
    except LookupError:
        # Defensive: race between the check above and the service lookup.
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


# ── POST /api/v1/admin/users/{user_id}/re-enable ─────────────────────────────

@router.post(
    "/{user_id}/re-enable",
    response_model=UserResponse,
    summary="Re-enable a deprovisioned staff user (ADMIN only)",
)
async def reenable_user(
    user_id: Annotated[uuid.UUID, Path(description="UUID of the user to re-enable")],
    current_user: Annotated[TokenClaims, Depends(require_permission("user", "write"))],
    db: Annotated[AsyncSession, Depends(get_write_db)],
) -> UserResponse:
    """Re-enable a previously deprovisioned user.

    Clears ``deprovisioned_at`` and sets ``is_active=True``.  The user's
    JWT blocklist entry is NOT removed (US-059): the previous token remains
    revoked; re-enabling only allows future logins to succeed.
    """
    result = await db.execute(select(AppUser).where(AppUser.id == user_id))
    user: AppUser | None = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if user.deprovisioned_at is None and user.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already active",
        )

    user.deprovisioned_at = None
    user.is_active = True
    user.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(user)

    logger.info(
        "User re-enabled via admin endpoint: user_id=%s by admin=%s",
        user_id,
        current_user.sub,
        extra={
            "event_type": "user_reenabled",
            "target_user_id": str(user_id),
            "admin_sub": current_user.sub,
        },
    )
    return UserResponse.model_validate(user)


# ── POST /api/v1/admin/users/bulk-assign-roles ───────────────────────────────

@router.post(
    "/bulk-assign-roles",
    response_model=BulkRoleAssignResponse,
    summary="Bulk assign a role to multiple users (ADMIN only)",
)
async def bulk_assign_roles(
    payload: BulkRoleAssignRequest,
    current_user: Annotated[TokenClaims, Depends(require_permission("user", "write"))],
    db: Annotated[AsyncSession, Depends(get_write_db)],
) -> BulkRoleAssignResponse:
    """Assign the same role to many users in one request.

    Reads existing ``app_user`` records from the database, validates the
    requested role against the RBAC matrix, and updates every matching
    active or inactive user.  Returns a detailed breakdown of which users
    were updated and which IDs did not exist.
    """
    _raise_for_invalid_role(payload.role)

    result = await db.execute(select(AppUser).where(AppUser.id.in_(payload.user_ids)))
    users: list[AppUser] = list(result.scalars().all())

    found_ids = {user.id for user in users}
    not_found = [uid for uid in payload.user_ids if uid not in found_ids]

    assigned: list[BulkRoleAssignResult] = []
    for user in users:
        previous_role = user.role
        user.role = payload.role
        user.updated_at = datetime.now(timezone.utc)
        assigned.append(
            BulkRoleAssignResult(
                user_id=user.id,
                previous_role=previous_role,
                new_role=payload.role,
            )
        )

    if assigned:
        await db.commit()
        for item in assigned:
            logger.info(
                "Bulk role assignment: user_id=%s %s -> %s by admin=%s",
                item.user_id,
                item.previous_role,
                item.new_role,
                current_user.sub,
                extra={
                    "event_type": "user_role_assigned",
                    "target_user_id": str(item.user_id),
                    "admin_sub": current_user.sub,
                    "previous_role": item.previous_role,
                    "new_role": item.new_role,
                },
            )

    return BulkRoleAssignResponse(
        assigned=assigned,
        not_found=not_found,
        total_requested=len(payload.user_ids),
        total_assigned=len(assigned),
    )
