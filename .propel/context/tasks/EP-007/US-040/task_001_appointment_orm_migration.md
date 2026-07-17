---
id: TASK-001
title: "appointment SQLAlchemy ORM Model + Alembic Migration"
user_story: US-040
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

# TASK-001: appointment SQLAlchemy ORM Model + Alembic Migration

> **Story:** US-040 | **Epic:** EP-007 | **Sprint:** 2 | **Layer:** Backend / Database | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-040 requires persisting follow-up appointment records for every discharged patient across all three risk tiers (HIGH, MEDIUM, LOW). The `appointment` table is **not** covered by US-006 (which defines 10 core tables: `patient`, `encounter`, `adt_event`, `medication`, `agent_task`, `document`, `bed`, `app_user`, `audit_log`, `chatbot_transcript`). This task adds the `appointment` table as a new Alembic migration and the corresponding SQLAlchemy ORM model.

US-040 Technical Notes specify:
- `appointment` status lifecycle: `SCHEDULED → CONFIRMED → COMPLETED | MISSED`
- Phase 1: internal SmartHandoff record only (no FHIR write-back)
- Care manager assignment from `app_user` with `role=CARE_MANAGER` scoped to the patient's unit

**Design references:**
- design.md §3.1 — Follow-up Care Agent responsibility: appointment scheduling
- design.md §6.1 DR-001 — all DDL managed via Alembic migrations
- design.md §6.1 DR-005 — soft deletes on clinical records
- US-040 AC Scenario 2 — `appointment_type=HIGH_RISK_FOLLOW_UP`, `target_date = discharge_date + 7 days`, `status=SCHEDULED`, `assigned_user_id`
- US-040 AC Scenario 3 — `appointment_type=STANDARD_FOLLOW_UP`, `target_date = discharge_date + 14 days`
- US-040 AC Scenario 4 — `appointment_type=ROUTINE_FOLLOW_UP`, `target_date = discharge_date + 30 days`

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 2 | `appointment` record persisted: `HIGH_RISK_FOLLOW_UP`, `target_date = discharge_date + 7 days`, `status=SCHEDULED`, `assigned_user_id` |
| Scenario 3 | `appointment` record: `STANDARD_FOLLOW_UP`, `target_date = discharge_date + 14 days` |
| Scenario 4 | `appointment` record: `ROUTINE_FOLLOW_UP`, `target_date = discharge_date + 30 days` |

---

## Implementation Steps

### 1. Create module file

```bash
touch backend/app/models/appointment.py
```

### 2. Implement `backend/app/models/appointment.py`

```python
"""SQLAlchemy ORM model for the `appointment` table.

Stores follow-up appointment records created by the FollowUpCareAgent
after risk score calculation at patient discharge (A03 event).

Appointment lifecycle:
    SCHEDULED → CONFIRMED → COMPLETED
                          → MISSED

Phase 1 constraint (C-03): internal SmartHandoff record only.
FHIR write-back deferred to Phase 2.

Design refs:
    US-040 AC Scenarios 2, 3, 4 — appointment_type, target_date, status, assigned_user_id
    US-040 Technical Notes — status lifecycle; care manager assignment
    design.md §6.1 DR-001 — all DDL via Alembic
    design.md §6.1 DR-005 — soft delete (deleted_at)
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum

from sqlalchemy import Date, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class AppointmentType(str, Enum):
    HIGH_RISK_FOLLOW_UP = "HIGH_RISK_FOLLOW_UP"
    STANDARD_FOLLOW_UP = "STANDARD_FOLLOW_UP"
    ROUTINE_FOLLOW_UP = "ROUTINE_FOLLOW_UP"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"


class Appointment(Base):
    """Follow-up appointment created by the FollowUpCareAgent post-discharge.

    One appointment record is created per encounter per discharge event.
    Additional appointments may be created if a re-admission occurs.

    Attributes:
        id:               UUID primary key.
        encounter_id:     FK → encounter.id. Cascade delete follows encounter.
        appointment_type: Tier-determined type (HIGH_RISK_FOLLOW_UP / STANDARD / ROUTINE).
        target_date:      Calendar date of the required follow-up appointment.
        status:           Current status in the lifecycle (SCHEDULED | CONFIRMED | COMPLETED | MISSED).
        assigned_user_id: FK → app_user.id — care manager assigned for HIGH-risk tier.
                          NULL for MEDIUM and LOW tiers (no mandatory care manager).
        created_at:       Server-side UTC timestamp at record creation.
        updated_at:       Server-side UTC timestamp updated on every change.
        deleted_at:       Soft-delete timestamp; NULL for active records (DR-005).
    """

    __tablename__ = "appointment"
    __table_args__ = (
        UniqueConstraint("encounter_id", "appointment_type", name="uq_appointment_encounter_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    encounter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("encounter.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    appointment_type: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        comment="AppointmentType enum value",
    )
    target_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="Calendar date by which follow-up must occur",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=AppointmentStatus.SCHEDULED.value,
        comment="AppointmentStatus lifecycle value",
    )
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Care manager assigned for HIGH-risk follow-up; NULL for MEDIUM/LOW",
    )
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
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="Soft-delete timestamp (DR-005); NULL = active",
    )

    # Relationships (lazy by default — do not eager-load in agent context)
    encounter: Mapped["Encounter"] = relationship(back_populates="appointments", lazy="select")
    assigned_user: Mapped["AppUser | None"] = relationship(lazy="select")
```

