"""audit_log Row Security Policy — append-only enforcement.

Revision ID: b7d1c4a82e59
Revises: a3f9e2c10b4d
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

revision: str = "b7d1c4a82e59"
down_revision: Union[str, None] = "a3f9e2c10b4d"
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

    # 4. Revoke DELETE and UPDATE from application user.
    # No RLS policy for DELETE/UPDATE → these operations are denied by default
    # when RLS is enabled and no matching policy exists.
    op.execute(f"REVOKE DELETE ON audit_log FROM {_APP_DB_USER}")
    op.execute(f"REVOKE UPDATE ON audit_log FROM {_APP_DB_USER}")

    # 5. Create a DB-level trigger to prevent UPDATE as defence-in-depth
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
