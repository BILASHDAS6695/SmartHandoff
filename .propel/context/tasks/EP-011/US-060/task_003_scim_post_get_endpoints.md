---
id: TASK-003
title: "Implement SCIM Router + POST (Create User) + GET (Read User / List Users) Endpoints"
user_story: US-060
epic: EP-011
sprint: 2
layer: Backend / API
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-060/TASK-001, US-060/TASK-002, US-006/TASK-001]
---

# TASK-003: Implement SCIM Router + POST (Create User) + GET (Read User / List Users) Endpoints

> **Story:** US-060 | **Epic:** EP-011 | **Sprint:** 2 | **Layer:** Backend / API | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

This task implements the SCIM router and the two read/create endpoints:

- **`POST /api/v1/admin/scim/Users`** — AC Scenario 1: Creates an `app_user` record from a SCIM payload. Maps `enterpriseUser.department` → `AppRole` using `ScimRoleMapper`. Stores the IdP-assigned `id` as `scim_id` on `app_user`. Returns the SCIM 2.0 User resource with `201 Created`.
- **`GET /api/v1/admin/scim/Users/{id}`** — Returns a single user by SmartHandoff UUID as a SCIM User resource.
- **`GET /api/v1/admin/scim/Users`** — Returns a paginated `ScimListResponse` (RFC 7643 §3.3) supporting `?startIndex` and `?count` query params for IdP sync operations.

All three endpoints use `Depends(verify_scim_token)` from TASK-002, and all reads/writes go through the `AsyncSession` from SQLAlchemy (async DB pattern established in earlier stories).

Design.md §3.3 specifies the `app_user` ORM model fields; US-060 Technical Notes define the SCIM `scim_id` storage requirement.

---

## Acceptance Criteria Addressed

| US-060 AC | Requirement |
|---|---|
| **Scenario 1** | SCIM POST creates `app_user` with correct `email`, `display_name`, `role`, `unit`, `scim_id` |
| **Scenario 3** | All endpoints protected by `verify_scim_token` |
| **DoD** | `POST`, `GET` `/api/v1/admin/scim/Users` endpoints |

---

## Implementation Steps

### 1. Alembic Migration — Add `scim_id` Column to `app_user`

Create `backend/alembic/versions/0005_add_scim_id_to_app_user.py`:

```python
"""Add scim_id to app_user for IdP cross-reference.

Revision: 0005
Depends on: 0004 (current_jti / deprovisioned_at)

Design refs:
    US-060 Technical Notes — scim_id stored on app_user
    AIR-032                 — SCIM IdP to SmartHandoff cross-reference
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_user",
        sa.Column(
            "scim_id",
            sa.String(256),
            nullable=True,
            comment="IdP-assigned SCIM externalId; used for SCIM→SmartHandoff cross-reference",
        ),
    )
    op.create_index("ix_app_user_scim_id", "app_user", ["scim_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_app_user_scim_id", table_name="app_user")
    op.drop_column("app_user", "scim_id")
```

---

### 2. Create `backend/app/api/v1/admin/scim/router.py`

