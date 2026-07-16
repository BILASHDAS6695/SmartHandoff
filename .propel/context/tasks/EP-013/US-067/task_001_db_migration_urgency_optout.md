---
id: TASK-001
title: "Alembic Migration — Add `urgency_override` to `notification`, `delivery_status` Enum Extension, and `notification_opt_out` to `patient`"
user_story: US-067
epic: EP-013
sprint: 2
layer: Backend / Database
estimate: 1.5h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-064, US-006]
---

# TASK-001: Alembic Migration — Add `urgency_override` to `notification`, `delivery_status` Enum Extension, and `notification_opt_out` to `patient`

> **Story:** US-067 | **Epic:** EP-013 | **Sprint:** 2 | **Layer:** Backend / Database | **Est:** 1.5 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-067 DoD specifies:

> *"`notification` table `delivery_status` enum: `PENDING`, `SENT`, `DELIVERED`, `FAILED`, `OPTED_OUT`"*
> *"`urgency_override` boolean field on notification Pub/Sub message schema"*
> *"Opt-out persisted on `patient` table (US-006 ORM model) — not notification-table"*

US-064 (TASK-001) already created the `notification` table with `status` enum values `PENDING`, `SENT`, `DELIVERED`, `FAILED`. US-067 requires:

1. **Rename `status` → `delivery_status`** on the `notification` table and extend the enum with `OPTED_OUT` (or confirm US-064 already used `delivery_status` — align with the existing column name)
2. **Add `urgency_override BOOLEAN NOT NULL DEFAULT FALSE`** column to `notification` table
3. **Add `notification_opt_out BOOLEAN NOT NULL DEFAULT FALSE`** column to `patient` table — this is where the opt-out preference is stored per US-006 dependency and US-067 Technical Notes

Design decisions:

| Decision | Rationale |
|----------|-----------|
| `urgency_override` on `notification` table (not just Pub/Sub schema) | Persisted so audit log query (Scenario 1) can surface `urgency_override=True` in the response; Pub/Sub schema carries it as transport, DB persists it for evidence |
| `notification_opt_out` on `patient` table (not `notification` table) | US-067 Technical Notes explicitly state opt-out is a patient-level preference; notification table records outcomes per attempt |
| `DEFAULT FALSE` for both boolean columns | Safe default: new patients are opted in; new notifications are non-urgent unless explicitly set |
| PostgreSQL native `ENUM` type for `delivery_status` | Enum values must be altered with `ALTER TYPE ... ADD VALUE` in PostgreSQL — migration uses this pattern |
| `OPTED_OUT` added to enum, not as a status override | Keeps status as a single source of truth for the notification record outcome |

Design refs: US-064 TASK-001 (existing `notification` model), US-006 (`patient` ORM model), ADR-003, ADR-007, design.md §6.

---

## Acceptance Criteria Addressed

| US-067 AC | Requirement |
|---|---|
| **Scenario 1** | `delivery_status` column present in `notification` table for audit log query |
| **Scenario 2** | `delivery_status=OPTED_OUT` can be persisted when notification is suppressed |
| **Scenario 3** | `urgency_override=True` persisted on `notification` record |
| **Scenario 4** | `patient.notification_opt_out=True` can be persisted via portal PATCH |
| **DoD** | `notification` table `delivery_status` enum: `PENDING`, `SENT`, `DELIVERED`, `FAILED`, `OPTED_OUT` |

---

## Implementation Steps

### 1. Locate existing ORM models

The `notification` model is at `notification-service/app/models/notification.py` (created by US-064 TASK-001).
The `patient` model is at `backend/app/models/patient.py` (created by US-006).

### 2. Update `notification-service/app/models/notification.py`

Add `urgency_override` column and ensure `delivery_status` enum includes `OPTED_OUT`:

```python
import enum
from sqlalchemy import Boolean, Column, Enum
# ... existing imports ...

class DeliveryStatus(str, enum.Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    OPTED_OUT = "OPTED_OUT"


class Notification(Base):
    __tablename__ = "notification"

    # ... existing columns from US-064 ...

    delivery_status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus, name="deliverystatus", create_type=True),
        nullable=False,
        default=DeliveryStatus.PENDING,
        comment="Outcome of the notification delivery attempt",
    )
    urgency_override: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="True if set by sending agent to bypass patient opt-out (US-067)",
    )
```

> **Note:** If US-064 used the column name `status` instead of `delivery_status`, rename it here and add a corresponding `ALTER TABLE notification RENAME COLUMN status TO delivery_status` in the migration.

### 3. Update `backend/app/models/patient.py`

