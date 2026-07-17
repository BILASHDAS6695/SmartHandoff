---
id: TASK-001
title: "`care_escalation` SQLAlchemy ORM Model + Alembic Migration"
user_story: US-042
epic: EP-007
sprint: 2
layer: Backend / Database
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-006, US-021/TASK-001]
---

# TASK-001: `care_escalation` SQLAlchemy ORM Model + Alembic Migration

> **Story:** US-042 | **Epic:** EP-007 | **Sprint:** 2 | **Layer:** Backend / Database | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-042 requires a `CareEscalationMonitor` that creates and tracks escalation records when a patient's urgency flag is set. The `care_escalation` table is the system-of-record for:

- The initial `CARE_TEAM_ESCALATION` notification (sent to the on-call nurse via SMS within 60 seconds of flag detection)
- The re-escalation at 15 minutes if no acknowledgement is received (`SUPERVISOR_ESCALATION`)
- The nurse's acknowledgement via `PATCH /api/v1/care/escalations/{id}/acknowledge`

The table does **not** exist in the US-006 baseline schema (`patient`, `encounter`, `adt_event`, `medication`, `agent_task`, `document`, `bed`, `app_user`, `audit_log`, `chatbot_transcript`). This task adds it as a new Alembic migration and the corresponding SQLAlchemy 2.x ORM model.

**Key design decisions:**

| Decision | Rationale |
|---|---|
| `status` as `Enum(PENDING, ACKNOWLEDGED, ESCALATED_TO_SUPERVISOR)` | Maps to the three lifecycle states in US-042 AC Scenarios 2 and 3 |
| `idempotency_key VARCHAR(64)` with `unique=True` | Format: `ESC-{encounter_id}`; prevents duplicate escalations on Pub/Sub redelivery (ADR-001) |
| `notified_nurse_user_id` FK → `app_user.id` | Records which nurse received the initial SMS; required for audit trail (BR-023) |
| `acknowledged_by` FK → `app_user.id` nullable | Populated by `PATCH /api/v1/care/escalations/{id}/acknowledge`; null until acknowledged |
| `escalated_to_supervisor` Boolean default False | Toggled by APScheduler re-escalation job (TASK-003); explicitly queryable |
| No PHI in this table | Patient name/phone resolved at notification dispatch time from encrypted `patient` record (ADR-007) |
| `sent_at` timezone-aware | All timestamps stored in UTC; 15-minute SLA calculated as `NOW() - sent_at > INTERVAL '15 minutes'` |

**Design references:**
- design.md §3.1 — Follow-up Care Agent: risk scoring, appointment scheduling, reminder dispatch
- design.md §6.1 DR-001 — all DDL managed via Alembic migrations
- design.md §6.1 DR-003 — `audit_log` append-only; PHI access logged separately
- design.md §6.1 DR-005 — soft deletes via `deleted_at` timestamp
- design.md §8.3 — RBAC: nurse/physician/charge_nurse may acknowledge; patient = 403
- US-042 AC Scenario 2 — `status=ACKNOWLEDGED`, `acknowledged_at` recorded on nurse acknowledgement
- US-042 AC Scenario 3 — `escalated_to_supervisor=True` set after 15-minute SLA breach
- ADR-001 — Pub/Sub at-least-once; idempotency key required
- ADR-007 — PHI not duplicated in escalation record; resolved at dispatch time

---

## Acceptance Criteria Addressed

| US-042 AC Scenario | Coverage |
|---|---|
| **Scenario 2** | `care_escalation.status=ACKNOWLEDGED`, `acknowledged_at` column populated on nurse acknowledgement |
| **Scenario 3** | `care_escalation.escalated_to_supervisor=True`, `escalated_at` column populated after 15-minute SLA breach |

---

## Implementation Steps

### 1. Add `CareEscalationStatus` enum to `backend/app/models/enums.py`

```python
# Append to backend/app/models/enums.py alongside existing enums

import enum


class CareEscalationStatus(str, enum.Enum):
    """Lifecycle states for a care escalation triggered by patient urgency flag.

    PENDING               : Initial notification sent to on-call nurse; awaiting acknowledgement.
    ACKNOWLEDGED          : Nurse acknowledged via PATCH /api/v1/care/escalations/{id}/acknowledge.
    ESCALATED_TO_SUPERVISOR: 15-minute SLA breached; supervisor notified; original escalation tagged.
    """

    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATED_TO_SUPERVISOR = "ESCALATED_TO_SUPERVISOR"
```

### 2. Create `backend/app/models/care_escalation.py`

