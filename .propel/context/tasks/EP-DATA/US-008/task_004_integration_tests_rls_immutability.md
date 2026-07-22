---
id: TASK-004
title: "Write Integration Tests — RLS Immutability (DELETE/UPDATE Denial) and Middleware Audit Trail Verification"
user_story: US-008
epic: EP-DATA
sprint: 1
layer: Backend (Test)
estimate: 3h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [TASK-001, TASK-002]
---

# TASK-004: Write Integration Tests — RLS Immutability (DELETE/UPDATE Denial) and Middleware Audit Trail Verification

> **Story:** US-008 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Backend (Test) | **Est:** 3 h
> **Status:** Done | **Date:** 2026-07-15

---

## Context

US-008 has four explicit acceptance criterion scenarios and a DoD requirement for integration test coverage. Each scenario maps directly to a test:

| Scenario | Test Name |
|---|---|
| SC-1: `app_write` cannot DELETE | `test_app_write_delete_raises_insufficient_privilege` |
| SC-2: `app_write` cannot UPDATE | `test_app_write_update_raises_insufficient_privilege` |
| SC-3: `audit_writer` INSERT succeeds | `test_audit_writer_insert_succeeds` |
| SC-4: `compliance_reader` SELECT succeeds | `test_compliance_reader_select_succeeds` |
| DoD: Middleware creates correct record | `test_middleware_creates_audit_log_entry` |

Tests use **pytest** with **pytest-asyncio** and **testcontainers** (PostgreSQL 15), consistent with the pattern established in US-006/TASK-008 and US-007/TASK-006.

The PostgreSQL RLS tests **must connect as the target role** to be meaningful. The testcontainers `PostgresContainer` starts as `postgres` (superuser). Each test creates a role-specific connection URL by replacing credentials:

```python
# Role connection URL pattern for testcontainers:
# postgresql+asyncpg://app_write:password@host:port/db
```

### Important: pg_cron Exclusion

The `0003_pgcron_retention` migration (TASK-003) is **skipped** in test containers because `pg_cron` is not available in the `postgres:15` testcontainers image. The test suite runs migrations up to and including `0002_audit_log_rls` only.

---

## Acceptance Criteria Addressed

| US-008 AC | Requirement |
|---|---|
| **Scenario 1** | DELETE raises `InsufficientPrivilege` for `app_write` |
| **Scenario 2** | UPDATE raises `InsufficientPrivilege` for `app_write` |
| **Scenario 3** | `audit_writer` INSERT succeeds with all required fields |
| **Scenario 4** | `compliance_reader` SELECT returns rows without error |
| **DoD** | Integration tests confirm all four scenarios |

---

## Implementation Steps

### 1. Add Test Dependencies (if not already present from US-006/TASK-008)

Verify `backend/requirements-dev.txt` contains:

```
pytest>=8.0.0
pytest-asyncio>=0.23.0
testcontainers[postgres]>=4.0.0
asyncpg>=0.29.0
httpx>=0.27.0
```

### 2. Create `backend/tests/integration/test_audit_log_rls.py`

