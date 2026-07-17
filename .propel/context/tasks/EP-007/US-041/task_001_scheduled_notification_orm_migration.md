---
id: TASK-001
title: "`scheduled_notification` SQLAlchemy ORM Model + Alembic Migration"
user_story: US-041
epic: EP-007
sprint: 2
layer: Backend / Database
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-006, US-039/TASK-004]
---

# TASK-001: `scheduled_notification` SQLAlchemy ORM Model + Alembic Migration

> **Story:** US-041 | **Epic:** EP-007 | **Sprint:** 2 | **Layer:** Backend / Database | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-041 DoD specifies:

> *"`ScheduledNotification` ORM model: `type`, `send_at`, `patient_id`, `encounter_id`, `channel`, `delivery_status`"*

The `scheduled_notification` table does **not** exist in the US-006 baseline schema (which covers: `patient`, `encounter`, `adt_event`, `medication`, `agent_task`, `document`, `bed`, `app_user`, `audit_log`, `chatbot_transcript`). This task adds it as a new Alembic migration and the corresponding SQLAlchemy 2.x ORM model.

Key design decisions:

| Decision | Rationale |
|---|---|
| `type` as `Enum(CHECK_IN_48H, MEDICATION_REMINDER)` | Matches US-041 Technical Notes; extensible for future notification types without schema changes |
| `channel` as `Enum(SMS, EMAIL)` | Aligned with US-064 Notification Service dispatch logic; avoids free-text values |
| `delivery_status` as `Enum(PENDING, SENT, OPTED_OUT, FAILED)` | Covers all AC scenarios: PENDING (created), SENT (dispatched), OPTED_OUT (AC Scenario 4), FAILED (retry exhausted) |
| `send_at` as `DateTime(timezone=True)` | Stored in UTC; `send_at = encounter.discharge_time + timedelta(hours=48)` per US-041 Technical Notes |
| `idempotency_key` as `VARCHAR(64)` with `unique=True` | Prevents duplicate dispatch if polling loop runs concurrently; format: `CHK48-{encounter_id}` |
| `patient_id` FK to `patient.id` | Enables opt-out check join without a second DB call in the polling loop |
| `encounter_id` FK to `encounter.id` | Links the check-in to the discharge encounter for HIPAA audit traceability |
| `channel` not nullable | Channel is resolved at creation time from `patient.preferred_contact` |

**Design references:**
- design.md §3.1 — Follow-up Care Agent: responsible for scheduling check-ins post-discharge
- design.md §6.1 DR-001 — all DDL managed via Alembic migrations; no manual schema changes
- design.md §6.1 DR-005 — soft deletes on clinical records (`deleted_at` timestamp)
- US-041 AC Scenario 1 — `type=CHECK_IN_48H`, `send_at = discharge_time + 48 hours`, `patient_phone` or `patient_email`
- US-041 AC Scenario 4 — `delivery_status=OPTED_OUT` when `patient.notification_opt_out=True`
- ADR-007 — PHI fields encrypted at ORM layer (patient phone/email stored in `patient` table, not duplicated here)

---

## Acceptance Criteria Addressed

| US-041 AC Scenario | Coverage |
|---|---|
| **Scenario 1** | `ScheduledNotification` record created with `type=CHECK_IN_48H`, `send_at = discharge_time + 48 hours` |
| **Scenario 4** | `delivery_status=OPTED_OUT` field stores the opt-out outcome without deleting the record |

---

## Implementation Steps

### 1. Create model file

```bash
touch backend/app/models/scheduled_notification.py
```

### 2. Implement `backend/app/models/scheduled_notification.py`

```python
"""SQLAlchemy ORM model for the `scheduled_notification` table.

Tracks every notification that the FollowUpCareAgent schedules for
future dispatch (e.g., 48-hour post-discharge check-in).

Delivery lifecycle:
    PENDING → SENT         (dispatched successfully by NotificationService)
           → OPTED_OUT     (patient.notification_opt_out=True at dispatch time)
           → FAILED        (all retries exhausted — manual care-team follow-up)

Idempotency key format: CHK48-{encounter_id}
    Ensures the 48-hour check-in is created exactly once per encounter even
    if the A03 Pub/Sub message is redelivered (ADR-001 at-least-once delivery).

Design refs:
    US-041 AC Scenarios 1, 4 — type, send_at, channel, delivery_status
    US-041 Technical Notes — send_at = encounter.discharge_time + timedelta(hours=48)
    design.md §6.1 DR-001 — all DDL via Alembic
    design.md §6.1 DR-005 — soft delete (deleted_at)
    ADR-007 — PHI not duplicated here; phone/email resolved at dispatch time
               from the encrypted patient record
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class NotificationType(str, Enum):
    CHECK_IN_48H = "CHECK_IN_48H"
    MEDICATION_REMINDER = "MEDICATION_REMINDER"


class NotificationChannel(str, Enum):
    SMS = "SMS"
    EMAIL = "EMAIL"


class DeliveryStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    OPTED_OUT = "OPTED_OUT"
    FAILED = "FAILED"


class ScheduledNotification(Base):
    """One row per future notification to be dispatched by the NotificationService."""

    __tablename__ = "scheduled_notification"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        comment="CHK48-{encounter_id} — prevents duplicate creation on Pub/Sub redelivery",
    )
    type: Mapped[NotificationType] = mapped_column(
        nullable=False,
        comment="Notification category; CHECK_IN_48H for US-041",
    )
    send_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        comment="UTC timestamp at which the NotificationService should dispatch; "
                "= encounter.discharge_time + 48 hours",
    )
    channel: Mapped[NotificationChannel] = mapped_column(
        nullable=False,
        comment="Dispatch channel resolved from patient.preferred_contact at creation time",
    )
    delivery_status: Mapped[DeliveryStatus] = mapped_column(
        nullable=False,
        default=DeliveryStatus.PENDING,
        index=True,
        comment="Updated by NotificationService after dispatch attempt",
    )

    # Foreign keys
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patient.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    encounter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("encounter.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Soft delete (DR-005)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    # Audit timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships (lazy="raise" to prevent N+1 in polling loop — use explicit joinedload)
    patient = relationship("Patient", lazy="raise")
    encounter = relationship("Encounter", lazy="raise")
```

