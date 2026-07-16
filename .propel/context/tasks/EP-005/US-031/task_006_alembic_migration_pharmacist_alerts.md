---
id: TASK-006
title: "Alembic Migration — pharmacist_alerts Table"
user_story: US-031
epic: EP-005
sprint: 2
layer: Backend / Database
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-031/TASK-005]
---

# TASK-006: Alembic Migration — pharmacist_alerts Table

> **Story:** US-031 | **Epic:** EP-005 | **Sprint:** 2 | **Layer:** Backend / Database | **Est:** 1 h  
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

The `PharmacistAlert` ORM model added in TASK-005 requires a corresponding Alembic migration to create the `pharmacist_alerts` table in Cloud SQL PostgreSQL. This migration must be idempotent and follow the project's Alembic conventions (autogenerate + manual review).

**Design references:**
- design.md §4.1 — Alembic for version-controlled schema migrations
- ADR-003 — Cloud SQL PostgreSQL 15; append-only audit log policy

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| AC Scenario 1 | `pharmacist_alerts` table present to persist alert records |

---

## Implementation Steps

### 1. Generate migration

```bash
cd backend
alembic revision --autogenerate -m "add_pharmacist_alerts_table"
```

### 2. Verify generated migration file

Ensure the generated migration in `backend/alembic/versions/` contains:

```python
"""add_pharmacist_alerts_table

Revision ID: <auto>
Revises: <previous_revision>
Create Date: 2026-07-16
"""
from __future__ import annotations

import uuid
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


def upgrade() -> None:
    op.create_table(
        "pharmacist_alerts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "encounter_id",
            UUID(as_uuid=True),
            sa.ForeignKey("encounters.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("alert_type", sa.String(64), nullable=False,
                  server_default="PHARMACIST_ALERT"),
        sa.Column(
            "severity",
            sa.Enum("HIGH", "MEDIUM", "LOW", name="alert_severity_enum"),
            nullable=False,
        ),
        sa.Column("drug_pair", sa.JSON(), nullable=True),
        sa.Column("interaction_description", sa.Text(), nullable=True),
        sa.Column("source", sa.String(32), nullable=False, server_default="RXNAV"),
        sa.Column(
            "interaction_check_status",
            sa.Enum("COMPLETE", "INCOMPLETE", name="check_status_enum"),
            nullable=False,
            server_default="COMPLETE",
        ),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_pharmacist_alerts_encounter_id",
        "pharmacist_alerts",
        ["encounter_id"],
    )
    op.create_index(
        "ix_pharmacist_alerts_severity",
        "pharmacist_alerts",
        ["severity"],
    )


def downgrade() -> None:
    op.drop_index("ix_pharmacist_alerts_severity", table_name="pharmacist_alerts")
    op.drop_index(
        "ix_pharmacist_alerts_encounter_id", table_name="pharmacist_alerts"
    )
    op.drop_table("pharmacist_alerts")
    op.execute("DROP TYPE IF EXISTS alert_severity_enum")
    op.execute("DROP TYPE IF EXISTS check_status_enum")
```

### 3. Run migration in dev environment

```bash
alembic upgrade head
```

### 4. Verify table schema

```sql
\d pharmacist_alerts
-- Confirm: id, encounter_id (FK + index), alert_type, severity (enum),
--          drug_pair (json), interaction_description (text),
--          source, interaction_check_status (enum), metadata (json), created_at
```

---

## File Checklist

| File | Action |
|------|--------|
| `backend/alembic/versions/<hash>_add_pharmacist_alerts_table.py` | Create via autogenerate |

---

## Validation

- [ ] `alembic upgrade head` applies cleanly with no errors
- [ ] `alembic downgrade -1` reverts cleanly
- [ ] `encounter_id` FK constraint references `encounters.id` with `ON DELETE CASCADE`
- [ ] `severity` and `interaction_check_status` stored as PostgreSQL enums
- [ ] Indexes on `encounter_id` and `severity` created

---

## Definition of Done

- [ ] Migration file committed to version control
- [ ] `alembic upgrade head` verified in dev environment
- [ ] Downgrade path tested