```python
"""Integration tests for US-008: audit_log RLS immutability.

Tests verify that PostgreSQL row-level security correctly denies
DELETE and UPDATE operations to the app_write role while permitting
INSERT via audit_writer and SELECT via compliance_reader.

Uses testcontainers (PostgreSQL 15) consistent with US-006/TASK-008 pattern.
Migrations applied up to 0002_audit_log_rls (pg_cron migration excluded
as the extension is unavailable in the postgres:15 container image).

Acceptance criteria covered:
  SC-1: app_write DELETE → InsufficientPrivilege (psycopg2.errors or asyncpg)
  SC-2: app_write UPDATE → InsufficientPrivilege
  SC-3: audit_writer INSERT → success, all fields persisted
  SC-4: compliance_reader SELECT → rows returned, no error
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer


# ── Pytest configuration ──────────────────────────────────────────────────────
pytestmark = pytest.mark.asyncio


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def pg_container():
    """Session-scoped PostgreSQL 15 container with migrations applied to rev2."""
    with PostgresContainer("postgres:15", dbname="test_smarthandoff") as container:
        # Run migrations up to 0002_audit_log_rls (stop before pg_cron)
        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option(
            "sqlalchemy.url",
            container.get_connection_url().replace("postgresql+psycopg2", "postgresql"),
        )
        # Apply all available migrations except pgcron (use revision tag for safety)
        # Assumes rev2 is the audit_log_rls revision (TASK-001)
        command.upgrade(alembic_cfg, "audit_log_rls@head")
        yield container


@pytest.fixture(scope="session")
def superuser_url(pg_container) -> str:
    """Superuser connection URL for setup operations (role creation, grants)."""
    return pg_container.get_connection_url().replace(
        "postgresql+psycopg2", "postgresql+asyncpg"
    )


@pytest_asyncio.fixture(scope="session")
async def setup_roles(superuser_url: str) -> None:
    """Create test roles and set passwords for role-specific connections.

    The testcontainers postgres superuser creates the roles used in tests
    by granting them LOGIN and setting a known test password.
    """
    engine = create_async_engine(superuser_url, poolclass=NullPool)
    async with engine.begin() as conn:
        # Allow the roles created by the migration to LOGIN with a test password
        await conn.execute(text("ALTER ROLE app_write LOGIN PASSWORD 'app_write_test';"))
        await conn.execute(text("ALTER ROLE audit_writer LOGIN PASSWORD 'audit_writer_test';"))
        await conn.execute(text("ALTER ROLE compliance_reader LOGIN PASSWORD 'compliance_reader_test';"))

        # Insert a known audit_log row for DELETE/UPDATE tests
        await conn.execute(text("""
            INSERT INTO audit_log (id, user_id, action, entity_type, entity_id, ip_address, endpoint, created_at)
            VALUES (
                '00000000-0000-0000-0000-000000000001',
                '00000000-0000-0000-0000-000000000099',
                'READ',
                'patient',
                'patient-001',
                '10.0.0.1',
                '/api/v1/patients/patient-001',
                now()
            )
        """))
    await engine.dispose()


def _make_url(pg_container, user: str, password: str) -> str:
    """Build an asyncpg connection URL for a specific role."""
    base = pg_container.get_connection_url()
    # Replace user/password in the URL
    # base format: postgresql+psycopg2://test:test@host:port/dbname
    import re
    url = re.sub(
        r"postgresql\+psycopg2://[^@]+@",
        f"postgresql+asyncpg://{user}:{password}@",
        base,
    )
    return url


# ── Tests ─────────────────────────────────────────────────────────────────────

async def test_app_write_delete_raises_insufficient_privilege(
    pg_container, setup_roles
) -> None:
    """SC-1: app_write role cannot DELETE any row from audit_log.

    The RESTRICTIVE RLS policy (USING false) makes all rows invisible
    to app_write, causing DELETE to find 0 rows — but the explicit
    REVOKE INSERT, UPDATE, DELETE ensures the privilege is denied outright.
    We verify the operation raises a ProgrammingError wrapping
    PostgreSQL error code 42501 (insufficient_privilege).
    """
    url = _make_url(pg_container, "app_write", "app_write_test")
    engine = create_async_engine(url, poolclass=NullPool)

    try:
        async with engine.begin() as conn:
            with pytest.raises(ProgrammingError) as exc_info:
                await conn.execute(
                    text("DELETE FROM audit_log WHERE id = :id"),
                    {"id": "00000000-0000-0000-0000-000000000001"},
                )
        assert "42501" in str(exc_info.value) or "permission denied" in str(exc_info.value).lower()
    finally:
        await engine.dispose()


async def test_app_write_update_raises_insufficient_privilege(
    pg_container, setup_roles
) -> None:
    """SC-2: app_write role cannot UPDATE any row in audit_log.

    Verifies PostgreSQL error code 42501 (insufficient_privilege) is raised
    when app_write attempts to modify an existing audit log entry.
    """
    url = _make_url(pg_container, "app_write", "app_write_test")
    engine = create_async_engine(url, poolclass=NullPool)

    try:
        async with engine.begin() as conn:
            with pytest.raises(ProgrammingError) as exc_info:
                await conn.execute(
                    text(
                        "UPDATE audit_log SET action = 'TAMPERED' "
                        "WHERE id = :id"
                    ),
                    {"id": "00000000-0000-0000-0000-000000000001"},
                )
        assert "42501" in str(exc_info.value) or "permission denied" in str(exc_info.value).lower()
    finally:
        await engine.dispose()


async def test_audit_writer_insert_succeeds(pg_container, setup_roles) -> None:
    """SC-3: audit_writer role can INSERT into audit_log.

    Verifies that the new row is persisted with all required fields:
    user_id, action, entity_type, entity_id, ip_address, created_at.
    """
    audit_writer_url = _make_url(pg_container, "audit_writer", "audit_writer_test")
    superuser_url_val = pg_container.get_connection_url().replace(
        "postgresql+psycopg2", "postgresql+asyncpg"
    )

    new_id = uuid.uuid4()
    user_id = uuid.uuid4()

    # INSERT as audit_writer
    engine_aw = create_async_engine(audit_writer_url, poolclass=NullPool)
    try:
        async with engine_aw.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO audit_log
                        (id, user_id, action, entity_type, entity_id, ip_address, endpoint, created_at)
                    VALUES
                        (:id, :user_id, :action, :entity_type, :entity_id, :ip, :endpoint, :created_at)
                """),
                {
                    "id": new_id,
                    "user_id": user_id,
                    "action": "READ",
                    "entity_type": "patient",
                    "entity_id": "patient-999",
                    "ip": "192.168.1.1",
                    "endpoint": "/api/v1/patients/patient-999",
                    "created_at": datetime.now(timezone.utc),
                },
            )
    finally:
        await engine_aw.dispose()

    # Verify the row was persisted — read as superuser
    engine_su = create_async_engine(superuser_url_val, poolclass=NullPool)
    try:
        async with engine_su.connect() as conn:
            result = await conn.execute(
                text("SELECT user_id, action, entity_type, entity_id, ip_address FROM audit_log WHERE id = :id"),
                {"id": new_id},
            )
            row = result.fetchone()

        assert row is not None, "audit_log row was not persisted"
        assert str(row.user_id) == str(user_id)
        assert row.action == "READ"
        assert row.entity_type == "patient"
        assert row.entity_id == "patient-999"
        assert row.ip_address == "192.168.1.1"
    finally:
        await engine_su.dispose()


async def test_compliance_reader_select_succeeds(pg_container, setup_roles) -> None:
    """SC-4: compliance_reader role can SELECT from audit_log.

    Verifies that a date-range compliance query returns rows without
    raising a permission error.
    """
    url = _make_url(pg_container, "compliance_reader", "compliance_reader_test")
    engine = create_async_engine(url, poolclass=NullPool)

    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT id, action, entity_type, created_at "
                    "FROM audit_log "
                    "WHERE created_at >= now() - INTERVAL '1 day'"
                )
            )
            rows = result.fetchall()
        # At minimum the row inserted in setup_roles is present
        assert len(rows) >= 1
        # Verify the row has the expected shape
        assert all(row.action in {"READ", "WRITE", "DELETE"} for row in rows)
    finally:
        await engine.dispose()


async def test_compliance_reader_cannot_insert(pg_container, setup_roles) -> None:
    """Additional: compliance_reader is SELECT-only — INSERT must be denied.

    This confirms the principle of least privilege is correctly enforced
    for the compliance_reader role (not a direct US-008 scenario but
    required by the DoD privilege model).
    """
    url = _make_url(pg_container, "compliance_reader", "compliance_reader_test")
    engine = create_async_engine(url, poolclass=NullPool)

    try:
        async with engine.begin() as conn:
            with pytest.raises(ProgrammingError) as exc_info:
                await conn.execute(
                    text("""
                        INSERT INTO audit_log (id, action, entity_type, created_at)
                        VALUES (gen_random_uuid(), 'READ', 'patient', now())
                    """)
                )
        assert "42501" in str(exc_info.value) or "permission denied" in str(exc_info.value).lower()
    finally:
        await engine.dispose()
```

