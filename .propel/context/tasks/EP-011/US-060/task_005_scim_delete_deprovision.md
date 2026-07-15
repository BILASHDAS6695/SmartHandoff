---
id: TASK-005
title: "Implement SCIM DELETE (Deprovision User) Endpoint"
user_story: US-060
epic: EP-011
sprint: 2
layer: Backend / API
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-060/TASK-002, US-060/TASK-003, US-059/TASK-004]
---

# TASK-005: Implement SCIM DELETE (Deprovision User) Endpoint

> **Story:** US-060 | **Epic:** EP-011 | **Sprint:** 2 | **Layer:** Backend / API | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

AC Scenario 2 requires that when the hospital IdP sends `DELETE /api/v1/admin/scim/Users/{id}`, the user is immediately deprovisioned: `app_user.deprovisioned_at` is set and any active JWTs for that user are added to the Redis blocklist within 1 second.

US-060 DoD explicitly states: *"SCIM DELETE: calls same `deprovisioning_service.deprovision_user(user_id)` as manual deprovision (US-059)"*. This means the SCIM DELETE endpoint must **not** duplicate the deprovisioning logic — it delegates entirely to the `deprovisioning_service` module implemented in US-059/TASK-004. This keeps the security-critical JWT revocation path as a single implementation that is tested and audited in one place.

The endpoint returns `204 No Content` on success (RFC 7644 §3.6 — DELETE response), or `404` if the user does not exist.

---

## Acceptance Criteria Addressed

| US-060 AC | Requirement |
|---|---|
| **Scenario 2** | SCIM DELETE → `deprovisioned_at` set; active JWTs blocklisted within 1 second; subsequent API calls → 401 |
| **Scenario 3** | Endpoint protected by `verify_scim_token` |
| **DoD** | `DELETE /api/v1/admin/scim/Users` endpoint; reuses `deprovisioning_service.deprovision_user()` |

---

## Implementation Steps

### 1. Create `backend/app/services/deprovision_service.py`

> **Note:** If US-059/TASK-004 already created a deprovisioning function inline in the endpoint handler, refactor it into this shared service module now. The SCIM router cannot import directly from an endpoint module.

```python
"""User deprovisioning service — shared between manual and SCIM-triggered flows.

Called by:
  - DELETE /api/v1/admin/users/{id}  (US-059/TASK-004 — manual deprovision)
  - DELETE /api/v1/admin/scim/Users/{id}  (US-060/TASK-005 — SCIM deprovision)
  - SCIM PATCH active=False  (US-060/TASK-004 — PATCH-based deprovision)

Responsibilities:
  1. Look up app_user.current_jti
  2. Add current_jti to Redis blocklist via JwtBlocklistService (US-059/TASK-001)
  3. Set app_user.deprovisioned_at = UTC now
  4. Write audit_log entry

Design refs:
    design.md §7.4 AIR-032   — SCIM deprovisioning / JWT revocation
    US-059/TASK-001           — JwtBlocklistService
    US-059/TASK-004           — deprovision endpoint + DB schema
    SEC-009, SEC-011
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.auth.jwt_blocklist import add_to_blocklist
from app.models.audit import AuditLog, AuditAction
from app.models.user import AppUser

logger = logging.getLogger(__name__)


async def deprovision_user(user_id: uuid.UUID, db: AsyncSession) -> AppUser:
    """Deprovision a user: blocklist JWT + set deprovisioned_at + audit.

    Args:
        user_id: The SmartHandoff UUID of the user to deprovision.
        db:      Open async SQLAlchemy session.

    Returns:
        The updated AppUser instance (deprovisioned_at is set).

    Raises:
        ValueError: if no user with user_id exists in the database.
    """
    result = await db.execute(select(AppUser).where(AppUser.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise ValueError(f"User {user_id} not found")

    # Already deprovisioned — idempotent: no-op
    if user.deprovisioned_at is not None:
        logger.info(
            "deprovision_user: user already deprovisioned (idempotent no-op)",
            extra={"user_id": str(user_id)},
        )
        return user

    # 1. Blocklist current JWT (if one has been issued — current_jti may be None
    #    for users who were never logged in)
    if user.current_jti:
        # We need the JWT exp to set Redis TTL. If not stored, use a safe default
        # (JWT max lifetime = 8 hours = 28800 seconds from now).
        import time
        exp = getattr(user, "current_jwt_exp", None) or (int(time.time()) + 28800)
        add_to_blocklist(user.current_jti, exp)
        logger.info(
            "deprovision_user: JWT blocklisted",
            extra={"user_id": str(user_id), "jti": user.current_jti},
        )

    # 2. Set deprovisioned_at
    user.deprovisioned_at = datetime.now(timezone.utc)

    # 3. Write audit log
    audit = AuditLog(
        id=uuid.uuid4(),
        user_id=user.id,
        action=AuditAction.USER_DEPROVISIONED,
        details={"source": "deprovision_service"},
        created_at=datetime.now(timezone.utc),
    )
    db.add(audit)

    await db.commit()
    await db.refresh(user)

    logger.info(
        "deprovision_user: complete",
        extra={"event": "user_deprovisioned", "user_id": str(user_id)},
    )
    return user
```

