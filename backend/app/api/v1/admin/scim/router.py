"""SCIM 2.0 User provisioning router.

Endpoints:
    POST   /api/v1/admin/scim/Users        — Create user (AC Scenario 1)
    GET    /api/v1/admin/scim/Users/{id}   — Read single user
    GET    /api/v1/admin/scim/Users        — List users (paginated, RFC 7644 §3.4.2)
    PATCH  /api/v1/admin/scim/Users/{id}   — Partial update (AC Scenario 4)
    PUT    /api/v1/admin/scim/Users/{id}   — Full replace (RFC 7644 §3.5.1)
    DELETE /api/v1/admin/scim/Users/{id}   — Deprovision (AC Scenario 2)

All endpoints require SCIM bearer token authentication (verify_scim_token).
SCIM DELETE and PATCH active=False delegate to deprovision_service to reuse
the JWT blocklist + audit logic from US-059.

Design refs:
    design.md §7.4 AIR-032
    RFC 7643 (SCIM Schema), RFC 7644 (SCIM Protocol)
    US-060
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.scim.scim_auth import verify_scim_token
from app.api.v1.admin.scim.schemas import (
    SCIM_ENTERPRISE_SCHEMA,
    ScimEmail,
    ScimListResponse,
    ScimMeta,
    ScimName,
    ScimPatchOp,
    ScimPatchOperation,
    ScimRoleMapper,
    ScimUserRequest,
    ScimUserResponse,
)
from app.db.deps import get_write_db
from app.models.app_user import AppUser

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/scim/Users",
    tags=["SCIM"],
    dependencies=[Depends(verify_scim_token)],
)

# Load role mapping once at module import (file is read-only at runtime)
_role_mapper = ScimRoleMapper.load()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_scim_response(user: AppUser, request: Request) -> ScimUserResponse:
    """Convert an AppUser ORM instance to a SCIM 2.0 User resource."""
    base_url = str(request.base_url).rstrip("/")
    full_name: str = getattr(user, "full_name", "") or ""
    parts = full_name.split(" ", 1)
    given = parts[0] if parts else None
    family = parts[1] if len(parts) > 1 else None

    return ScimUserResponse(
        id=str(user.id),
        externalId=user.scim_id,
        userName=user.email,
        name=ScimName(givenName=given, familyName=family),
        emails=[ScimEmail(value=user.email, primary=True)],
        active=user.deprovisioned_at is None,
        meta=ScimMeta(
            resourceType="User",
            location=f"{base_url}/api/v1/admin/scim/Users/{user.id}",
        ),
    )


def _resolve_role(scim_body: ScimUserRequest) -> str:
    """Derive role string from SCIM enterpriseUser.department.

    Raises:
        HTTPException 400 if department is missing or unknown.
    """
    department = (
        scim_body.enterprise.department
        if scim_body.enterprise and scim_body.enterprise.department
        else None
    )
    if not department:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "SCIM payload missing enterpriseUser.department. "
                "This field is required to assign a SmartHandoff role."
            ),
        )
    try:
        return _role_mapper.map(department)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


# ---------------------------------------------------------------------------
# POST — Create user (AC Scenario 1)
# ---------------------------------------------------------------------------

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ScimUserResponse,
    summary="SCIM: Create user",
    description=(
        "Creates an app_user record from a SCIM 2.0 User payload. "
        "Maps enterpriseUser.department → role via scim_role_mapping.yaml."
    ),
)
async def scim_create_user(
    body: ScimUserRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_write_db)],
) -> ScimUserResponse:
    """Create a new app_user from a SCIM payload (RFC 7644 §3.3)."""
    # Idempotency: if user with same email already exists return it
    result = await db.execute(
        select(AppUser).where(AppUser.email == body.userName)
    )
    existing: AppUser | None = result.scalar_one_or_none()
    if existing:
        logger.info(
            "SCIM create: user already exists — returning existing record",
            extra={"user_id": str(existing.id)},  # email intentionally omitted (SEC-011)
        )
        return _build_scim_response(existing, request)

    role_name = _resolve_role(body)

    # Build full_name from name sub-object
    given = body.name.givenName if body.name and body.name.givenName else ""
    family = body.name.familyName if body.name and body.name.familyName else ""
    full_name = f"{given} {family}".strip() or body.userName

    # Primary email — prefer the emails[] array, fall back to userName
    primary_email = body.userName
    if body.emails:
        primary = next((e for e in body.emails if e.primary), body.emails[0])
        primary_email = str(primary.value)

    # unit derives from department (US-060 AC Scenario 1)
    unit = body.enterprise.department if body.enterprise else None

    new_user = AppUser(
        id=uuid.uuid4(),
        idp_subject=body.userName,  # SCIM userName used as IdP subject
        email=primary_email,
        full_name=full_name,
        role=role_name,
        unit=unit,
        scim_id=body.externalId,  # IdP-assigned SCIM externalId (RFC 7643 §3.1)
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    logger.info(
        "SCIM user created",
        extra={
            "event": "scim_user_created",
            "user_id": str(new_user.id),
            "role": role_name,
        },
    )
    return _build_scim_response(new_user, request)


# ---------------------------------------------------------------------------
# GET /Users/{id} — Read single user
# ---------------------------------------------------------------------------

@router.get(
    "/{user_id}",
    response_model=ScimUserResponse,
    summary="SCIM: Get user by ID",
)
async def scim_get_user(
    user_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_write_db)],
) -> ScimUserResponse:
    """Return a single SCIM User resource by SmartHandoff UUID."""
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID format",
        )
    result = await db.execute(select(AppUser).where(AppUser.id == uid))
    user: AppUser | None = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return _build_scim_response(user, request)


# ---------------------------------------------------------------------------
# GET /Users — List users (paginated, RFC 7644 §3.4.2)
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=ScimListResponse,
    summary="SCIM: List users",
)
async def scim_list_users(
    request: Request,
    startIndex: int = Query(default=1, ge=1, description="RFC 7644 startIndex (1-based)"),
    count: int = Query(default=100, ge=1, le=500, description="RFC 7644 count (page size, max 500)"),
    db: Annotated[AsyncSession, Depends(get_write_db)],
) -> ScimListResponse:
    """Return a paginated SCIM ListResponse (RFC 7643 §3.3)."""
    # Total count
    total_result = await db.execute(select(func.count(AppUser.id)))
    total: int = total_result.scalar_one()

    # startIndex is 1-based (RFC 7644 §3.4.2)
    offset = max(startIndex - 1, 0)
    users_result = await db.execute(
        select(AppUser).offset(offset).limit(count)
    )
    users = users_result.scalars().all()

    return ScimListResponse(
        totalResults=total,
        startIndex=startIndex,
        itemsPerPage=len(users),
        Resources=[_build_scim_response(u, request) for u in users],
    )


# ---------------------------------------------------------------------------
# PATCH /Users/{id} — Partial update (AC Scenario 4)
# ---------------------------------------------------------------------------

@router.patch(
    "/{user_id}",
    response_model=ScimUserResponse,
    summary="SCIM: Partial update user",
    description=(
        "Processes SCIM PatchOp operations. "
        "Department changes trigger role update + audit_log entry. "
        "active=False triggers deprovisioning via deprovision_service."
    ),
)
async def scim_patch_user(
    user_id: str,
    body: ScimPatchOp,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_write_db)],
) -> ScimUserResponse:
    """Apply SCIM PatchOp operations to the user (RFC 7644 §3.5.2)."""
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID format",
        )

    result = await db.execute(select(AppUser).where(AppUser.id == uid))
    user: AppUser | None = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    for op in body.Operations:
        await _apply_patch_operation(op, user, db)

    await db.commit()
    await db.refresh(user)

    logger.info(
        "SCIM user patched",
        extra={"event": "scim_user_patched", "user_id": user_id},
    )
    return _build_scim_response(user, request)


async def _apply_patch_operation(
    op: ScimPatchOperation,
    user: AppUser,
    db: AsyncSession,
) -> None:
    """Apply a single SCIM PatchOp operation to the AppUser instance.

    Supported paths:
      - Contains ``"department"``        → role update + audit_log
      - ``"active"`` with value ``False``→ deprovisioning
      - ``"username"``                   → email update
      - ``"displayname"`` etc.           → full_name update

    Unknown paths are silently ignored (RFC 7644 §3.5.2 — unknown attributes
    SHOULD NOT cause an error for 'add' or 'replace' operations).
    """
    from app.services.deprovision_service import deprovision_user
    from app.models.audit_log import AuditLog

    path = (op.path or "").lower()
    value = op.value

    # Department → role mapping (AC Scenario 4)
    if "department" in path:
        if isinstance(value, str) and value:
            try:
                old_role = user.role
                new_role_name = _role_mapper.map(value)
                user.role = new_role_name
                user.unit = value  # sync unit to new department

                # Audit role change (DR-003, US-058 pattern)
                audit = AuditLog(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    user_role="system",
                    resource_type="user",
                    resource_id=str(user.id),
                    action="update",
                    endpoint="/api/v1/admin/scim/Users (PATCH)",
                    outcome="success",
                )
                db.add(audit)
                logger.info(
                    "SCIM PATCH: role changed from %s to %s",
                    old_role,
                    new_role_name,
                    extra={
                        "event": "scim_role_changed",
                        "user_id": str(user.id),
                        "old_role": old_role,
                        "new_role": new_role_name,
                    },
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(exc),
                ) from exc

    # active=False → deprovision (PATCH-based IdP deprovisioning)
    elif path == "active" and value is False:
        await deprovision_user(user.id, db=db)

    # userName → email
    elif path == "username":
        if isinstance(value, str) and value:
            user.email = value.lower().strip()

    # display name variants
    elif path in {"displayname", "name.givenname", "name.familyname"}:
        if isinstance(value, str):
            user.full_name = value


# ---------------------------------------------------------------------------
# PUT /Users/{id} — Full replace (RFC 7644 §3.5.1)
# ---------------------------------------------------------------------------

@router.put(
    "/{user_id}",
    response_model=ScimUserResponse,
    summary="SCIM: Full replace user",
)
async def scim_put_user(
    user_id: str,
    body: ScimUserRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_write_db)],
) -> ScimUserResponse:
    """Replace all user attributes from a full SCIM payload (RFC 7644 §3.5.1)."""
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID format",
        )

    result = await db.execute(select(AppUser).where(AppUser.id == uid))
    user: AppUser | None = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    new_role_name = _resolve_role(body)
    old_role = user.role

    # Apply full replacement
    given = body.name.givenName if body.name and body.name.givenName else ""
    family = body.name.familyName if body.name and body.name.familyName else ""
    user.full_name = f"{given} {family}".strip() or body.userName
    user.email = body.userName
    user.unit = body.enterprise.department if body.enterprise else None

    if new_role_name != user.role:
        user.role = new_role_name
        # Audit role change
        from app.models.audit_log import AuditLog
        audit = AuditLog(
            id=uuid.uuid4(),
            user_id=user.id,
            user_role="system",
            resource_type="user",
            resource_id=str(user.id),
            action="update",
            endpoint="/api/v1/admin/scim/Users (PUT)",
            outcome="success",
        )
        db.add(audit)
        logger.info(
            "SCIM PUT: role changed from %s to %s",
            old_role,
            new_role_name,
            extra={
                "event": "scim_role_changed_put",
                "user_id": str(user.id),
                "old_role": old_role,
                "new_role": new_role_name,
            },
        )

    await db.commit()
    await db.refresh(user)

    logger.info(
        "SCIM user replaced (PUT)",
        extra={"event": "scim_user_put", "user_id": user_id},
    )
    return _build_scim_response(user, request)


# ---------------------------------------------------------------------------
# DELETE /Users/{id} — Deprovision user (AC Scenario 2)
# ---------------------------------------------------------------------------

@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="SCIM: Deprovision user",
    description=(
        "Immediately deprovisions the user: sets deprovisioned_at, "
        "adds active JWT to Redis blocklist. Returns 204 No Content (RFC 7644 §3.6)."
    ),
)
async def scim_delete_user(
    user_id: str,
    db: Annotated[AsyncSession, Depends(get_write_db)],
) -> None:
    """Deprovision a user via SCIM DELETE (RFC 7644 §3.6).

    Delegates entirely to ``deprovision_service.deprovision_user()`` so that
    the JWT blocklist + audit logic is a single implementation (US-060 DoD).
    Returns 204 No Content on success (idempotent for already-deprovisioned users).
    """
    from app.services.deprovision_service import deprovision_user

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID format",
        )

    try:
        await deprovision_user(uid, db=db)
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    logger.info(
        "SCIM user deprovisioned",
        extra={"event": "scim_user_deleted", "user_id": user_id},
    )
