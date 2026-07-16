---
id: TASK-004
title: "Implement `GET /api/v1/notifications` — Notification Audit Log Endpoint with Staff JWT and Read Replica Routing"
user_story: US-067
epic: EP-013
sprint: 2
layer: Backend / API
estimate: 1.5h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [TASK-001, US-064]
---

# TASK-004: Implement `GET /api/v1/notifications` — Notification Audit Log Endpoint with Staff JWT and Read Replica Routing

> **Story:** US-067 | **Epic:** EP-013 | **Sprint:** 2 | **Layer:** Backend / API | **Est:** 1.5 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-067 DoD specifies:

> *"`GET /api/v1/notifications?encounter_id={id}` endpoint: staff JWT required; returns delivery log"*
> *"Notification log API: use read replica (US-009) for query performance"*
> *"PHI minimisation in notification log: `recipient_phone_hash` (not plaintext phone), `recipient_email_hash`; only `encounter_id` and patient's own data accessible"*

This task creates the FastAPI router and handler for the notification audit log query. The endpoint returns the complete delivery history for a specific encounter, enabling care team members to verify that patients received critical communications.

Key design constraints:

1. **Staff JWT only** — role check: `NURSE`, `PHYSICIAN`, `CARE_COORDINATOR`, `ADMIN`; patient JWT is forbidden from this endpoint
2. **Read replica** — query routes to the PostgreSQL read replica via the read-session router (ADR-006, TR-010)
3. **No PHI in response** — `recipient_phone` and `recipient_email` are never returned; only the hashed versions stored at dispatch time are included
4. **Encounter scoping** — `encounter_id` is required; prevents unrestricted patient notification history exposure

Design decisions:

| Decision | Rationale |
|----------|-----------|
| Query parameter `encounter_id` (not path parameter) | Consistent with existing list endpoints; allows future addition of `patient_id`, `date_from` filters |
| Read replica session via `get_read_db` dependency | TR-010 mandates 100% of dashboard GET requests route to replica; avoids primary DB load |
| Response model excludes `recipient_phone`, `recipient_email` | PHI minimisation per US-067 Technical Notes; only hashed values returned |
| `template_name` included in response | AC Scenario 1 explicitly requires `template_name` in the response |
| `urgency_override` included in response | Required for audit evidence (AC Scenario 3) |
| 200 with empty list if no notifications found | Consistent RESTful behaviour; 404 would imply the encounter doesn't exist |
| Staff role guard via existing RBAC dependency | Reuses `require_role(["NURSE", "PHYSICIAN", "CARE_COORDINATOR", "ADMIN"])` from core auth module |

Design refs: ADR-006 (CQRS read replica), TR-010, design.md §3.3 (API layer), SEC-006, US-009.

---

## Acceptance Criteria Addressed

| US-067 AC | Requirement |
|---|---|
| **Scenario 1** | `GET /api/v1/notifications?encounter_id={id}` with valid staff JWT returns `type`, `channel`, `sent_at`, `delivery_status`, `template_name`; no PHI in content fields |
| **DoD** | Endpoint exists, staff JWT required, returns delivery log |

---

## Implementation Steps

### 1. Create response schema

Create `backend/app/schemas/notification_log.py`:

```python
"""Response schemas for the notification audit log API.

PHI minimisation (US-067 Technical Notes):
    - ``recipient_phone`` and ``recipient_email`` are NEVER returned.
    - Only ``recipient_phone_hash`` and ``recipient_email_hash`` (SHA-256 hex)
      are included for correlation purposes.
    - No patient name, DOB, or MRN in any field.

Design refs:
    US-067 AC Scenario 1, US-067 Technical Notes, ADR-007, SEC-006.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class NotificationLogItem(BaseModel):
    """Single notification delivery record returned by the audit log API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="Notification record UUID")
    notification_type: str = Field(
        alias="type",
        description="Notification type e.g. 'medication_reminder'",
    )
    channel: str = Field(description="SMS or EMAIL")
    sent_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when dispatch was attempted (None for OPTED_OUT)",
    )
    delivery_status: str = Field(
        description="PENDING | SENT | DELIVERED | FAILED | OPTED_OUT",
    )
    template_name: str = Field(description="SendGrid template key used for this notification")
    urgency_override: bool = Field(
        description="True if notification bypassed patient opt-out",
    )
    recipient_phone_hash: Optional[str] = Field(
        default=None,
        description="SHA-256 hash of recipient phone number (no plaintext PHI)",
    )
    recipient_email_hash: Optional[str] = Field(
        default=None,
        description="SHA-256 hash of recipient email address (no plaintext PHI)",
    )

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class NotificationLogResponse(BaseModel):
    """Paginated notification audit log response."""

    encounter_id: UUID
    total: int = Field(description="Total number of notification records for this encounter")
    items: list[NotificationLogItem]
```

### 2. Create the router

Create `backend/app/routers/notifications.py`:

