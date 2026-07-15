---
id: TASK-001
title: "Complete Alembic Migration `0002_audit_log_rls` — Restrictive RLS Policy and Database Roles"
user_story: US-008
epic: EP-DATA
sprint: 1
layer: Backend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: []
---

# TASK-001: Complete Alembic Migration `0002_audit_log_rls` — Restrictive RLS Policy and Database Roles

> **Story:** US-008 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Backend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

US-006 TASK-007 introduced a migration stub `0002_<rev>_audit_log_rls.py` as a placeholder. US-008 owns the **full implementation** of that migration:

1. Create three PostgreSQL roles with least-privilege grants (`app_write`, `audit_writer`, `compliance_reader`).
2. Enable Row Level Security on `audit_log` and apply a `RESTRICTIVE` policy that denies all operations to `app_write`.
3. Grant `INSERT` on `audit_log` exclusively to `audit_writer`, and `SELECT` to `compliance_reader`.

The Technical Notes in US-008 specify the exact DDL:

```sql
CREATE POLICY audit_immutable ON audit_log
  AS RESTRICTIVE FOR ALL
  TO app_write
  USING (false);
```

A `RESTRICTIVE` policy with `USING (false)` means the policy's condition (`false`) is AND-combined with every query for `app_write`, making every row invisible to that role for `SELECT`, `UPDATE`, and `DELETE`. INSERT is not governed by `USING` — it uses a `WITH CHECK` clause — but because `app_write` has no `INSERT` privilege on `audit_log` in the first place (only `audit_writer` does), writes are blocked at the privilege level.

This migration **must be reversible**. The `downgrade()` function must drop the policy, revoke privileges, and drop the roles in reverse order.

---

## Acceptance Criteria Addressed

| US-008 AC | Requirement |
|---|---|
| **Scenario 1** | `app_write` role receives permission denied on DELETE |
| **Scenario 2** | `app_write` role receives permission denied on UPDATE |
| **Scenario 3** | `audit_writer` role can INSERT into `audit_log` |
| **Scenario 4** | `compliance_reader` role can SELECT from `audit_log` |
| **DoD** | RLS policy active; Alembic migration creates roles and applies policy; reversible downgrade |

---

## Implementation Steps

### 1. Locate the Stub Migration File

The migration `backend/alembic/versions/<rev2>_audit_log_rls.py` was created as an empty shell in US-006/TASK-007. The `<rev2>` value was generated there. Open the file and replace its content entirely with the implementation below.

If the stub was not yet created, generate a new revision ID:

```bash
python -c "import uuid; print(uuid.uuid4().hex[:12])"
# e.g., c8e3f1a05b92
```

And name the file `backend/alembic/versions/c8e3f1a05b92_audit_log_rls.py`.

### 2. Implement the Full Migration

```python
"""Audit log row-level security policy and database roles.

Revision ID: <rev2>
Revises: <rev1>
Create Date: 2026-07-15

Hand-authored per US-008 Technical Notes (autogenerate disabled).
Enforces append-only audit_log via PostgreSQL RESTRICTIVE RLS policy.
Creates three roles: app_write, audit_writer, compliance_reader.

Security note: USING (false) on a RESTRICTIVE policy is AND-combined with
every row-level check for app_write, making SELECT/UPDATE/DELETE
impossible regardless of any future permissive policies.
INSERT is blocked at the privilege level (no GRANT INSERT TO app_write).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "<rev2>"
down_revision: Union[str, None] = "<rev1>"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Create application database roles ─────────────────────────────
    # Use DO $$ ... $$ to make role creation idempotent (safe on re-run).
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_write') THEN
                CREATE ROLE app_write NOLOGIN;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'audit_writer') THEN
                CREATE ROLE audit_writer NOLOGIN;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'compliance_reader') THEN
                CREATE ROLE compliance_reader NOLOGIN;
            END IF;
        END
        $$;
    """)

    # ── 2. Grant table-level privileges to app_write ──────────────────────
    # app_write can INSERT/UPDATE/DELETE on all domain tables EXCEPT
    # audit_log (blocked by RLS below) and SELECT everything.
    op.execute("""
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_write;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_write;
    """)

    # ── 3. Revoke INSERT/UPDATE/DELETE on audit_log from app_write ────────
    # The RLS policy below is the primary enforcement mechanism; this
    # explicit revoke is a defence-in-depth layer.
    op.execute("""
        REVOKE INSERT, UPDATE, DELETE ON audit_log FROM app_write;
    """)

    # ── 4. Grant INSERT-only on audit_log to audit_writer ─────────────────
    op.execute("""
        GRANT INSERT ON audit_log TO audit_writer;
    """)

    # ── 5. Grant SELECT-only on audit_log to compliance_reader ────────────
    op.execute("""
        GRANT SELECT ON audit_log TO compliance_reader;
    """)

    # ── 6. Enable Row Level Security on audit_log ─────────────────────────
    op.execute("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;")

    # ── 7. Apply RESTRICTIVE policy that blocks all operations for app_write
    # RESTRICTIVE + USING (false) → condition is AND-combined with every
    # row filter, making every row invisible for SELECT/UPDATE/DELETE.
    op.execute("""
        CREATE POLICY audit_immutable
            ON audit_log
            AS RESTRICTIVE
            FOR ALL
            TO app_write
            USING (false);
    """)


def downgrade() -> None:
    # ── Reverse in opposite order ─────────────────────────────────────────
    op.execute("DROP POLICY IF EXISTS audit_immutable ON audit_log;")
    op.execute("ALTER TABLE audit_log DISABLE ROW LEVEL SECURITY;")

    op.execute("REVOKE SELECT ON audit_log FROM compliance_reader;")
    op.execute("REVOKE INSERT ON audit_log FROM audit_writer;")

    op.execute("""
        REVOKE SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public FROM app_write;
        REVOKE USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public FROM app_write;
    """)

    op.execute("""
        DO $$
        BEGIN
            DROP ROLE IF EXISTS compliance_reader;
            DROP ROLE IF EXISTS audit_writer;
            DROP ROLE IF EXISTS app_write;
        END
        $$;
    """)
```

### 3. Verify Migration Applies and Reverses Cleanly

Run in the local test environment (or CI against testcontainers):

```bash
cd backend
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

All three commands must complete with zero errors.

### 4. Confirm RLS is Active

After `alembic upgrade head`, verify in `psql`:

```sql
-- Confirm policy exists
SELECT polname, polcmd, polroles::text, polqual
FROM pg_policies
WHERE tablename = 'audit_log';
-- Expected: audit_immutable | * | {app_write} | false

-- Confirm RLS is enabled
SELECT relname, relrowsecurity
FROM pg_class
WHERE relname = 'audit_log';
-- Expected: audit_log | t
```

---

## Files Affected

| File | Action |
|---|---|
| `backend/alembic/versions/<rev2>_audit_log_rls.py` | Replace stub with full implementation |

---

## Definition of Done

- [ ] Migration `upgrade()` creates roles `app_write`, `audit_writer`, `compliance_reader`
- [ ] Migration `upgrade()` enables RLS on `audit_log` and creates `audit_immutable` RESTRICTIVE policy for `app_write`
- [ ] Migration `downgrade()` reverses all changes cleanly
- [ ] `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` runs without errors in CI
- [ ] `pg_policies` query confirms policy exists after upgrade