### 3. Update `backend/app/models/encounter.py` — add back-reference

Add the `appointments` relationship to the existing `Encounter` model so ORM navigation works:

```python
# In the Encounter class body, alongside existing relationships:
appointments: Mapped[list["Appointment"]] = relationship(
    "Appointment",
    back_populates="encounter",
    cascade="all, delete-orphan",
    lazy="select",
)
```

### 4. Create Alembic migration

```bash
# From the backend/ directory (where alembic.ini lives):
alembic revision --rev-id 0007 -m "add_appointment_table"
```

Implement `backend/alembic/versions/0007_add_appointment_table.py`:

```python
"""add_appointment_table

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-17

Adds the `appointment` table for follow-up care pathway records
created by the FollowUpCareAgent (US-040).

Columns:
    id               UUID PK
    encounter_id     UUID FK → encounter.id (CASCADE DELETE)
    appointment_type VARCHAR(40) NOT NULL — AppointmentType enum
    target_date      DATE NOT NULL
    status           VARCHAR(20) NOT NULL DEFAULT 'SCHEDULED'
    assigned_user_id UUID FK → app_user.id (SET NULL) — care manager
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
    deleted_at       TIMESTAMPTZ NULL

Indexes:
    idx_appointment_encounter_id   — appointment.encounter_id (FK lookups)
    idx_appointment_assigned_user  — appointment.assigned_user_id (care manager workload queries)
    uq_appointment_encounter_type  — UNIQUE (encounter_id, appointment_type)
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


def upgrade() -> None:
    op.create_table(
        "appointment",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "encounter_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("encounter.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("appointment_type", sa.String(40), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="SCHEDULED"),
        sa.Column(
            "assigned_user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index("idx_appointment_encounter_id", "appointment", ["encounter_id"])
    op.create_index("idx_appointment_assigned_user", "appointment", ["assigned_user_id"])
    op.create_unique_constraint(
        "uq_appointment_encounter_type",
        "appointment",
        ["encounter_id", "appointment_type"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_appointment_encounter_type", "appointment", type_="unique")
    op.drop_index("idx_appointment_assigned_user", table_name="appointment")
    op.drop_index("idx_appointment_encounter_id", table_name="appointment")
    op.drop_table("appointment")
```

### 5. Verify migration applies cleanly

```bash
# From backend/ directory using the test DB:
alembic upgrade head
alembic current   # Must show: 0007 (head)
alembic downgrade -1
alembic upgrade head
```

---

## Validation Checklist

- [ ] `Appointment` ORM model has all required columns (`encounter_id`, `appointment_type`, `target_date`, `status`, `assigned_user_id`)
- [ ] `AppointmentType` enum defines `HIGH_RISK_FOLLOW_UP`, `STANDARD_FOLLOW_UP`, `ROUTINE_FOLLOW_UP`
- [ ] `AppointmentStatus` enum defines `SCHEDULED`, `CONFIRMED`, `COMPLETED`, `MISSED`
- [ ] `UniqueConstraint` on `(encounter_id, appointment_type)` prevents duplicate appointments per discharge
- [ ] `encounter.appointments` back-reference added to `Encounter` ORM model
- [ ] Alembic migration `0007_add_appointment_table.py` applies with zero errors on clean DB
- [ ] `alembic downgrade -1` removes the `appointment` table cleanly
- [ ] Indexes on `encounter_id` and `assigned_user_id` created

---

## DoD Exit Criteria

- [ ] `backend/app/models/appointment.py` created with `Appointment`, `AppointmentType`, `AppointmentStatus`
- [ ] `backend/alembic/versions/0007_add_appointment_table.py` migration created and verified
- [ ] `Encounter.appointments` relationship added in `encounter.py`
- [ ] Alembic `upgrade head` succeeds on a clean test DB
- [ ] Alembic `downgrade -1` succeeds (reversible migration)