---

### 2. Add DELETE Handler to `backend/app/api/v1/admin/scim/router.py`

```python
# ---------------------------------------------------------------------------
# DELETE /Users/{id} — Deprovision user (AC Scenario 2)
# ---------------------------------------------------------------------------

from app.services.deprovision_service import deprovision_user


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
    db: AsyncSession = Depends(get_async_db),
) -> None:
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID format",
        )

    try:
        await deprovision_user(uid, db=db)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    logger.info(
        "SCIM user deprovisioned",
        extra={"event": "scim_user_deleted", "user_id": user_id},
    )
    # FastAPI returns 204 with no body when the function returns None
```

---

### 3. Update US-059/TASK-004 Endpoint to Use Shared Service

In `backend/app/api/v1/admin/users.py` (the manual deprovision endpoint from US-059/TASK-004), replace the inline deprovisioning logic with a call to `deprovision_service`:

```python
# Before (inline in endpoint):
# user.deprovisioned_at = datetime.now(timezone.utc)
# add_to_blocklist(user.current_jti, ...)
# db.add(audit_entry)

# After (delegate to shared service):
from app.services.deprovision_service import deprovision_user

@router.delete("/{user_id}", status_code=204)
async def deprovision_user_endpoint(user_id: str, db: AsyncSession = Depends(get_async_db)):
    try:
        await deprovision_user(uuid.UUID(user_id), db=db)
    except ValueError:
        raise HTTPException(404, "User not found")
```

> **Important:** Only refactor if US-059/TASK-004 has not yet been merged. If it is already in `main`, create a separate refactor commit on the same branch as US-060 to avoid merge conflicts.

---

## Files Created / Modified

| File | Action |
|---|---|
| `backend/app/services/deprovision_service.py` | **Create** (or extract from US-059/TASK-004) |
| `backend/app/api/v1/admin/scim/router.py` | **Modify** — add `DELETE` handler |
| `backend/app/api/v1/admin/users.py` | **Modify** — delegate to `deprovision_service` |

---

## Validation

```bash
cd backend

# Confirm deprovision_service imports correctly
python -c "
from app.services.deprovision_service import deprovision_user
print('deprovision_user importable:', deprovision_user)
"

# Confirm DELETE route is registered
python -c "
from app.main import app
routes = [(r.path, list(r.methods)) for r in app.routes]
scim_delete = [r for r in routes if 'scim' in r[0] and 'DELETE' in r[1]]
print('SCIM DELETE routes:', scim_delete)
assert scim_delete, 'No SCIM DELETE route found'
"

# Verify idempotency: calling deprovision_user twice should not raise
# (unit test covers this — see TASK-006)
```
