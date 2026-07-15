---
id: TASK-007
title: "Hand-Author Alembic Migrations — `0001_initial_schema` and `0002_audit_log_rls`"
user_story: US-006
epic: EP-DATA
sprint: 1
layer: Backend
estimate: 4h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [TASK-001, TASK-002, TASK-003, TASK-004, TASK-005]
---

# TASK-007: Hand-Author Alembic Migrations — `0001_initial_schema` and `0002_audit_log_rls`

> **Story:** US-006 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Backend | **Est:** 4 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

US-006 mandates that all migrations be **hand-authored** (`autogenerate = False` per the Technical Notes). This is required because:

1. The `EncryptedString` TypeDecorators render non-standard column types that Alembic's autogenerate cannot correctly infer or reverse.
2. The PostgreSQL Row Security Policy (RLS) on `audit_log` is DDL that Alembic autogenerate does not support.
3. Hand-authored migrations are more explicit, reviewable, and safer for HIPAA-scoped schema changes.

This task produces two migration files:

- **`0001_<rev>_initial_schema.py`** — creates all 10 tables, all indexes, all unique constraints, and soft-delete columns
- **`0002_<rev>_audit_log_rls.py`** — adds PostgreSQL Row Security Policy to `audit_log` table (DR-003 append-only enforcement) and revokes DELETE/UPDATE from the application user

Both migrations must implement complete, reversible `downgrade()` functions (DoD requirement).

---

## Acceptance Criteria Addressed

| US-006 AC | Requirement |
|---|---|
| **Scenario 1** | `alembic upgrade head` on empty DB creates all 10 tables with zero errors |
| **DoD** | Alembic migration files created for all 10 tables |
| **DoD** | `alembic downgrade -1` tested and reversible for each migration |
| **DoD** | `source_message_id` unique constraint on `adt_event` (DR-022) |
| **DoD** | Soft-delete columns on `patient` and `encounter` (DR-005) |
| **DoD** | Indexes on `encounter.status`, `encounter.risk_tier`, `patient.mrn_encrypted` (DR-004) |

---

## Implementation Steps

### 1. Generate Revision IDs

Generate two Alembic revision IDs for use as file prefixes. In the `backend/` directory:

```bash
python -c "import uuid; print(uuid.uuid4().hex[:12])"
# Example output: a3f9e2c10b4d  → used as <rev1>
python -c "import uuid; print(uuid.uuid4().hex[:12])"
# Example output: b7d1c4a82e59  → used as <rev2>
```

Name the files:
- `backend/alembic/versions/<rev1>_initial_schema.py`
- `backend/alembic/versions/<rev2>_audit_log_rls.py`

### 2. Author `<rev1>_initial_schema.py` — All 10 Tables

The migration creates tables in dependency order:
1. Independent tables first: `app_user`, `patient`, `bed`  
2. Tables with FKs to the above: `encounter`  
3. Tables with FKs to `encounter`: `adt_event`, `medication`, `agent_task`, `document`, `audit_log`, `chatbot_transcript`

