---
id: TASK-004
title: "Implement `DELETE /api/v1/admin/users/{id}` Deprovisioning Endpoint"
user_story: US-059
epic: EP-011
sprint: 1
layer: Backend / API
estimate: 1.5h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-059/TASK-001, US-059/TASK-002]
---

# TASK-004: Implement `DELETE /api/v1/admin/users/{id}` Deprovisioning Endpoint

> **Story:** US-059 | **Epic:** EP-011 | **Sprint:** 1 | **Layer:** Backend / API | **Est:** 1.5 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

AC Scenario 1 requires that when `DELETE /api/v1/admin/users/{id}` is called, the deprovisioned user's active JWT `jti` is added to the Redis blocklist immediately and the user's `deprovisioned_at` timestamp is set in the database. The next API call from the deprovisioned user must return `401 Unauthorized` within 1 second of the deprovisioning call.

Design.md §7.4 AIR-032 specifies: *"Deprovisioning immediately revokes all active JWTs via token blocklist (Redis-compatible Cloud Memorystore)"*.

**Challenge — fetching the user's active jti:** The `jti` is stored in the JWT, which is in the client's memory. The backend must retrieve the `jti` from a persistent store. The solution: store the most-recently-issued `jti` in the `app_user` table at JWT issuance time so the deprovisioning endpoint can look it up.

This task therefore has two sub-components:
1. **DB schema** — add `current_jti` and `deprovisioned_at` columns to `app_user` via Alembic migration.
2. **JWT issuance patch** — update `issue_app_jwt()` to write the issued `jti` to `app_user.current_jti` in the DB.
3. **Deprovisioning endpoint** — look up `current_jti`, add to blocklist, set `deprovisioned_at`.

---

## Acceptance Criteria Addressed

| US-059 AC | Requirement |
|---|---|
| **Scenario 1** | `DELETE /api/v1/admin/users/{id}` → JWT in blocklist within 1 second; next API call → 401 |
| **DoD** | `DELETE /api/v1/admin/users/{id}` deprovisioning endpoint: adds JWT to blocklist + sets `app_user.deprovisioned_at` |

---

## Implementation Steps

### 1. Alembic Migration — Add `current_jti` and `deprovisioned_at` to `app_user`

Create `backend/alembic/versions/0004_add_user_jti_deprovisioning.py`:

```python
"""Add current_jti and deprovisioned_at to app_user.

Revision: 0004
Depends on: 0003 (existing app_user table migration)

Design refs:
    US-059 TASK-004 — deprovisioning via JWT blocklist
    AIR-032          — immediate JWT revocation on deprovision
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_user",
        sa.Column(
            "current_jti",
            sa.String(36),   # UUID string length
            nullable=True,
            comment="Most-recently-issued JWT ID; used for immediate revocation on deprovision",
        ),
    )
    op.add_column(
        "app_user",
        sa.Column(
            "deprovisioned_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC timestamp of admin-initiated deprovisioning; non-null = deprovisioned",
        ),
    )
    # Index for fast jti lookup during deprovisioning
    op.create_index("ix_app_user_current_jti", "app_user", ["current_jti"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_app_user_current_jti", table_name="app_user")
    op.drop_column("app_user", "deprovisioned_at")
    op.drop_column("app_user", "current_jti")
```

---

### 2. Update `app_user` SQLAlchemy Model

Add the two new columns to `backend/app/models/app_user.py`:

```python
from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

# Add these two columns to the AppUser class:
current_jti: Mapped[str | None] = mapped_column(
    String(36),
    nullable=True,
    index=True,
    unique=True,
    comment="Most-recently-issued JWT jti; updated on every login",
)
deprovisioned_at: Mapped[datetime | None] = mapped_column(
    DateTime(timezone=True),
    nullable=True,
    comment="Set by DELETE /api/v1/admin/users/{id}; non-null blocks login",
)
```

---

### 3. Patch `issue_app_jwt()` — Write `jti` to `app_user.current_jti`

In `backend/app/core/auth/jwt.py`, update `issue_app_jwt()` to accept an `AsyncSession` and persist the issued `jti`:

