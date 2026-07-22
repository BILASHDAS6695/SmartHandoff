"""Audit log row-level security policy and database roles.

Revision ID: b7d1c4a82e59
Revises: a3f9e2c10b4d
Create Date: 2026-07-15

Hand-authored per US-008/TASK-001 (autogenerate disabled).
Enforces append-only audit_log via PostgreSQL RESTRICTIVE RLS policy.
Creates three least-privilege roles: app_write, audit_writer, compliance_reader.

Security note (DR-003, BR-022):
  RESTRICTIVE + USING(false) is AND-combined with every row-level check for
  app_write, making SELECT / UPDATE / DELETE impossible regardless of any
  future permissive policies.
  INSERT is blocked at the privilege level (REVOKE INSERT … FROM app_write),
  providing defence-in-depth on top of the RLS policy.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "b7d1c4a82e59"
down_revision: Union[str, None] = "a3f9e2c10b4d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Create application database roles (idempotent) ─────────────────
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

    # ── 2. Grant broad table privileges to app_write ──────────────────────
    # app_write is the role used by the main application service. It gets
    # full DML on all domain tables; audit_log is restricted below.
    op.execute("""
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_write;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_write;
    """)

    # ── 3. Revoke all mutating privileges on audit_log from app_write ─────
    # Defence-in-depth layer complementing the RLS policy below.
    # INSERT is also revoked because only audit_writer should write audit rows.
    op.execute("""
        REVOKE INSERT, UPDATE, DELETE ON audit_log FROM app_write;
    """)

    # ── 4. Grant INSERT-only on audit_log to audit_writer ─────────────────
    # audit_writer is used exclusively by HIPAAAuditMiddleware session pool.
    op.execute("""
        GRANT INSERT ON audit_log TO audit_writer;
    """)

    # ── 5. Grant SELECT-only on audit_log to compliance_reader ────────────
    # compliance_reader is used for HIPAA compliance reporting queries.
    op.execute("""
        GRANT SELECT ON audit_log TO compliance_reader;
    """)

    # ── 6. Enable Row Level Security on audit_log ─────────────────────────
    op.execute("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE audit_log FORCE ROW LEVEL SECURITY;")

    # ── 7. Apply RESTRICTIVE policy blocking all operations for app_write ─
    # RESTRICTIVE + USING(false): the condition evaluates to false for every
    # row, so SELECT / UPDATE / DELETE find zero rows for app_write.
    # Combined with the explicit REVOKE above, tampering requires compromising
    # both the privilege layer and the RLS enforcement layer simultaneously.
    op.execute("""
        CREATE POLICY audit_immutable
            ON audit_log
            AS RESTRICTIVE
            FOR ALL
            TO app_write
            USING (false);
    """)


def downgrade() -> None:
    # ── Reverse in opposite order of upgrade ─────────────────────────────
    op.execute("DROP POLICY IF EXISTS audit_immutable ON audit_log;")
    # Undo FORCE before DISABLE (reverse order of upgrade steps 6–7)
    op.execute("ALTER TABLE audit_log NO FORCE ROW LEVEL SECURITY;")
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