```python
"""Initial schema — all 10 domain tables.

Revision ID: <rev1>
Revises: None
Create Date: 2026-07-15

Hand-authored per US-006 Technical Notes (autogenerate disabled).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "<rev1>"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── app_user ──────────────────────────────────────────────────────────
    op.create_table(
        "app_user",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("idp_subject", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("unit", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idp_subject", name="uq_app_user_idp_subject"),
        sa.UniqueConstraint("email", name="uq_app_user_email"),
    )
    op.create_index("ix_app_user_idp_subject", "app_user", ["idp_subject"], unique=True)
    op.create_index("ix_app_user_email", "app_user", ["email"], unique=True)
    op.create_index("ix_app_user_role_active", "app_user", ["role", "is_active"])

    # ── patient ───────────────────────────────────────────────────────────
    # PHI columns stored as TEXT (AES-256-GCM ciphertext via US-007 TypeDecorator)
    op.create_table(
        "patient",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("first_name", sa.Text(), nullable=False,
                  comment="AES-256-GCM encrypted (US-007)"),
        sa.Column("last_name", sa.Text(), nullable=False,
                  comment="AES-256-GCM encrypted (US-007)"),
        sa.Column("date_of_birth", sa.Text(), nullable=False,
                  comment="ISO-8601 date, AES-256-GCM encrypted (US-007)"),
        sa.Column("phone", sa.Text(), nullable=True,
                  comment="AES-256-GCM encrypted (US-007)"),
        sa.Column("email", sa.Text(), nullable=True,
                  comment="AES-256-GCM encrypted (US-007)"),
        sa.Column(
            "mrn_encrypted",
            sa.String(128),
            nullable=False,
            comment="Deterministically encrypted MRN for unique indexing (DR-020)",
        ),
        sa.Column(
            "language_code", sa.String(8), nullable=False, server_default="en"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Soft delete (DR-005)
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mrn_encrypted", name="uq_patient_mrn_encrypted"),
    )
    op.create_index(
        "ix_patient_mrn_encrypted", "patient", ["mrn_encrypted"], unique=True
    )
    op.create_index("ix_patient_deleted_at", "patient", ["deleted_at"])

    # ── encounter ─────────────────────────────────────────────────────────
    op.create_table(
        "encounter",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "patient_id",
            sa.UUID(),
            sa.ForeignKey("patient.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="REGISTERED",
            comment="Encounter lifecycle status; transitions enforced by ORM event listener",
        ),
        sa.Column("admit_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discharge_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("admitting_diagnosis", sa.Text(), nullable=True),
        sa.Column(
            "attending_physician_id",
            sa.UUID(),
            sa.ForeignKey("app_user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("unit", sa.String(64), nullable=True),
        sa.Column(
            "risk_tier",
            sa.String(16),
            nullable=False,
            server_default="UNKNOWN",
        ),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("visit_number", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Soft delete (DR-005)
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # DR-004: Composite indexes for dashboard query performance
    op.create_index(
        "ix_encounter_patient_admit", "encounter", ["patient_id", "admit_date"]
    )
    op.create_index("ix_encounter_unit_status", "encounter", ["unit", "status"])
    op.create_index(
        "ix_encounter_risk_tier_status", "encounter", ["risk_tier", "status"]
    )
    op.create_index("ix_encounter_deleted_at", "encounter", ["deleted_at"])

    # ── bed ───────────────────────────────────────────────────────────────
    op.create_table(
        "bed",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("bed_number", sa.String(32), nullable=False),
        sa.Column("unit", sa.String(64), nullable=False),
        sa.Column("ward", sa.String(64), nullable=True),
        sa.Column(
            "status", sa.String(32), nullable=False, server_default="available"
        ),
        sa.Column(
            "current_encounter_id",
            sa.UUID(),
            sa.ForeignKey("encounter.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "predicted_discharge_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("unit", "bed_number", name="uq_bed_unit_number"),
    )
    op.create_index("ix_bed_unit_status", "bed", ["unit", "status"])

    # ── adt_event ─────────────────────────────────────────────────────────
    op.create_table(
        "adt_event",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "encounter_id",
            sa.UUID(),
            sa.ForeignKey("encounter.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_message_id",
            sa.String(128),
            nullable=False,
            comment="HL7 MSH-10 message control ID — unique constraint (DR-022)",
        ),
        sa.Column("event_type", sa.String(8), nullable=False),
        sa.Column("event_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sending_facility", sa.String(64), nullable=True),
        sa.Column("raw_message_path", sa.Text(), nullable=True),
        sa.Column(
            "processing_status",
            sa.String(32),
            nullable=False,
            server_default="received",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        # DR-022: Unique constraint on HL7 message ID for idempotency
        sa.UniqueConstraint("source_message_id", name="uq_adt_event_source_message_id"),
    )
    op.create_index(
        "ix_adt_event_source_message_id",
        "adt_event",
        ["source_message_id"],
        unique=True,
    )
    op.create_index("ix_adt_event_encounter_id", "adt_event", ["encounter_id"])
    op.create_index(
        "ix_adt_event_type_timestamp", "adt_event", ["event_type", "event_timestamp"]
    )

    # ── medication ────────────────────────────────────────────────────────
    op.create_table(
        "medication",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "encounter_id",
            sa.UUID(),
            sa.ForeignKey("encounter.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("drug_name", sa.String(255), nullable=False),
        sa.Column("rxcui", sa.String(32), nullable=True),
        sa.Column("dose", sa.String(64), nullable=True),
        sa.Column("route", sa.String(64), nullable=True),
        sa.Column("frequency", sa.String(64), nullable=True),
        sa.Column(
            "source", sa.String(32), nullable=False, server_default="admission"
        ),
        sa.Column("interaction_severity", sa.String(16), nullable=True),
        sa.Column(
            "reconciliation_status",
            sa.String(32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_medication_encounter_id", "medication", ["encounter_id"])
    op.create_index("ix_medication_rxcui", "medication", ["rxcui"])
    op.create_index(
        "ix_medication_severity", "medication", ["interaction_severity"]
    )

    # ── agent_task ────────────────────────────────────────────────────────
    op.create_table(
        "agent_task",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "encounter_id",
            sa.UUID(),
            sa.ForeignKey("encounter.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent_type", sa.String(64), nullable=False),
        sa.Column(
            "status", sa.String(32), nullable=False, server_default="queued"
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pubsub_message_id", sa.String(128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "retry_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "encounter_id",
            "agent_type",
            "pubsub_message_id",
            name="uq_agent_task_idempotency",
        ),
    )
    op.create_index(
        "ix_agent_task_encounter_agent",
        "agent_task",
        ["encounter_id", "agent_type"],
    )
    op.create_index("ix_agent_task_status", "agent_task", ["status"])

    # ── document ──────────────────────────────────────────────────────────
    op.create_table(
        "document",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "encounter_id",
            sa.UUID(),
            sa.ForeignKey("encounter.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("document_type", sa.String(64), nullable=False),
        sa.Column(
            "content",
            sa.Text(),
            nullable=False,
            comment="AES-256-GCM encrypted document body (US-007, DR-013)",
        ),
        sa.Column(
            "language_code", sa.String(8), nullable=False, server_default="en"
        ),
        sa.Column(
            "status", sa.String(32), nullable=False, server_default="draft"
        ),
        sa.Column(
            "generation_type",
            sa.String(16),
            nullable=False,
            server_default="LLM",
        ),
        sa.Column(
            "approved_by_id",
            sa.UUID(),
            sa.ForeignKey("app_user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_document_encounter_type",
        "document",
        ["encounter_id", "document_type"],
    )
    op.create_index("ix_document_status", "document", ["status"])

    # ── audit_log ─────────────────────────────────────────────────────────
    # Append-only table. Row Security Policy added in migration 0002.
    op.create_table(
        "audit_log",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("user_role", sa.String(32), nullable=True),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(128), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column(
            "outcome", sa.String(16), nullable=False, server_default="success"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_log_user_id", "audit_log", ["user_id"])
    op.create_index(
        "ix_audit_log_resource",
        "audit_log",
        ["resource_type", "resource_id"],
    )
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])

    # ── chatbot_transcript ────────────────────────────────────────────────
    op.create_table(
        "chatbot_transcript",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "encounter_id",
            sa.UUID(),
            sa.ForeignKey("encounter.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column(
            "message_content",
            sa.Text(),
            nullable=False,
            comment="AES-256-GCM encrypted chatbot message (DR-016)",
        ),
        sa.Column(
            "is_urgent",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chatbot_encounter_id", "chatbot_transcript", ["encounter_id"]
    )
    op.create_index(
        "ix_chatbot_urgent",
        "chatbot_transcript",
        ["encounter_id", "is_urgent"],
    )


def downgrade() -> None:
    # Drop in reverse dependency order to avoid FK violations
    op.drop_table("chatbot_transcript")
    op.drop_table("audit_log")
    op.drop_table("document")
    op.drop_table("agent_task")
    op.drop_table("medication")
    op.drop_table("adt_event")
    op.drop_table("bed")
    op.drop_table("encounter")
    op.drop_table("patient")
    op.drop_table("app_user")
```