```python
"""Notification audit log API router.

Endpoints:
    GET /api/v1/notifications — Returns notification delivery history for an encounter.

Auth:
    Staff JWT required. Patient JWTs are rejected (role guard).

Query:
    Routes to PostgreSQL read replica (ADR-006, TR-010) via ``get_read_db``.

PHI minimisation:
    Response never includes plaintext phone or email.
    Only hashed values (recipient_phone_hash, recipient_email_hash) are returned.

Design refs:
    US-067 AC Scenario 1, design.md §3.3, ADR-006, SEC-006.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.db.session import get_read_db
from app.models.notification import Notification
from app.schemas.notification_log import NotificationLogItem, NotificationLogResponse

router = APIRouter(prefix="/notifications", tags=["notifications"])

STAFF_ROLES = ["NURSE", "PHYSICIAN", "CARE_COORDINATOR", "ADMIN"]


@router.get(
    "",
    response_model=NotificationLogResponse,
    summary="List notification delivery history for an encounter",
    description=(
        "Returns all notification records for the specified encounter. "
        "Staff JWT required. PHI is excluded from all response fields."
    ),
)
async def list_notifications(
    encounter_id: UUID = Query(..., description="Encounter UUID to retrieve notifications for"),
    db: AsyncSession = Depends(get_read_db),
    _current_user=Depends(require_role(STAFF_ROLES)),
) -> NotificationLogResponse:
    """Return notification delivery history for an encounter.

    Queries the PostgreSQL read replica for performance (TR-010).
    Returns notification records ordered by ``sent_at`` descending.
    No PHI is included in the response body.

    Args:
        encounter_id: Required. Filters notifications to this encounter.
        db: Read-replica AsyncSession (injected via dependency).
        _current_user: Enforces staff role; raises 403 if patient JWT.

    Returns:
        NotificationLogResponse with total count and list of delivery records.
    """
    stmt = (
        select(Notification)
        .where(Notification.encounter_id == encounter_id)
        .order_by(Notification.sent_at.desc().nullslast())
    )
    result = await db.execute(stmt)
    records = result.scalars().all()

    items = [
        NotificationLogItem.model_validate(record)
        for record in records
    ]

    return NotificationLogResponse(
        encounter_id=encounter_id,
        total=len(items),
        items=items,
    )
```

### 3. Register the router in `backend/app/main.py`

```python
from app.routers.notifications import router as notifications_router

# Add alongside existing routers:
app.include_router(notifications_router, prefix="/api/v1")
```

### 4. Verify PHI is excluded from ORM serialisation

Confirm that `Notification.recipient_phone` and `Notification.recipient_email` are **not** included in `NotificationLogItem`. Only `recipient_phone_hash` and `recipient_email_hash` columns (set at dispatch time in US-064) are mapped to the response schema.

---

## Validation

```bash
cd backend

# Syntax check
python -c "
import ast, pathlib
for f in ['app/schemas/notification_log.py', 'app/routers/notifications.py']:
    ast.parse(pathlib.Path(f).read_text())
    print(f'Syntax check {f}: PASSED')
"

# Schema construction check
python -c "
from app.schemas.notification_log import NotificationLogItem, NotificationLogResponse
import uuid
item = NotificationLogItem.model_validate({
    'id': str(uuid.uuid4()),
    'type': 'medication_reminder',
    'channel': 'SMS',
    'sent_at': None,
    'delivery_status': 'OPTED_OUT',
    'template_name': 'medication_reminder',
    'urgency_override': False,
})
assert not hasattr(item, 'recipient_phone'), 'PHI field must not be present'
print('PHI exclusion check: PASSED')
print('Schema construction: PASSED')
"

# Manual API test (requires running server)
# curl -H 'Authorization: Bearer <staff_jwt>' \
#   'http://localhost:8000/api/v1/notifications?encounter_id=<uuid>'
```

---

## Files Involved

| File | Action | Notes |
|------|--------|-------|
| `backend/app/schemas/notification_log.py` | Create | `NotificationLogItem` and `NotificationLogResponse` Pydantic schemas |
| `backend/app/routers/notifications.py` | Create | `GET /api/v1/notifications` router with staff RBAC and read replica |
| `backend/app/main.py` | Modify | Register `notifications_router` under `/api/v1` |

---

## Definition of Done (Task-Level)

- [ ] `GET /api/v1/notifications?encounter_id={id}` endpoint implemented
- [ ] Staff JWT enforced via `require_role(STAFF_ROLES)` dependency
- [ ] Query routes to read replica via `get_read_db` dependency
- [ ] Response includes: `type`, `channel`, `sent_at`, `delivery_status`, `template_name`, `urgency_override`, hashed contact fields
- [ ] `recipient_phone` and `recipient_email` (plaintext) excluded from response schema
- [ ] Returns 200 with empty list if no notifications found for encounter
- [ ] Syntax checks pass
- [ ] Router registered in `main.py`
