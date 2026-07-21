"""Integration tests — audit_log Row Level Security immutability.

SC-1: app_write role cannot DELETE from audit_log (RESTRICTIVE RLS blocks it)
SC-2: app_write role cannot UPDATE audit_log (RESTRICTIVE RLS blocks it)
SC-3: audit_writer role INSERT succeeds and all fields are persisted
SC-4: compliance_reader role can SELECT audit_log rows
SC-5: compliance_reader role cannot INSERT into audit_log

These tests use testcontainers (postgres:15-alpine).  The alembic upgrade
stops at revision c2e5f8a91d3b (widen_mrn) — the pg_cron migration
(d4b7e2f91c30) and endpoint migration (e1f8d3c92a47) are intentionally
excluded because pg_cron is not available in the plain postgres:15 Docker image.

Roles created by the b7d1c4a82e59 migration are base roles (NOLOGIN).  The
setup_roles fixture grants LOGIN and sets a password so the test suite can
open per-role connections.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import uuid

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer

_BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent.parent


# ── Session-scoped container + schema ────────────────────────────────────────

@pytest.fixture(scope="session")
def pg_container_rls():
    """Dedicated PostgreSQL 15 container for RLS tests (session-scoped)."""
    with PostgresContainer("postgres:15-alpine") as postgres:
        yield postgres


@pytest.fixture(scope="session")
def sync_url_rls(pg_container_rls: PostgresContainer) -> str:
    """psycopg2-compatible URL (used for Alembic + role setup)."""
    return pg_container_rls.get_connection_url()


@pytest.fixture(scope="session")
def async_url_rls(pg_container_rls: PostgresContainer) -> str:
    """asyncpg-compatible URL for the superuser (test orchestration)."""
    url = pg_container_rls.get_connection_url()
    return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")


@pytest.fixture(scope="session")
def apply_rls_migrations(sync_url_rls: str) -> None:
    """Run Alembic migrations up to c2e5f8a91d3b (widen_mrn migration).

    This revision is the last one before the pgcron migration (d4b7e2f91c30).
    It includes b7d1c4a82e59 (RLS policy) and c2e5f8a91d3b (widen mrn_encrypted),
    both of which are safe in a plain postgres:15 testcontainers image.
    The pg_cron migration (d4b7e2f91c30) and endpoint migration (e1f8d3c92a47)
    are excluded from this test run.
    """
    os.environ["DATABASE_URL"] = sync_url_rls.replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://"
    )
    alembic_cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    # c2e5f8a91d3b is the widen_mrn migration — the last safe revision for
    # testcontainers (no pg_cron required)
    command.upgrade(alembic_cfg, "c2e5f8a91d3b")


@pytest.fixture(scope="session")
def superuser_engine(async_url_rls: str, apply_rls_migrations):
    """Superuser async engine for role management and test orchestration."""
    engine = create_async_engine(async_url_rls, poolclass=NullPool)
    yield engine
    asyncio.run(engine.dispose())


@pytest.fixture(scope="session")
def setup_roles(superuser_engine, pg_container_rls: PostgresContainer):
    """Grant LOGIN + password to app_write, audit_writer, compliance_reader.

    These roles are created as NOLOGIN by the migration.  The test suite
    grants LOGIN temporarily so we can open per-role connections.
    """
    host = pg_container_rls.get_container_host_ip()
    port = pg_container_rls.get_exposed_port(5432)

    async def _setup():
        async with superuser_engine.begin() as conn:
            for role, password in [
                ("app_write", "app_write_test"),
                ("audit_writer", "audit_writer_test"),
                ("compliance_reader", "compliance_reader_test"),
            ]:
                await conn.execute(text(
                    f"ALTER ROLE {role} LOGIN PASSWORD '{password}'"
                ))
                # Also grant CONNECT on the database
                db_name = pg_container_rls.dbname
                await conn.execute(text(
                    f"GRANT CONNECT ON DATABASE {db_name} TO {role}"
                ))

    asyncio.run(_setup())
    return {"host": host, "port": port, "dbname": pg_container_rls.dbname}


def _role_engine(role: str, password: str, role_info: dict):
    """Create an asyncpg engine for a specific DB role."""
    url = (
        f"postgresql+asyncpg://{role}:{password}@"
        f"{role_info['host']}:{role_info['port']}/{role_info['dbname']}"
    )
    return create_async_engine(url, poolclass=NullPool)


def _sample_audit_row() -> dict:
    """Return a minimal valid audit_log row dict."""
    return {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "user_role": "clinician",
        "action": "read",
        "resource_type": "patient",
        "resource_id": str(uuid.uuid4()),
        "ip_address": "10.0.0.1",
        "request_id": "trace-abc-123",
        "outcome": "success",
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestAuditLogRLSImmutability:
    """SC-1 through SC-5: RLS policy enforcement tests."""

    def test_audit_writer_insert_succeeds(self, setup_roles):
        """SC-3: audit_writer role can INSERT into audit_log.

        Verifies that the INSERT succeeds and the row is visible to
        compliance_reader (which has SELECT-only privilege).  The SELECT
        is done via compliance_reader because audit_writer has INSERT-only
        privilege — querying as audit_writer would raise 42501.
        """
        writer_engine = _role_engine("audit_writer", "audit_writer_test", setup_roles)
        reader_engine = _role_engine("compliance_reader", "compliance_reader_test", setup_roles)

        async def _insert():
            row = _sample_audit_row()
            async with writer_engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO audit_log "
                        "(id, user_id, user_role, action, resource_type, "
                        " resource_id, ip_address, request_id, outcome) "
                        "VALUES (:id, :user_id, :user_role, :action, :resource_type, "
                        "        :resource_id, :ip_address, :request_id, :outcome)"
                    ),
                    row,
                )
            return row["id"]

        async def _verify(row_id):
            # compliance_reader has SELECT privilege; audit_writer does not
            async with reader_engine.connect() as conn:
                result = await conn.execute(
                    text("SELECT id FROM audit_log WHERE id = :id"),
                    {"id": row_id},
                )
                return result.fetchone()

        inserted_id = asyncio.run(_insert())
        row_back = asyncio.run(_verify(inserted_id))
        asyncio.run(writer_engine.dispose())
        asyncio.run(reader_engine.dispose())
        assert row_back is not None, "audit_writer INSERT must persist the row"

    def test_compliance_reader_select_succeeds(self, setup_roles, superuser_engine):
        """SC-4: compliance_reader can SELECT from audit_log."""
        # First insert a row as audit_writer
        writer_engine = _role_engine("audit_writer", "audit_writer_test", setup_roles)
        reader_engine = _role_engine("compliance_reader", "compliance_reader_test", setup_roles)

        async def _run():
            row = _sample_audit_row()
            async with writer_engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO audit_log "
                        "(id, user_id, user_role, action, resource_type, "
                        " resource_id, ip_address, request_id, outcome) "
                        "VALUES (:id, :user_id, :user_role, :action, :resource_type, "
                        "        :resource_id, :ip_address, :request_id, :outcome)"
                    ),
                    row,
                )
            async with reader_engine.connect() as conn:
                result = await conn.execute(text("SELECT id FROM audit_log"))
                rows = result.fetchall()
            return rows

        rows = asyncio.run(_run())
        asyncio.run(writer_engine.dispose())
        asyncio.run(reader_engine.dispose())
        assert len(rows) >= 1, "compliance_reader must be able to SELECT audit_log"

    def test_compliance_reader_cannot_insert(self, setup_roles):
        """SC-5: compliance_reader INSERT must raise a privilege error."""
        engine = _role_engine("compliance_reader", "compliance_reader_test", setup_roles)

        async def _run():
            row = _sample_audit_row()
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO audit_log "
                        "(id, user_id, user_role, action, resource_type, "
                        " resource_id, ip_address, request_id, outcome) "
                        "VALUES (:id, :user_id, :user_role, :action, :resource_type, "
                        "        :resource_id, :ip_address, :request_id, :outcome)"
                    ),
                    row,
                )

        with pytest.raises(ProgrammingError) as exc_info:
            asyncio.run(_run())
        asyncio.run(engine.dispose())
        # PostgreSQL error code 42501: insufficient_privilege
        assert "42501" in str(exc_info.value)

    def test_app_write_delete_raises_insufficient_privilege(self, setup_roles, superuser_engine):
        """SC-1: app_write DELETE must be blocked by REVOKE + RESTRICTIVE RLS."""
        writer_engine = _role_engine("audit_writer", "audit_writer_test", setup_roles)
        app_engine = _role_engine("app_write", "app_write_test", setup_roles)

        async def _insert_row():
            row = _sample_audit_row()
            async with writer_engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO audit_log "
                        "(id, user_id, user_role, action, resource_type, "
                        " resource_id, ip_address, request_id, outcome) "
                        "VALUES (:id, :user_id, :user_role, :action, :resource_type, "
                        "        :resource_id, :ip_address, :request_id, :outcome)"
                    ),
                    row,
                )
            return row["id"]

        async def _delete_row(row_id):
            async with app_engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM audit_log WHERE id = :id"),
                    {"id": row_id},
                )

        row_id = asyncio.run(_insert_row())

        with pytest.raises(ProgrammingError) as exc_info:
            asyncio.run(_delete_row(row_id))
        asyncio.run(writer_engine.dispose())
        asyncio.run(app_engine.dispose())
        # PostgreSQL error code 42501: insufficient_privilege
        assert "42501" in str(exc_info.value)

    def test_app_write_update_raises_insufficient_privilege(self, setup_roles, superuser_engine):
        """SC-2: app_write UPDATE must be blocked by REVOKE + RESTRICTIVE RLS."""
        writer_engine = _role_engine("audit_writer", "audit_writer_test", setup_roles)
        app_engine = _role_engine("app_write", "app_write_test", setup_roles)

        async def _insert_row():
            row = _sample_audit_row()
            async with writer_engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO audit_log "
                        "(id, user_id, user_role, action, resource_type, "
                        " resource_id, ip_address, request_id, outcome) "
                        "VALUES (:id, :user_id, :user_role, :action, :resource_type, "
                        "        :resource_id, :ip_address, :request_id, :outcome)"
                    ),
                    row,
                )
            return row["id"]

        async def _update_row(row_id):
            async with app_engine.begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE audit_log SET outcome = 'tampered' WHERE id = :id"
                    ),
                    {"id": row_id},
                )

        row_id = asyncio.run(_insert_row())

        with pytest.raises(ProgrammingError) as exc_info:
            asyncio.run(_update_row(row_id))
        asyncio.run(writer_engine.dispose())
        asyncio.run(app_engine.dispose())
        assert "42501" in str(exc_info.value)