### 3. Register model in `backend/app/models/__init__.py`

```python
# Add to existing imports:
from app.models.scheduled_notification import (  # noqa: F401
    DeliveryStatus,
    NotificationChannel,
    NotificationType,
    ScheduledNotification,
)
```

### 4. Create Alembic migration `backend/app/migrations/versions/0012_add_scheduled_notification.py`

```python
"""add scheduled_notification table

Revision ID: 0012
Revises: 0011  # appointment table from US-040/TASK-001
Create Date: 2026-07-17

Design refs:
    US-041 — 48-hour post-discharge check-in scheduling
    design.md §6.1 DR-001 — all DDL via Alembic
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enums — created before the table
    notification_type = postgresql.ENUM(
        "CHECK_IN_48H",
        "MEDICATION_REMINDER",
        name="notificationtype",
        create_type=True,
    )
    notification_channel = postgresql.ENUM(
        "SMS",
        "EMAIL",
        name="notificationchannel",
        create_type=True,
    )
    delivery_status = postgresql.ENUM(
        "PENDING",
        "SENT",
        "OPTED_OUT",
        "FAILED",
        name="deliverystatus",
        create_type=True,
    )
    notification_type.create(op.get_bind(), checkfirst=True)
    notification_channel.create(op.get_bind(), checkfirst=True)
    delivery_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "scheduled_notification",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("type", sa.Enum("CHECK_IN_48H", "MEDICATION_REMINDER",
                                  name="notificationtype"), nullable=False),
        sa.Column("send_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("channel", sa.Enum("SMS", "EMAIL",
                                     name="notificationchannel"), nullable=False),
        sa.Column("delivery_status", sa.Enum("PENDING", "SENT", "OPTED_OUT", "FAILED",
                                             name="deliverystatus"),
                  nullable=False, server_default="PENDING"),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("patient.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("encounter_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("encounter.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()"), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_scheduled_notification_idempotency_key"),
    )

    # Indexes for polling query: WHERE send_at <= NOW() AND delivery_status = 'PENDING'
    op.create_index(
        "ix_scheduled_notification_send_at",
        "scheduled_notification",
        ["send_at"],
    )
    op.create_index(
        "ix_scheduled_notification_delivery_status",
        "scheduled_notification",
        ["delivery_status"],
    )
    op.create_index(
        "ix_scheduled_notification_patient_id",
        "scheduled_notification",
        ["patient_id"],
    )
    op.create_index(
        "ix_scheduled_notification_encounter_id",
        "scheduled_notification",
        ["encounter_id"],
    )


def downgrade() -> None:
    op.drop_table("scheduled_notification")
    op.execute("DROP TYPE IF EXISTS deliverystatus")
    op.execute("DROP TYPE IF EXISTS notificationchannel")
    op.execute("DROP TYPE IF EXISTS notificationtype")
```

### 5. Validate migration syntax

```bash
cd backend
alembic check        # verify no pending schema drift
alembic upgrade head # apply to dev DB
alembic downgrade -1 # verify downgrade path
alembic upgrade head # re-apply
```

---

## Validation

- [ ] `alembic check` exits 0 (no un-migrated model changes)
- [ ] `alembic upgrade head` succeeds on dev Cloud SQL
- [ ] `alembic downgrade -1` + `alembic upgrade head` round-trips without error
- [ ] `SELECT column_name FROM information_schema.columns WHERE table_name='scheduled_notification'` returns all 11 columns
- [ ] `SELECT conname FROM pg_constraint WHERE conrelid='scheduled_notification'::regclass AND contype='u'` returns `uq_scheduled_notification_idempotency_key`
- [ ] Four indexes confirmed present in `pg_indexes`
- [ ] `mypy backend/app/models/scheduled_notification.py --strict` exits 0
- [ ] `ruff check backend/app/models/scheduled_notification.py` exits 0

---

## Files Produced

| File | Change |
|------|--------|
| `backend/app/models/scheduled_notification.py` | New — ORM model |
| `backend/app/models/__init__.py` | Modified — register new model + enums |
| `backend/app/migrations/versions/0012_add_scheduled_notification.py` | New — Alembic migration |
