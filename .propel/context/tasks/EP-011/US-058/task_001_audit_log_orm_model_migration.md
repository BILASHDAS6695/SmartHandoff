---
id: TASK-001
title: "Create `AuditLog` SQLAlchemy ORM Model + Alembic Migration"
user_story: US-058
epic: EP-011
sprint: 1
layer: Backend / Database
estimate: 1.5h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-008/TASK-001, US-056/TASK-004]
---

# TASK-001: Create `AuditLog` SQLAlchemy ORM Model + Alembic Migration

> **Story:** US-058 | **Epic:** EP-011 | **Sprint:** 1 | **Layer:** Backend / Database | **Est:** 1.5 h
> **Status:** Done | **Date:** 2026-07-15

---

## Context

US-058 requires every PHI endpoint access to be recorded in an `audit_log` table. US-008 already provisions the PostgreSQL `audit_log` table schema, RLS policy (`DENY DELETE, UPDATE` for `app_write`), and the dedicated `audit_writer` DB role. This task creates the SQLAlchemy ORM model that maps to that existing table, plus a helper `write_audit_entry()` function used by the middleware (TASK-002).

If the `audit_log` table does **not** yet exist (US-008 not yet merged), this task also provides the Alembic migration that creates it.

Fields required by US-058 AC and DoD:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | Generated server-side |
| `user_id` | UUID | From JWT `sub`; nullable for pre-auth requests |
| `action` | ENUM | `READ`, `WRITE`, `DELETE`, `APPROVE`, `REJECT` |
| `entity_type` | VARCHAR(64) | e.g. `PATIENT`, `DOCUMENT`, `MEDICATION` |
| `entity_id` | UUID | ID of the accessed entity; nullable for collection GETs |
| `ip_address` | VARCHAR(45) | IPv4 or IPv6; extracted with `X-Forwarded-For` support |
| `user_agent` | TEXT | From `User-Agent` header; nullable |
| `timestamp` | TIMESTAMPTZ | UTC, server-set on insert; immutable |

> **PHI note:** No PHI field values are stored in `audit_log`. Only entity identifiers (`entity_id`, `entity_type`) and user identity (`user_id`) are recorded. Per DR-003 the table is append-only enforced by RLS.

---

## Acceptance Criteria Addressed

| US-058 AC | Requirement |
|---|---|
| **Scenario 1** | `audit_log` entry created with correct fields on `GET /api/v1/patients/{id}` |
| **Scenario 2** | `audit_log` entry created with `action=APPROVE`, `entity_type=DOCUMENT` on document approval |
| **DoD** | `audit_log` ORM model: `user_id`, `action`, `entity_type`, `entity_id`, `ip_address`, `user_agent`, `timestamp` |

---

## Implementation Steps

### 1. Create `backend/app/models/audit_log.py`

```python
"""SQLAlchemy ORM model for the audit_log table.

Maps to the append-only PostgreSQL table enforced by RLS (US-008).
PHI field values are NEVER stored here — only entity identifiers
and user identity.

Design refs:
    design.md §6.1 DR-003  — Audit log immutability
    design.md §8.4          — PHI Protection Layers
    SEC-006, BR-023         — Audit requirements
    US-008                  — Table + RLS provisioning
    US-058                  — This story: writes via AuditLogMiddleware
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditAction(str, enum.Enum):
    """Permitted action values for audit_log.action.

    Enumerated to prevent free-text injection into the audit record.
    """
    READ = "READ"
    WRITE = "WRITE"
    DELETE = "DELETE"
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class AuditLog(Base):
    """Immutable PHI access record.

    Rows are INSERT-only; UPDATE and DELETE are blocked by PostgreSQL RLS
    policy ``audit_immutable`` (created by US-008 migration).

    All timestamps are stored as UTC TIMESTAMPTZ. The ``timestamp`` column
    uses ``server_default`` so the DB sets it — application clock skew cannot
    affect the record.
    """
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="JWT sub claim; null for unauthenticated or pre-auth requests",
    )
    action: Mapped[AuditAction] = mapped_column(
        Enum(AuditAction, name="audit_action_enum", create_type=False),
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Resource type: PATIENT, DOCUMENT, MEDICATION, etc.",
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="ID of the accessed entity; null for collection-level endpoints",
    )
    ip_address: Mapped[str | None] = mapped_column(
        String(45),  # max IPv6 length
        nullable=True,
    )
    user_agent: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="UTC insert timestamp; immutable after creation",
    )
```

### 2. Create `backend/app/db/audit.py` — write helper

The middleware (TASK-002) and RBAC module (US-057/TASK-002) both call `write_audit_entry()` and `write_rbac_audit_entry()`. Define them here as the single write path to `audit_log`.