```python
"""SQLAlchemy ORM model for the care_escalation table.

Tracks the lifecycle of urgent patient escalations triggered by chatbot urgency flags.

Design refs:
    US-042 AC Scenarios 2, 3
    design.md §6.1 DR-001 (Alembic), DR-005 (soft deletes)
    ADR-001 (idempotency), ADR-007 (PHI containment)
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import CareEscalationStatus


class CareEscalation(Base):
    """System-of-record for urgent patient escalations.

    Lifecycle:
        PENDING → ACKNOWLEDGED         (nurse acknowledges within 15 min)
        PENDING → ESCALATED_TO_SUPERVISOR  (APScheduler triggers after 15-min SLA breach)

    PHI policy:
        No patient PHI stored in this table. Patient name and contact details are
        resolved at notification dispatch time from the encrypted `patient` record
        (ADR-007). Only `patient_id` (UUID FK) is stored here for RBAC join queries.
    """

    __tablename__ = "care_escalation"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_care_escalation_idempotency_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        doc="Surrogate primary key.",
    )
    encounter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("encounter.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        doc="FK to encounter that generated the urgency flag.",
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patient.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        doc="FK to patient; used for RBAC scope checks.",
    )
    notified_nurse_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="SET NULL"),
        nullable=True,
        doc="FK to the on-call nurse who received the initial SMS alert.",
    )
    status: Mapped[CareEscalationStatus] = mapped_column(
        SAEnum(CareEscalationStatus, name="care_escalation_status"),
        nullable=False,
        default=CareEscalationStatus.PENDING,
        doc="Current lifecycle state of the escalation.",
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        doc="UTC timestamp when the initial CARE_TEAM_ESCALATION notification was published.",
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="UTC timestamp when the nurse acknowledged (via PATCH endpoint). Null until acknowledged.",
    )
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="SET NULL"),
        nullable=True,
        doc="FK to the app_user who acknowledged. Null until acknowledged.",
    )
    escalated_to_supervisor: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="True after the 15-minute SLA is breached and a SUPERVISOR_ESCALATION is published.",
    )
    escalated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="UTC timestamp when the supervisor escalation was triggered. Null until escalated.",
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        doc="Idempotency key preventing duplicate escalations on Pub/Sub redelivery. Format: ESC-{encounter_id}.",
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
        doc="Soft-delete timestamp (DR-005). Active records have deleted_at=NULL.",
    )

    # Relationships
    encounter = relationship("Encounter", foreign_keys=[encounter_id], lazy="select")
    patient = relationship("Patient", foreign_keys=[patient_id], lazy="select")
    notified_nurse = relationship("AppUser", foreign_keys=[notified_nurse_user_id], lazy="select")
    acknowledging_user = relationship("AppUser", foreign_keys=[acknowledged_by], lazy="select")
```

### 3. Register the model in `backend/app/models/__init__.py`

```python
# Add to existing imports in backend/app/models/__init__.py
from app.models.care_escalation import CareEscalation  # noqa: F401
```

### 4. Generate Alembic migration

```bash
cd backend
alembic revision --autogenerate \
    -m "add_care_escalation_table_us042"
```

Review the generated migration to confirm:
- `care_escalation_status` PostgreSQL ENUM is created
- `uq_care_escalation_idempotency_key` unique constraint is present
- Foreign keys reference `encounter.id`, `patient.id`, `app_user.id`
- `deleted_at` column is nullable

### 5. Apply migration to dev environment

```bash
alembic upgrade head
```

Verify:

```sql
-- Confirm table exists with correct structure
\d care_escalation

-- Confirm unique constraint on idempotency_key
SELECT conname, contype FROM pg_constraint
WHERE conrelid = 'care_escalation'::regclass;

-- Confirm enum values
SELECT enumlabel FROM pg_enum
JOIN pg_type ON pg_enum.enumtypid = pg_type.oid
WHERE pg_type.typname = 'care_escalation_status';
```

Expected enum values: `PENDING`, `ACKNOWLEDGED`, `ESCALATED_TO_SUPERVISOR`

---

## Definition of Done Checklist

- [ ] `CareEscalationStatus` enum added to `backend/app/models/enums.py`
- [ ] `CareEscalation` ORM model created at `backend/app/models/care_escalation.py`
- [ ] Model registered in `backend/app/models/__init__.py`
- [ ] Alembic migration generated and reviewed (no raw SQL — autogenerate only)
- [ ] `alembic upgrade head` applied successfully to dev Cloud SQL
- [ ] Table structure verified via `\d care_escalation`
- [ ] Unique constraint on `idempotency_key` confirmed
- [ ] `deleted_at` soft-delete column present

---

## Notes

- **PHI**: No PHI is stored in `care_escalation`. Patient name and phone number are resolved from the encrypted `patient` record at notification dispatch time (ADR-007).
- **Audit**: Any PATCH to acknowledge must write an `audit_log` entry (enforced by the HIPAA audit middleware in TASK-004, not in this migration).
- **Do not add an index on `status`** at this stage — escalation re-query runs at most once per minute via APScheduler with a small result set (PENDING records < 15 min old). A full-table scan is acceptable until volume warrants it.