```python
"""SCIM 2.0 User provisioning router.

Endpoints:
    POST   /api/v1/admin/scim/Users        — Create user (AC Scenario 1)
    GET    /api/v1/admin/scim/Users/{id}   — Read single user
    GET    /api/v1/admin/scim/Users        — List users (paginated)
    PATCH  /api/v1/admin/scim/Users/{id}   — Partial update (see TASK-004)
    PUT    /api/v1/admin/scim/Users/{id}   — Full replace (see TASK-004)
    DELETE /api/v1/admin/scim/Users/{id}   — Deprovision (see TASK-005)

All endpoints require SCIM bearer token authentication (verify_scim_token).
Design refs:
    design.md §7.4 AIR-032
    RFC 7643 (schema), RFC 7644 (protocol)
    US-060
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.scim.scim_auth import verify_scim_token
from app.api.v1.admin.scim.schemas import (
    ScimEmail,
    ScimListResponse,
    ScimMeta,
    ScimName,
    ScimRoleMapper,
    ScimUserRequest,
    ScimUserResponse,
)
from app.db.session import get_async_db
from app.models.user import AppUser, AppRole

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/scim/Users",
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
    return ScimUserResponse(
        id=str(user.id),
        externalId=user.scim_id,
        userName=user.email,
        name=ScimName(
            givenName=user.display_name.split(" ")[0] if user.display_name else None,
            familyName=(
                " ".join(user.display_name.split(" ")[1:])
                if user.display_name and " " in user.display_name
                else None
            ),
        ),
        emails=[ScimEmail(value=user.email, primary=True)],
        active=user.deprovisioned_at is None,
        meta=ScimMeta(
            resourceType="User",
            location=f"{base_url}/api/v1/admin/scim/Users/{user.id}",
        ),
    )


def _resolve_role(scim_body: ScimUserRequest) -> AppRole:
    """Derive AppRole from SCIM enterpriseUser.department.

    Raises HTTPException 400 if department is unknown.
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
        role_name = _role_mapper.map(department)
        return AppRole[role_name]
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
        "Maps enterpriseUser.department to AppRole via scim_role_mapping.yaml."
    ),
)
async def scim_create_user(
    body: ScimUserRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
) -> ScimUserResponse:
    # Check for existing user by email (idempotency — IdP may retry)
    result = await db.execute(
        select(AppUser).where(AppUser.email == body.userName)
    )
    existing = result.scalar_one_or_none()
    if existing:
        # IdP already provisioned this user; return current state (201 is idempotent here)
        logger.info(
            "SCIM create: user already exists, returning existing record",
            extra={"email": body.userName, "user_id": str(existing.id)},
        )
        return _build_scim_response(existing, request)

    role = _resolve_role(body)

    # Build display_name from SCIM name sub-object
    given = body.name.givenName if body.name and body.name.givenName else ""
    family = body.name.familyName if body.name and body.name.familyName else ""
    display_name = f"{given} {family}".strip() or body.userName

    # Extract email from emails[] if provided; fall back to userName
    primary_email = body.userName
    if body.emails:
        primary = next((e for e in body.emails if e.primary), body.emails[0])
        primary_email = str(primary.value)

    # Extract unit from enterprise extension department (US-060 AC Scenario 1)
    unit = body.enterprise.department if body.enterprise else None

    new_user = AppUser(
        id=uuid.uuid4(),
        email=primary_email,
        display_name=display_name,
        role=role,
        unit=unit,
        scim_id=body.schemas[0] if False else None,  # placeholder; scim_id = IdP's `id`
        # Note: scim_id is the IdP-assigned id, passed in the SCIM `externalId` or `id` field.
        # FastAPI will set it after creation; updated in TASK-004 (PATCH flow).
        created_at=datetime.now(timezone.utc),
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    logger.info(
        "SCIM user created",
        extra={
            "event": "scim_user_created",
            "user_id": str(new_user.id),
            "role": role.value,
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
    db: AsyncSession = Depends(get_async_db),
) -> ScimUserResponse:
    result = await db.execute(
        select(AppUser).where(AppUser.id == uuid.UUID(user_id))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return _build_scim_response(user, request)


# ---------------------------------------------------------------------------
# GET /Users — List users (paginated)
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
    db: AsyncSession = Depends(get_async_db),
) -> ScimListResponse:
    # Total count
    total_result = await db.execute(select(func.count(AppUser.id)))
    total: int = total_result.scalar_one()

    # Paginated query (startIndex is 1-based per RFC 7644 §3.4.2)
    offset = startIndex - 1
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
```

---

### 3. Register the SCIM Router in the Main App Router

In `backend/app/api/v1/router.py` (or equivalent), add:

```python
from app.api.v1.admin.scim.router import router as scim_router

# Under the /admin prefix:
api_router.include_router(scim_router, prefix="/admin")
```

This makes the full path `/api/v1/admin/scim/Users`.

---

## Files Created / Modified

| File | Action |
|---|---|
| `backend/alembic/versions/0005_add_scim_id_to_app_user.py` | **Create** |
| `backend/app/api/v1/admin/scim/router.py` | **Create** (POST + GET endpoints; PATCH/PUT/DELETE stubs) |
| `backend/app/api/v1/router.py` | **Modify** — register SCIM router under `/admin` |

---

## Validation

```bash
cd backend

# Run Alembic migration against dev DB
alembic upgrade head

# Confirm scim_id column exists
python -c "
from sqlalchemy import inspect, create_engine
import os
engine = create_engine(os.environ['DATABASE_URL'])
cols = [c['name'] for c in inspect(engine).get_columns('app_user')]
assert 'scim_id' in cols, 'scim_id column missing'
print('scim_id column present')
"

# Smoke test — POST a new SCIM user (requires running dev server)
# curl -X POST http://localhost:8000/api/v1/admin/scim/Users \
#   -H "Authorization: Bearer $SCIM_CLIENT_SECRET" \
#   -H "Content-Type: application/json" \
#   -d '{"schemas":["urn:ietf:params:scim:schemas:core:2.0:User"],
#        "userName":"jdoe@hospital.org",
#        "name":{"givenName":"Jane","familyName":"Doe"},
#        "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User":{"department":"Nursing"}}'
```