### 3. Author `<rev2>_audit_log_rls.py` — `audit_log` Row Security Policy

```python
"""audit_log Row Security Policy — append-only enforcement.

Revision ID: <rev2>
Revises: <rev1>
Create Date: 2026-07-15

DR-003: The audit_log table must be append-only.
- PostgreSQL RLS DENY DELETE/UPDATE on audit_log.
- Application DB user (`smarthandoff_app`) has INSERT/SELECT only.
- Superuser / DBA accounts retain full access (compliance queries).

Hand-authored per US-006 Technical Notes (autogenerate disabled).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "<rev2>"
down_revision: Union[str, None] = "<rev1>"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Application DB user that Cloud Run services connect as.
# This matches the user created by the cloud_sql Terraform module.
_APP_DB_USER = "smarthandoff_app"


def upgrade() -> None:
    # 1. Enable Row Security on audit_log
    op.execute("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_log FORCE ROW LEVEL SECURITY")

    # 2. Allow INSERT (audit writer) — application inserts new audit records
    op.execute(
        f"""
        CREATE POLICY audit_log_insert_policy ON audit_log
        FOR INSERT
        TO {_APP_DB_USER}
        WITH CHECK (true)
        """
    )

    # 3. Allow SELECT (audit reader) — compliance queries and middleware reads
    op.execute(
        f"""
        CREATE POLICY audit_log_select_policy ON audit_log
        FOR SELECT
        TO {_APP_DB_USER}
        USING (true)
        """
    )

    # 4. Revoke DELETE and UPDATE from application user
    # No RLS policy for DELETE/UPDATE → these operations are denied by default
    # when RLS is enabled and no matching policy exists.
    op.execute(f"REVOKE DELETE ON audit_log FROM {_APP_DB_USER}")
    op.execute(f"REVOKE UPDATE ON audit_log FROM {_APP_DB_USER}")

    # 5. Create a DB-level trigger to prevent UPDATE via trigger as defence-in-depth
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_audit_log_no_update()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION
                'audit_log is append-only: UPDATE operations are not permitted (DR-003)';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER tg_audit_log_no_update
        BEFORE UPDATE ON audit_log
        FOR EACH ROW
        EXECUTE FUNCTION fn_audit_log_no_update()
        """
    )


def downgrade() -> None:
    # Remove trigger first
    op.execute("DROP TRIGGER IF EXISTS tg_audit_log_no_update ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS fn_audit_log_no_update()")

    # Restore privileges
    op.execute(f"GRANT DELETE ON audit_log TO {_APP_DB_USER}")
    op.execute(f"GRANT UPDATE ON audit_log TO {_APP_DB_USER}")

    # Remove RLS policies
    op.execute("DROP POLICY IF EXISTS audit_log_insert_policy ON audit_log")
    op.execute("DROP POLICY IF EXISTS audit_log_select_policy ON audit_log")
    op.execute("ALTER TABLE audit_log DISABLE ROW LEVEL SECURITY")
```