```python
"""Database write helpers for the audit_log table.

All writes use the ``audit_writer`` database role (US-008) which has
INSERT-only permission on audit_log. This file is the sole write path —
no other module inserts to audit_log directly.

Usage:
    from app.db.audit import write_audit_entry

    await write_audit_entry(
        db=db,
        user_id=current_user.sub,
        action=AuditAction.READ,
        entity_type="PATIENT",
        entity_id=patient_id,
        ip_address=request.client.host,
        user_agent=request.headers.get("User-Agent"),
    )
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditAction, AuditLog


async def write_audit_entry(
    *,
    db: AsyncSession,
    user_id: Optional[uuid.UUID],
    action: AuditAction,
    entity_type: str,
    entity_id: Optional[uuid.UUID] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    """Insert one row into audit_log.

    Silently absorbs database errors to ensure audit failures never
    block the primary request. Errors are emitted to Cloud Logging
    at ERROR severity without PHI field values.

    Args:
        db:          Async SQLAlchemy session bound to the audit_writer role.
        user_id:     UUID from JWT sub claim; None for unauthenticated paths.
        action:      One of AuditAction enum values.
        entity_type: Uppercase resource type string, e.g. "PATIENT".
        entity_id:   UUID of the specific entity accessed; None for collections.
        ip_address:  Caller IP; supports IPv4 and IPv6 (max 45 chars).
        user_agent:  Value of User-Agent request header.
    """
    import logging
    logger = logging.getLogger(__name__)

    try:
        entry = AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.add(entry)
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        # Log audit failure without PHI. Do NOT re-raise — audit write
        # failures must never block the main request (availability > audit).
        logger.error(
            "audit_log write failed",
            extra={
                "event": "audit_write_failure",
                "entity_type": entity_type,
                "action": action.value,
                "error": str(exc),
            },
        )


async def write_rbac_audit_entry(
    *,
    db: AsyncSession,
    user_id: Optional[uuid.UUID],
    action: AuditAction,
    entity_type: str,
    entity_id: Optional[uuid.UUID] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    """Alias for write_audit_entry for RBAC denial events.

    Provided as a separate symbol so that app/core/auth/rbac.py (US-057)
    can import it by name without circular dependency risk.
    """
    await write_audit_entry(
        db=db,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
```

### 3. Create Alembic migration (conditional on US-008 not yet merged)

If US-008 has **not** yet created the `audit_log` table, create an Alembic migration:

```bash
cd backend
alembic revision --autogenerate -m "create_audit_log_table"
```

Then verify the generated migration includes:

- `CREATE TYPE audit_action_enum AS ENUM ('READ','WRITE','DELETE','APPROVE','REJECT')`
- `CREATE TABLE audit_log (id UUID PRIMARY KEY, user_id UUID, action audit_action_enum NOT NULL, entity_type VARCHAR(64) NOT NULL, entity_id UUID, ip_address VARCHAR(45), user_agent TEXT, timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW())`
- RLS policy grant: `GRANT INSERT ON audit_log TO audit_writer`

> **If US-008 is already merged:** Verify the existing migration includes all required columns. If `user_agent` or `entity_id` columns are missing, create a new migration: `alembic revision -m "add_user_agent_entity_id_to_audit_log"`.

### 4. Register `AuditLog` model in `backend/app/models/__init__.py`

```python
from app.models.audit_log import AuditLog, AuditAction  # noqa: F401
```

---

## Validation

```bash
# Confirm ORM model imports cleanly
cd backend
python -c "from app.models.audit_log import AuditLog, AuditAction; print('OK', list(AuditAction))"
# Expected: OK ['READ', 'WRITE', 'DELETE', 'APPROVE', 'REJECT']

# Confirm write helper imports cleanly
python -c "from app.db.audit import write_audit_entry, write_rbac_audit_entry; print('OK')"

# Run migration (against dev DB)
alembic upgrade head
```

---

## Files Touched

| File | Action |
|---|---|
| `backend/app/models/audit_log.py` | Create — `AuditLog` ORM model + `AuditAction` enum |
| `backend/app/db/audit.py` | Create — `write_audit_entry()` + `write_rbac_audit_entry()` helpers |
| `backend/app/models/__init__.py` | Update — register `AuditLog`, `AuditAction` imports |
| `backend/alembic/versions/<rev>_create_audit_log_table.py` | Create (if US-008 not merged) |

---

## Definition of Done Checklist

- [ ] `backend/app/models/audit_log.py` exists; `AuditLog` and `AuditAction` importable
- [ ] `backend/app/db/audit.py` exists; `write_audit_entry()` and `write_rbac_audit_entry()` importable
- [ ] Alembic migration covers all 8 columns; `alembic upgrade head` completes without error on dev DB
- [ ] No PHI field values present in the model or write helper