Add `notification_opt_out` boolean column:

```python
from sqlalchemy import Boolean, Column
# ... existing imports ...

class Patient(Base):
    __tablename__ = "patient"

    # ... existing columns from US-006 ...

    notification_opt_out: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Patient has opted out of non-urgent notifications (US-067)",
    )
```

### 4. Generate Alembic migration for `notification-service`

```bash
cd notification-service
alembic revision --autogenerate \
  -m "us067_add_urgency_override_optedout_status"
```

Edit the generated migration to ensure correct PostgreSQL enum handling:

```python
"""us067_add_urgency_override_optedout_status

Revision ID: <generated>
Revises: <us064_revision_id>
Create Date: 2026-07-16
"""
from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    # 1. Extend DeliveryStatus enum with OPTED_OUT (PostgreSQL ALTER TYPE)
    op.execute("ALTER TYPE deliverystatus ADD VALUE IF NOT EXISTS 'OPTED_OUT'")

    # 2. Add urgency_override column to notification table
    op.add_column(
        "notification",
        sa.Column(
            "urgency_override",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
            comment="True bypasses patient opt-out; set by sending agent only",
        ),
    )

    # 3. (If renaming) Rename status → delivery_status
    # op.alter_column("notification", "status", new_column_name="delivery_status")

def downgrade() -> None:
    op.drop_column("notification", "urgency_override")
    # Cannot remove enum value in PostgreSQL without recreating the type;
    # downgrade leaves OPTED_OUT in enum (safe — unused after downgrade)
```

### 5. Generate Alembic migration for `backend` (patient table)

```bash
cd backend
alembic revision --autogenerate \
  -m "us067_add_notification_opt_out_to_patient"
```

Edit the generated migration:

```python
"""us067_add_notification_opt_out_to_patient

Revision ID: <generated>
Revises: <us006_revision_id>
Create Date: 2026-07-16
"""
from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    op.add_column(
        "patient",
        sa.Column(
            "notification_opt_out",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
            comment="Patient opted out of non-urgent notifications (US-067)",
        ),
    )

def downgrade() -> None:
    op.drop_column("patient", "notification_opt_out")
```

### 6. Run and verify migrations locally

```bash
# notification-service migration
cd notification-service
alembic upgrade head

# backend migration
cd ../backend
alembic upgrade head
```

---

## Validation

```bash
# 1. Verify notification table schema
psql $DATABASE_URL -c "
  SELECT column_name, data_type, column_default
  FROM information_schema.columns
  WHERE table_name = 'notification'
    AND column_name IN ('delivery_status', 'urgency_override')
  ORDER BY column_name;
"
# Expected: delivery_status (USER-DEFINED), urgency_override (boolean, default false)

# 2. Verify patient table schema
psql $DATABASE_URL -c "
  SELECT column_name, data_type, column_default
  FROM information_schema.columns
  WHERE table_name = 'patient'
    AND column_name = 'notification_opt_out';
"
# Expected: notification_opt_out (boolean, default false)

# 3. Verify OPTED_OUT is in the enum
psql $DATABASE_URL -c "
  SELECT enumlabel FROM pg_enum
  JOIN pg_type ON pg_enum.enumtypid = pg_type.oid
  WHERE pg_type.typname = 'deliverystatus'
  ORDER BY enumsortorder;
"
# Expected: PENDING, SENT, DELIVERED, FAILED, OPTED_OUT

# 4. Verify alembic history shows both revisions
cd notification-service && alembic history | grep us067
cd ../backend && alembic history | grep us067
```

---

## Files Involved

| File | Action | Notes |
|------|--------|-------|
| `notification-service/app/models/notification.py` | Modify | Add `urgency_override` column; extend `DeliveryStatus` enum with `OPTED_OUT` |
| `notification-service/app/migrations/versions/<rev>_us067_add_urgency_override_optedout_status.py` | Create | Alembic migration for notification table |
| `backend/app/models/patient.py` | Modify | Add `notification_opt_out` boolean column |
| `backend/app/migrations/versions/<rev>_us067_add_notification_opt_out_to_patient.py` | Create | Alembic migration for patient table |

---

## Definition of Done (Task-Level)

- [ ] `DeliveryStatus` enum updated with `OPTED_OUT` in `notification.py`
- [ ] `urgency_override` column added to `Notification` ORM model and migration
- [ ] `notification_opt_out` column added to `Patient` ORM model and migration
- [ ] Both migrations run cleanly against local PostgreSQL (`alembic upgrade head`)
- [ ] Downgrade migrations tested (`alembic downgrade -1`)
- [ ] No regressions in existing US-064 tests