### 4. Test `downgrade -1` for Both Migrations

After creating both migration files, run and verify reversibility:

```bash
cd backend

# Apply both migrations
alembic upgrade head

# Verify all 10 tables exist
python -c "
import asyncio
from app.db.session import AsyncSessionLocal
from sqlalchemy import text

async def check():
    async with AsyncSessionLocal() as s:
        result = await s.execute(
            text(\"SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename\")
        )
        print([r[0] for r in result.fetchall()])

asyncio.run(check())
"
# Expected: ['adt_event', 'agent_task', 'app_user', 'audit_log', 'bed',
#            'chatbot_transcript', 'document', 'encounter', 'medication', 'patient']

# Downgrade audit_log_rls migration
alembic downgrade -1
# Verify: RLS disabled, trigger dropped, privileges restored

# Downgrade initial schema migration
alembic downgrade -1
# Verify: all 10 tables dropped, alembic_version table has no rows
```

---

## Definition of Done

- [ ] `backend/alembic/versions/<rev1>_initial_schema.py` creates all 10 tables with correct columns, FKs, and constraints
- [ ] `<rev1>` migration includes `UniqueConstraint("source_message_id", ...)` on `adt_event` (DR-022)
- [ ] `<rev1>` migration includes `deleted_at` column on `patient` and `encounter` (DR-005)
- [ ] `<rev1>` migration creates all DR-004 composite indexes: `(patient_id, admit_date)`, `(unit, status)`, `(risk_tier, status)`, `ix_patient_mrn_encrypted`
- [ ] `backend/alembic/versions/<rev2>_audit_log_rls.py` enables RLS and adds INSERT-only policy for `smarthandoff_app`
- [ ] `<rev2>` migration creates UPDATE-blocking trigger `fn_audit_log_no_update` as defence-in-depth
- [ ] `alembic upgrade head` runs on a fresh empty database with zero errors
- [ ] `alembic downgrade -1` tested for `<rev2>` (RLS and trigger removed cleanly)
- [ ] `alembic downgrade -1` tested for `<rev1>` (all 10 tables dropped in reverse FK order)
- [ ] No hardcoded DB credentials or connection strings in migration files

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 | Preceding task | Alembic project structure and `env.py` must exist |
| TASK-002–TASK-005 | Preceding tasks | All ORM models must be defined (migration DDL must match model definitions) |

---

## Files Modified

| File | Action |
|---|---|
| `backend/alembic/versions/<rev1>_initial_schema.py` | Create |
| `backend/alembic/versions/<rev2>_audit_log_rls.py` | Create |