```python
from app.db.session import AsyncSessionLocal  # adjust import path to project convention

async def issue_app_jwt(oidc_claims: dict, db: AsyncSession) -> str:
    """Issue a SmartHandoff application JWT from validated OIDC claims.

    Also writes the issued jti to app_user.current_jti so that
    deprovisioning (TASK-004) can look up and blocklist the active token.

    Args:
        oidc_claims: Decoded and validated OIDC id_token claims.
        db: Active async DB session (injected by caller endpoint).

    Returns:
        str: Signed JWT string.
    """
    app_claims = _map_claims(oidc_claims)
    now = int(datetime.now(tz=timezone.utc).timestamp())
    jti = str(_uuid.uuid4())

    payload = {
        **app_claims,
        "jti": jti,
        "iat": now,
        "exp": now + _TOKEN_EXPIRY_SECONDS,
    }

    token = jwt.encode(payload, _jwt_signing_key(), algorithm=_ALGORITHM)

    # Persist jti so deprovisioning can blocklist this specific token
    from sqlalchemy import update as sa_update
    from app.models.app_user import AppUser
    await db.execute(
        sa_update(AppUser)
        .where(AppUser.oidc_sub == app_claims["sub"])
        .values(current_jti=jti)
    )
    await db.commit()

    logger.info(
        "Application JWT issued for sub=%s role=%s jti=%s exp_in=%ds",
        app_claims["sub"],
        app_claims["role"],
        jti,
        _TOKEN_EXPIRY_SECONDS,
        extra={"event_type": "jwt_issued", "jti": jti},
    )
    return token
```

> **Note:** Update the `POST /api/v1/auth/token` endpoint (US-056/TASK-004) to pass `db` when calling `issue_app_jwt()`.

---

### 4. Create `backend/app/api/v1/admin/users.py` — Deprovisioning Endpoint

```python
"""Admin user management router — deprovisioning.

Routes:
    DELETE /api/v1/admin/users/{user_id}  — deprovision user + blocklist JWT

Design refs:
    design.md §3.3 Routers — /admin/users
    design.md §8.3 RBAC — Admin role required
    AIR-032, SEC-009, US-059
"""
from __future__ import annotations

import logging
import uuid
from typing import Annotated

import redis
from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.jwt import get_current_user
from app.core.auth.rbac import require_permission
from app.core.auth.jwt_blocklist import add_to_blocklist
from app.db.session import get_db
from app.models.app_user import AppUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/users", tags=["admin"])


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_200_OK,
    summary="Deprovision a user — blocklist their active JWT and disable login",
)
async def deprovision_user(
    user_id: Annotated[uuid.UUID, Path(description="UUID of the user to deprovision")],
    current_user: Annotated[dict, Depends(require_permission("user", "write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Deprovision a staff user.

    Steps:
        1. Look up the target user in app_user.
        2. If the user has a current_jti, add it to the Redis blocklist.
        3. Set app_user.deprovisioned_at = now (UTC).
        4. Return 200 OK.

    The ``require_permission("user", "write")`` dependency enforces that
    only ADMIN role callers can reach this endpoint (design.md §8.3).

    Raises:
        HTTP 404: User not found.
        HTTP 409: User is already deprovisioned.
        HTTP 503: Redis unavailable (blocklist write failed).
    """
    from datetime import datetime, timezone
    from sqlalchemy import select

    # 1. Fetch target user
    result = await db.execute(
        select(AppUser).where(AppUser.id == user_id)
    )
    target_user: AppUser | None = result.scalar_one_or_none()

    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if target_user.deprovisioned_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already deprovisioned",
        )

    # 2. Blocklist active JWT if one exists
    if target_user.current_jti:
        # Compute a safe TTL: use 8h max (maximum JWT lifetime) since we
        # don't store exp separately; over-estimating TTL is safer than under.
        _MAX_JWT_LIFETIME = 8 * 3600
        try:
            import time
            add_to_blocklist(
                target_user.current_jti,
                int(time.time()) + _MAX_JWT_LIFETIME,
            )
        except redis.RedisError as exc:
            logger.error(
                "Redis error during deprovision blocklist write: user_id=%s jti=%s error=%s",
                user_id,
                target_user.current_jti,
                exc,
                extra={
                    "event_type": "redis_error",
                    "context": "deprovision",
                    "user_id": str(user_id),
                },
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to revoke active session — try again",
            ) from exc

    # 3. Set deprovisioned_at
    target_user.deprovisioned_at = datetime.now(timezone.utc)
    await db.commit()

    logger.info(
        "User deprovisioned: user_id=%s by admin=%s jti_blocklisted=%s",
        user_id,
        current_user.get("sub"),
        bool(target_user.current_jti),
        extra={
            "event_type": "user_deprovisioned",
            "target_user_id": str(user_id),
            "admin_sub": current_user.get("sub"),
        },
    )
    return {"message": "User deprovisioned successfully", "user_id": str(user_id)}
```

---

### 5. Register Router in `backend/app/main.py`

```python
from app.api.v1.admin.users import router as admin_users_router

app.include_router(admin_users_router, prefix="/api/v1")
```

---

## Validation

```bash
cd backend

# 1. Confirm migration applies cleanly
alembic upgrade head

# 2. Confirm the route is registered
python -c "
from app.main import app
routes = [r.path for r in app.routes]
assert '/api/v1/admin/users/{user_id}' in routes
print('Deprovision route: OK')
"

# 3. Run unit tests — no regressions
pytest tests/unit/ -q

# 4. Bandit SAST — no HIGH/CRITICAL in admin users module
bandit backend/app/api/v1/admin/users.py -ll
```
