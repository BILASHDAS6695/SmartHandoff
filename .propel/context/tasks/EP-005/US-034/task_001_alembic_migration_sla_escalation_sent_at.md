---
id: TASK-001
title: "Add `sla_escalation_sent_at` Nullable Timestamp to `agent_task` via Alembic Migration"
user_story: US-034
epic: EP-005
sprint: 2
layer: Backend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-021/TASK-002, US-030]
---

# TASK-001: Add `sla_escalation_sent_at` Nullable Timestamp to `agent_task` via Alembic Migration

> **Story:** US-034 | **Epic:** EP-005 | **Sprint:** 2 | **Layer:** Backend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-034 Scenario 3 and DoD require an idempotency guard on the `AgentTask` record to prevent duplicate `CHARGE_PHARMACIST_ESCALATION` notifications:

> *"`sla_escalation_sent_at` nullable timestamp on `agent_task` (prevents duplicate escalation)"*

When the medication SLA monitor fires an escalation it sets `sla_escalation_sent_at = NOW()`. On subsequent monitor ticks, any task that already has `sla_escalation_sent_at IS NOT NULL` is skipped — avoiding repeated notifications for the same SLA breach.

The override endpoint (TASK-004) clears this field (`sla_escalation_sent_at = NULL`) when a charge pharmacist manually marks a reconciliation as `REVIEWED_MANUALLY`, allowing the task to be cleanly closed without further escalations.

**Design references:**
- US-034 Scenario 3 — `sla_escalation_sent_at` field ensures idempotency
- US-034 Scenario 4 — Override clears `sla_escalation_sent_at`
- US-021/TASK-002 — `sla_breached` and `sla_threshold_minutes` established the SLA schema pattern

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|---|---|
| Scenario 3 | `sla_escalation_sent_at` prevents duplicate escalation on repeated monitor ticks |
| Scenario 4 | Override endpoint clears `sla_escalation_sent_at` — TASK-004 depends on this column existing |
| DoD | `sla_escalation_sent_at` nullable timestamp on `agent_task` |

---

## Implementation Steps

### 1. Update `backend/app/models/agent_task.py`

Perform a **surgical addition** — add one column after the existing `sla_breached` column. Do not rewrite the file.

Locate the `sla_breached` column definition and add the new column immediately after it:

```python
    # SLA escalation idempotency — US-034
    sla_escalation_sent_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        default=None,
        comment=(
            "Timestamp when a CHARGE_PHARMACIST_ESCALATION notification was last sent "
            "for this task. NULL means no escalation has been sent. "
            "Set by MedRecSLAMonitor (US-034); cleared by override endpoint (US-034 AC4)."
        ),
    )
```

Add `datetime` to the `typing` import block at the top of the file if not already present.

### 2. Generate Alembic migration

From the project root (with the virtual environment active):

```bash
cd backend
alembic revision --autogenerate \
  -m "add_sla_escalation_sent_at_to_agent_task"
```

Verify the generated migration file under `backend/alembic/versions/` contains:

```python
def upgrade() -> None:
    op.add_column(
        "agent_task",
        sa.Column(
            "sla_escalation_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment=(
                "Timestamp when a CHARGE_PHARMACIST_ESCALATION notification was last sent "
                "for this task. NULL means no escalation has been sent."
            ),
        ),
    )
    # Partial index for medication SLA monitor polling query (US-034 TASK-002).
    op.create_index(
        "ix_agent_task_medrec_sla_pending",
        "agent_task",
        ["agent_type", "status", "encounter_id"],
        postgresql_where=(
            "agent_type = 'MEDICATION_RECONCILIATION' "
            "AND status IN ('IN_PROGRESS', 'PENDING') "
            "AND sla_escalation_sent_at IS NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_task_medrec_sla_pending",
        table_name="agent_task",
    )
    op.drop_column("agent_task", "sla_escalation_sent_at")
```

### 3. Apply the migration (local dev)

```bash
alembic upgrade head
```

### 4. Verify schema

Connect to the local dev database and confirm:

```sql
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'agent_task'
  AND column_name = 'sla_escalation_sent_at';
-- Expected: sla_escalation_sent_at | timestamp with time zone | YES

\d agent_task
-- ix_agent_task_medrec_sla_pending partial index must appear
```

---

## Files Changed

| File | Change |
|---|---|
| `backend/app/models/agent_task.py` | Add `sla_escalation_sent_at` column (surgical addition after `sla_breached`) |
| `backend/alembic/versions/<hash>_add_sla_escalation_sent_at_to_agent_task.py` | New Alembic migration |

---

## Definition of Done Checklist

- [ ] `sla_escalation_sent_at` column added to `AgentTask` ORM model
- [ ] Alembic migration generated and reviewed — contains `upgrade()` and `downgrade()`
- [ ] Partial index `ix_agent_task_medrec_sla_pending` created for monitor poll query
- [ ] Migration applied to local dev DB without errors
- [ ] Schema verified with `\d agent_task` — column present and nullable
- [ ] No other columns modified — surgical change only