### 3. Create `backend/tests/integration/test_audit_middleware.py`

```python
"""Integration tests for US-008: HIPAA audit logging middleware.

Tests verify that HIPAAAuditMiddleware creates the correct audit_log
record when PHI endpoints are accessed, and does NOT create records
for non-PHI endpoints.

Uses the FastAPI TestClient with an in-memory audit session override
to avoid requiring a live database connection for middleware unit tests.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

from app.middleware.audit import HIPAAAuditMiddleware, _is_phi_endpoint, _extract_entity_info


# ── Unit tests for helper functions (no DB, no network) ──────────────────────

def test_is_phi_endpoint_phi_path() -> None:
    """PHI endpoint prefixes are correctly identified."""
    assert _is_phi_endpoint("/api/v1/patients") is True
    assert _is_phi_endpoint("/api/v1/patients/abc-123") is True
    assert _is_phi_endpoint("/api/v1/encounters/xyz/documents") is True
    assert _is_phi_endpoint("/api/v1/medications") is True
    assert _is_phi_endpoint("/api/v1/admin/audit") is True
    assert _is_phi_endpoint("/api/v1/admin/users") is True


def test_is_phi_endpoint_excluded_paths() -> None:
    """Non-PHI paths are correctly excluded from audit."""
    assert _is_phi_endpoint("/health") is False
    assert _is_phi_endpoint("/ready") is False
    assert _is_phi_endpoint("/metrics") is False
    assert _is_phi_endpoint("/docs") is False
    assert _is_phi_endpoint("/openapi.json") is False


def test_extract_entity_info_patient_with_id() -> None:
    entity_type, entity_id = _extract_entity_info("/api/v1/patients/abc-123")
    assert entity_type == "patient"
    assert entity_id == "abc-123"


def test_extract_entity_info_collection() -> None:
    entity_type, entity_id = _extract_entity_info("/api/v1/medications")
    assert entity_type == "medication"
    assert entity_id is None


def test_extract_entity_info_nested_resource() -> None:
    entity_type, entity_id = _extract_entity_info("/api/v1/encounters/enc-456/documents")
    assert entity_type == "encounter"
    assert entity_id == "enc-456"


# ── Integration tests with mocked audit session ───────────────────────────────

@pytest.mark.asyncio
async def test_middleware_creates_audit_log_entry_for_phi_endpoint() -> None:
    """Middleware writes an audit_log record for a PHI endpoint GET request.

    Uses a mock audit session to capture the AuditLog object written
    without requiring a live database.
    """
    captured_records: list = []

    async def mock_write(*args, **kwargs) -> None:
        captured_records.append(kwargs)

    app = FastAPI()

    @app.get("/api/v1/patients/{patient_id}")
    async def get_patient(patient_id: str):
        return {"id": patient_id}

    app.add_middleware(HIPAAAuditMiddleware)

    with patch("app.middleware.audit._write_audit_record", side_effect=mock_write):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Simulate a JWT-authenticated request (user_id set on request.state)
            response = await client.get("/api/v1/patients/patient-001")

    assert response.status_code == 200
    assert len(captured_records) == 1
    record = captured_records[0]
    assert record["action"] == "READ"
    assert record["entity_type"] == "patient"
    assert record["entity_id"] == "patient-001"
    assert record["endpoint"] == "/api/v1/patients/patient-001"


@pytest.mark.asyncio
async def test_middleware_does_not_audit_health_endpoint() -> None:
    """Middleware does NOT write an audit record for /health."""
    captured_records: list = []

    async def mock_write(*args, **kwargs) -> None:
        captured_records.append(kwargs)

    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    app.add_middleware(HIPAAAuditMiddleware)

    with patch("app.middleware.audit._write_audit_record", side_effect=mock_write):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")

    assert response.status_code == 200
    assert len(captured_records) == 0


@pytest.mark.asyncio
async def test_middleware_audit_write_failure_does_not_fail_request() -> None:
    """Audit write failure is swallowed — primary response is unaffected."""

    async def mock_write_raises(*args, **kwargs) -> None:
        raise RuntimeError("Simulated audit DB connection failure")

    app = FastAPI()

    @app.get("/api/v1/patients/{patient_id}")
    async def get_patient(patient_id: str):
        return {"id": patient_id}

    app.add_middleware(HIPAAAuditMiddleware)

    with patch("app.middleware.audit._write_audit_record", side_effect=mock_write_raises):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/patients/patient-001")

    # Response must be 200 even though audit write raised
    assert response.status_code == 200
```

