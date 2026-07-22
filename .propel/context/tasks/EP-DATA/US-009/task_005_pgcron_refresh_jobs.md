---
id: TASK-005
title: "Alembic Migration `0004_pgcron_refresh_jobs` — Schedule Materialised View Refresh via pg_cron"
user_story: US-009
epic: EP-DATA
sprint: 1
layer: Backend / Database
estimate: 1h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [TASK-004, US-008/TASK-001]
---

# TASK-005: Alembic Migration `0004_pgcron_refresh_jobs` — Schedule Materialised View Refresh via pg_cron

> **Story:** US-009 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Backend / Database | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

TASK-004 created three materialised views. `mv_bed_board` is also refreshed on every `encounter` table mutation via a trigger — but the trigger-based refresh is eventually consistent. The pg_cron jobs provide a guaranteed minimum refresh frequency regardless of trigger execution:

| View | pg_cron Schedule | Cron Expression | Refresh Method |
|---|---|---|---|
| `mv_bed_board` | Every 60 seconds | `*/1 * * * *` | `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_bed_board` |
| `mv_risk_dashboard` | Every 5 minutes | `*/5 * * * *` | `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_risk_dashboard` |
| `mv_kpi_daily` | Nightly at 02:00 UTC | `0 2 * * *` | `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_kpi_daily` |

> **Note on pg_cron frequency limit:** pg_cron uses cron syntax, which has a minimum granularity of 1 minute. The `*/1 * * * *` schedule fires every minute — not every second. The event-driven trigger in TASK-004 (`trg_refresh_mv_bed_board`) handles sub-minute refresh for `mv_bed_board` during active discharge periods.

US-009 Technical Notes require `cloudsql.enable_pgcron` to be set on the Cloud SQL instance. This flag is managed in Terraform (`infra/terraform/modules/cloud_sql/main.tf`) and must be set before applying this migration.

---

## Acceptance Criteria Addressed

| US-009 AC | Requirement |
|---|---|
| **Scenario 4** | `mv_bed_board` refreshes within 60 seconds; `mv_risk_dashboard` within 5 minutes |
| **DoD** | pg_cron refresh jobs scheduled: `mv_bed_board` every 60s, `mv_risk_dashboard` every 5m, `mv_kpi_daily` nightly |

---

## Implementation Steps

### 1. Verify pg_cron Is Enabled on Cloud SQL

Before applying this migration, confirm the `cloudsql.enable_pgcron` database flag is set to `on` in the Terraform Cloud SQL module. This flag was provisioned in US-008/TASK-003 (if already done) or must be added now.

```hcl
# infra/terraform/modules/cloud_sql/main.tf
# Add or verify this database_flag block exists:
database_flags {
  name  = "cloudsql.enable_pgcron"
  value = "on"
}
```

Apply the Terraform change before running the Alembic migration.

### 2. Generate the Alembic Revision Stub

```bash
cd backend
alembic revision --message "pgcron_refresh_jobs"
# Note the generated revision ID (e.g., e9f3c0d82a14)
```

### 3. Implement `backend/alembic/versions/<rev4>_pgcron_refresh_jobs.py`

```python
"""pg_cron scheduled refresh jobs for materialised views.

Revision ID: <rev4>
Revises: <rev3>
Create Date: 2026-07-15

Hand-authored — schedules pg_cron jobs for materialised view refresh.
Must be applied AFTER the Cloud SQL instance has cloudsql.enable_pgcron=on.

Schedules:
  mv_bed_board         — every minute (sub-minute handled by encounter trigger)
  mv_risk_dashboard    — every 5 minutes
  mv_kpi_daily         — nightly at 02:00 UTC

References:
  DR-007: Refresh intervals for materialised views
  US-009 DoD: pg_cron jobs scheduled
  US-009 Technical Notes: cloudsql.enable_pgcron flag required
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "<rev4>"
down_revision: Union[str, None] = "<rev3>"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Enable pg_cron extension ──────────────────────────────────────────────
    # Idempotent — safe to run on re-deploy
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_cron;")

    # ── Schedule mv_bed_board refresh — every 1 minute ───────────────────────
    # CONCURRENTLY avoids locking reads during refresh.
    # The job is owned by the superuser role on Cloud SQL (pg_cron limitation);
    # the job itself runs as the database superuser, which can access all tables.
    op.execute("""
        SELECT cron.schedule(
            'refresh_mv_bed_board',
            '*/1 * * * *',
            $$REFRESH MATERIALIZED VIEW CONCURRENTLY mv_bed_board$$
        );
    """)

    # ── Schedule mv_risk_dashboard refresh — every 5 minutes ─────────────────
    op.execute("""
        SELECT cron.schedule(
            'refresh_mv_risk_dashboard',
            '*/5 * * * *',
            $$REFRESH MATERIALIZED VIEW CONCURRENTLY mv_risk_dashboard$$
        );
    """)

    # ── Schedule mv_kpi_daily refresh — nightly at 02:00 UTC ─────────────────
    op.execute("""
        SELECT cron.schedule(
            'refresh_mv_kpi_daily',
            '0 2 * * *',
            $$REFRESH MATERIALIZED VIEW CONCURRENTLY mv_kpi_daily$$
        );
    """)


def downgrade() -> None:
    # Unschedule jobs before dropping extension (prevents dangling job references)
    op.execute("SELECT cron.unschedule('refresh_mv_bed_board');")
    op.execute("SELECT cron.unschedule('refresh_mv_risk_dashboard');")
    op.execute("SELECT cron.unschedule('refresh_mv_kpi_daily');")

    # Do NOT drop the pg_cron extension — US-008/TASK-003 also uses it for the
    # audit log retention job. Only unschedule our specific jobs.
```

### 4. Verify pg_cron Jobs Are Active

After applying the migration, verify all three jobs are registered:

```sql
-- Check scheduled jobs
SELECT jobname, schedule, command, active
FROM cron.job
WHERE jobname IN (
    'refresh_mv_bed_board',
    'refresh_mv_risk_dashboard',
    'refresh_mv_kpi_daily'
);
```

Expected output:

| jobname | schedule | active |
|---|---|---|
| `refresh_mv_bed_board` | `*/1 * * * *` | `t` |
| `refresh_mv_risk_dashboard` | `*/5 * * * *` | `t` |
| `refresh_mv_kpi_daily` | `0 2 * * *` | `t` |

### 5. Manual Smoke Test — Verify Refresh Works

```sql
-- Force a manual refresh and time it
\timing on
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_bed_board;
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_risk_dashboard;
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_kpi_daily;

-- Verify row counts (should be non-zero if encounter data exists)
SELECT COUNT(*) FROM mv_bed_board;
SELECT COUNT(*) FROM mv_risk_dashboard;
SELECT COUNT(*) FROM mv_kpi_daily;
```

---

## File Checklist

| File | Action |
|---|---|
| `backend/alembic/versions/<rev4>_pgcron_refresh_jobs.py` | Create |
| `infra/terraform/modules/cloud_sql/main.tf` | Verify `cloudsql.enable_pgcron = on` flag is present |

---

## Dependencies

- **TASK-004** — All three materialised views (`mv_bed_board`, `mv_risk_dashboard`, `mv_kpi_daily`) must exist before scheduling refresh jobs
- **US-008/TASK-003** — pg_cron may already be enabled for the audit retention job; verify the extension is not created twice (the `CREATE EXTENSION IF NOT EXISTS` guard handles this)