### 4. Run the Full Test Suite

```bash
cd backend
pytest tests/integration/test_audit_log_rls.py tests/integration/test_audit_middleware.py -v
```

All 9 tests must pass. Expected output:

```
tests/integration/test_audit_log_rls.py::test_app_write_delete_raises_insufficient_privilege PASSED
tests/integration/test_audit_log_rls.py::test_app_write_update_raises_insufficient_privilege PASSED
tests/integration/test_audit_log_rls.py::test_audit_writer_insert_succeeds PASSED
tests/integration/test_audit_log_rls.py::test_compliance_reader_select_succeeds PASSED
tests/integration/test_audit_log_rls.py::test_compliance_reader_cannot_insert PASSED
tests/integration/test_audit_middleware.py::test_middleware_creates_audit_log_entry_for_phi_endpoint PASSED
tests/integration/test_audit_middleware.py::test_middleware_does_not_audit_health_endpoint PASSED
tests/integration/test_audit_middleware.py::test_middleware_audit_write_failure_does_not_fail_request PASSED
tests/integration/test_audit_middleware.py::test_is_phi_endpoint_phi_path PASSED
... (helper function tests)
```

---

## Files Affected

| File | Action |
|---|---|
| `backend/tests/integration/test_audit_log_rls.py` | Create |
| `backend/tests/integration/test_audit_middleware.py` | Create |
| `backend/requirements-dev.txt` | Verify `httpx>=0.27.0` present |

---

## Definition of Done

- [ ] `test_app_write_delete_raises_insufficient_privilege` passes — error code 42501 confirmed
- [ ] `test_app_write_update_raises_insufficient_privilege` passes — error code 42501 confirmed
- [ ] `test_audit_writer_insert_succeeds` passes — all required fields persisted
- [ ] `test_compliance_reader_select_succeeds` passes — rows returned without error
- [ ] `test_compliance_reader_cannot_insert` passes — INSERT denied for read-only role
- [ ] `test_middleware_creates_audit_log_entry_for_phi_endpoint` passes
- [ ] `test_middleware_does_not_audit_health_endpoint` passes
- [ ] `test_middleware_audit_write_failure_does_not_fail_request` passes
- [ ] All tests pass in Cloud Build CI without manual intervention
