---
id: TASK-005
title: "Write Integration Tests — Archival Logic with Synthetic Past-Dated Records"
user_story: US-010
epic: EP-DATA
sprint: 1
layer: Backend (Test)
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [TASK-001, TASK-002, TASK-003]
---

# TASK-005: Write Integration Tests — Archival Logic with Synthetic Past-Dated Records

> **Story:** US-010 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Backend (Test) | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

US-010 DoD: *"Unit tests verify archival logic with synthetic past-dated records"*.

US-010 Acceptance Criteria Scenario 3 is testable via SQL:

> **Given** the Alembic migration has registered the cron jobs  
> **When** `SELECT * FROM cron.job` is executed on the database  
> **Then** at least 3 jobs are listed: encounter archival, audit log purge, and materialised view refresh

This test file covers:

| Scenario | Test |
|---|---|
| SC-1: Encounter archival moves 7-year-old encounters | `test_archive_old_encounters_moves_expired_rows` |
| SC-1: Encounters within 7 years are NOT archived | `test_archive_old_encounters_preserves_recent_rows` |
| SC-1: Original rows deleted after archival | `test_archive_old_encounters_deletes_originals` |
| SC-2: Purge deletes confirmed-exported audit logs older than 6 years | `test_purge_exported_audit_logs_deletes_eligible_rows` |
| SC-2: Audit logs NOT yet exported are not purged | `test_purge_exported_audit_logs_skips_unexported_rows` |
| SC-2: Audit logs within 6-year window are untouched | `test_purge_exported_audit_logs_preserves_recent_rows` |
| SC-3: All 3 pg_cron jobs registered in cron.job | `test_cron_jobs_registered` |

### pg_cron in Testcontainers

The standard `postgres:15` Docker image does **not** include the `pg_cron` extension. Therefore:

1. **Functional archival/purge logic** tests call the PL/pgSQL functions directly (not via cron scheduling). The functions can be invoked from any session with superuser privileges.
2. **Cron job registration** tests (`test_cron_jobs_registered`) are marked `@pytest.mark.skipif(no_pgcron, ...)` and only run in CI against the real Cloud SQL dev instance (where `cloudsql.enable_pgcron=on`).

The migration applied in testcontainers stops at `<rev6>` (skipping `<rev7>` which schedules pg_cron jobs) to avoid the `CREATE EXTENSION pg_cron` failure. This mirrors the pattern established in US-008/TASK-004.

### Test Isolation Strategy

Each test uses a **transactional fixture** that wraps the test in a `SAVEPOINT` and rolls back after the test, leaving the database state clean between tests. This is the `db_session` fixture pattern from US-006/TASK-008.

---

## Acceptance Criteria Addressed

| US-010 AC | Requirement |
|---|---|
| **Scenario 1** | archive_old_encounters() moves rows with discharge_date < 7 years and deletes originals |
| **Scenario 2** | purge_exported_audit_logs() deletes confirmed-exported rows older than 6 years; preserves others |
| **Scenario 3** | 3 pg_cron jobs present in cron.job (integration test on Cloud SQL dev; skipped in testcontainers) |
| **DoD** | Unit tests verify archival logic with synthetic past-dated records |

---

## Implementation Steps

### 1. Verify Test Dependencies

Confirm `backend/requirements-dev.txt` includes (these were established in US-006/TASK-008):

```
pytest>=8.0.0
pytest-asyncio>=0.23.0
testcontainers[postgres]>=4.0.0
asyncpg>=0.29.0
httpx>=0.27.0
```

### 2. Create `backend/tests/integration/test_data_retention.py`

```python
"""Integration tests for US-010: automated data retention pg_cron jobs.

Tests call the PL/pgSQL archival and purge functions directly (not via
pg_cron scheduling) against a testcontainers PostgreSQL 15 instance.

pg_cron extension is NOT available in the postgres:15 Docker image.
Migrations applied up to <rev6> (encounter archival function created;
pg_cron scheduling migrations <rev6>/<rev7> skipped — they require the
pg_cron extension).

Tests use synthetic records with artificially old timestamps to trigger
the archival/purge boundary conditions.

Acceptance criteria covered:
  SC-1: archive_old_encounters() moves 7-year-old rows, preserves recent rows
  SC-2: purge_exported_audit_logs() deletes confirmed-exported 6-year-old rows;
        skips unexported rows; preserves rows within 6-year window
  SC-3 (pg_cron registration): marked skip for testcontainers; runs in CI
       against Cloud SQL dev instance via SMARTHANDOFF_INTEGRATION_CLOUD_SQL=true
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

# ── Fixtures ──────────────────────────────────────────────────────────────────

POSTGRES_IMAGE = "postgres:15"
# Migrations run up to this revision ID (encounter_archive_table + archival
# function, but NOT the pg_cron scheduling migrations that require pg_cron).
# Update <rev6_id> to match the actual hex ID generated in TASK-002.
LAST_MIGRATION_WITHOUT_PGCRON = "<rev6_id>"

_no_pgcron = not bool(os.environ.get("SMARTHANDOFF_INTEGRATION_CLOUD_SQL"))


@pytest.fixture(scope="session")
def pg_container() -> Generator[PostgresContainer, None, None]:
    """Start a PostgreSQL 15 testcontainer for the test session."""
    with PostgresContainer(image=POSTGRES_IMAGE) as container:
        yield container


@pytest_asyncio.fixture(scope="session")
async def db_engine(pg_container: PostgresContainer):
    """Create an async SQLAlchemy engine for the test container."""
    sync_url = pg_container.get_connection_url()
    async_url = sync_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(async_url, echo=False)

    # Apply Alembic migrations up to the last non-pg_cron revision.
    # We use a subprocess call so Alembic resolves its env.py normally.
    import subprocess

    result = subprocess.run(
        ["alembic", "upgrade", LAST_MIGRATION_WITHOUT_PGCRON],
        capture_output=True,
        text=True,
        cwd=str(_backend_path()),
        env={**os.environ, "DATABASE_URL": sync_url},
    )
    assert result.returncode == 0, (
        f"Alembic upgrade failed:\n{result.stdout}\n{result.stderr}"
    )

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession with SAVEPOINT-based rollback for test isolation."""
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        await session.begin_nested()  # SAVEPOINT
        yield session
        await session.rollback()


def _backend_path():
    """Return path to the backend/ directory relative to this test file."""
    import pathlib

    return pathlib.Path(__file__).parent.parent.parent  # tests/integration/ → backend/


def _make_encounter(
    *,
    discharge_date: datetime,
    status: str = "DISCHARGED",
    unit: str = "ICU",
) -> dict:
    """Create a minimal encounter dict for INSERT."""
    return {
        "id": str(uuid.uuid4()),
        "patient_id": str(uuid.uuid4()),
        "admit_date": discharge_date - timedelta(days=3),
        "discharge_date": discharge_date,
        "status": status,
        "unit": unit,
        "bed_id": None,
        "risk_tier": "LOW",
        "risk_score": None,
        "source_message_id": f"TEST-{uuid.uuid4().hex[:8]}",
        "created_at": discharge_date - timedelta(days=3),
        "updated_at": None,
        "deleted_at": None,
    }


def _make_audit_log(*, created_at: datetime) -> dict:
    """Create a minimal audit_log dict for INSERT."""
    return {
        "id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "action": "READ",
        "entity_type": "encounter",
        "entity_id": str(uuid.uuid4()),
        "ip_address": "127.0.0.1",
        "endpoint": "/api/v1/encounters/test",
        "created_at": created_at,
    }


# ── archive_old_encounters() tests ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_archive_old_encounters_moves_expired_rows(db_session: AsyncSession):
    """Encounters with discharge_date > 7 years ago must be moved to encounter_archive."""
    expired_discharge = datetime.now(timezone.utc) - timedelta(days=365 * 7 + 30)
    enc = _make_encounter(discharge_date=expired_discharge)

    await db_session.execute(
        text("""
            INSERT INTO encounter
              (id, patient_id, admit_date, discharge_date, status, unit,
               bed_id, risk_tier, risk_score, source_message_id,
               created_at, updated_at, deleted_at)
            VALUES
              (:id, :patient_id, :admit_date, :discharge_date, :status, :unit,
               :bed_id, :risk_tier, :risk_score, :source_message_id,
               :created_at, :updated_at, :deleted_at)
        """),
        enc,
    )

    result = await db_session.execute(text("SELECT archive_old_encounters()"))
    rows_archived = result.scalar_one()
    assert rows_archived >= 1, "Expected at least 1 row archived"

    archived = await db_session.execute(
        text("SELECT id FROM encounter_archive WHERE id = :id"),
        {"id": enc["id"]},
    )
    assert archived.fetchone() is not None, "Expired encounter must appear in encounter_archive"


@pytest.mark.asyncio
async def test_archive_old_encounters_preserves_recent_rows(db_session: AsyncSession):
    """Encounters discharged less than 7 years ago must NOT be archived."""
    recent_discharge = datetime.now(timezone.utc) - timedelta(days=365 * 5)
    enc = _make_encounter(discharge_date=recent_discharge)

    await db_session.execute(
        text("""
            INSERT INTO encounter
              (id, patient_id, admit_date, discharge_date, status, unit,
               bed_id, risk_tier, risk_score, source_message_id,
               created_at, updated_at, deleted_at)
            VALUES
              (:id, :patient_id, :admit_date, :discharge_date, :status, :unit,
               :bed_id, :risk_tier, :risk_score, :source_message_id,
               :created_at, :updated_at, :deleted_at)
        """),
        enc,
    )

    await db_session.execute(text("SELECT archive_old_encounters()"))

    archived = await db_session.execute(
        text("SELECT id FROM encounter_archive WHERE id = :id"),
        {"id": enc["id"]},
    )
    assert archived.fetchone() is None, "Recent encounter must NOT appear in encounter_archive"

    still_in_live = await db_session.execute(
        text("SELECT id FROM encounter WHERE id = :id"),
        {"id": enc["id"]},
    )
    assert still_in_live.fetchone() is not None, "Recent encounter must remain in live encounter table"


@pytest.mark.asyncio
async def test_archive_old_encounters_deletes_originals(db_session: AsyncSession):
    """Archived encounters must be removed from the live encounter table."""
    expired_discharge = datetime.now(timezone.utc) - timedelta(days=365 * 7 + 60)
    enc = _make_encounter(discharge_date=expired_discharge)

    await db_session.execute(
        text("""
            INSERT INTO encounter
              (id, patient_id, admit_date, discharge_date, status, unit,
               bed_id, risk_tier, risk_score, source_message_id,
               created_at, updated_at, deleted_at)
            VALUES
              (:id, :patient_id, :admit_date, :discharge_date, :status, :unit,
               :bed_id, :risk_tier, :risk_score, :source_message_id,
               :created_at, :updated_at, :deleted_at)
        """),
        enc,
    )

    await db_session.execute(text("SELECT archive_old_encounters()"))

    remaining = await db_session.execute(
        text("SELECT id FROM encounter WHERE id = :id"),
        {"id": enc["id"]},
    )
    assert remaining.fetchone() is None, "Archived encounter must be deleted from the live encounter table"


# ── purge_exported_audit_logs() tests ─────────────────────────────────────────

async def _insert_audit_log_with_queue(
    session: AsyncSession,
    *,
    created_at: datetime,
    exported: bool,
) -> str:
    """Insert an audit_log row and a corresponding archive_queue entry."""
    log_id = str(uuid.uuid4())
    log = _make_audit_log(created_at=created_at)
    log["id"] = log_id

    await session.execute(
        text("""
            INSERT INTO audit_log
              (id, user_id, action, entity_type, entity_id, ip_address, endpoint, created_at)
            VALUES
              (:id, :user_id, :action, :entity_type, :entity_id, :ip_address, :endpoint, :created_at)
        """),
        log,
    )

    queue_row = {
        "id": str(uuid.uuid4()),
        "audit_log_id": log_id,
        "queued_at": created_at,
        "exported_at": datetime.now(timezone.utc) if exported else None,
        "gcs_object_path": f"gs://audit-log-archive-dev/{log_id}.jsonl" if exported else None,
        "payload": "{}",
    }
    await session.execute(
        text("""
            INSERT INTO audit_log_archive_queue
              (id, audit_log_id, queued_at, exported_at, gcs_object_path, payload)
            VALUES
              (:id, :audit_log_id, :queued_at, :exported_at, :gcs_object_path, :payload::jsonb)
        """),
        queue_row,
    )
    return log_id


@pytest.mark.asyncio
async def test_purge_exported_audit_logs_deletes_eligible_rows(db_session: AsyncSession):
    """Audit logs older than 6 years with export confirmed must be purged."""
    old_date = datetime.now(timezone.utc) - timedelta(days=365 * 6 + 30)
    log_id = await _insert_audit_log_with_queue(
        db_session, created_at=old_date, exported=True
    )

    result = await db_session.execute(text("SELECT purge_exported_audit_logs()"))
    rows_purged = result.scalar_one()
    assert rows_purged >= 1

    remaining = await db_session.execute(
        text("SELECT id FROM audit_log WHERE id = :id"), {"id": log_id}
    )
    assert remaining.fetchone() is None, "Eligible audit log must be deleted after purge"


@pytest.mark.asyncio
async def test_purge_exported_audit_logs_skips_unexported_rows(db_session: AsyncSession):
    """Audit logs older than 6 years but NOT yet exported must NOT be deleted."""
    old_date = datetime.now(timezone.utc) - timedelta(days=365 * 6 + 30)
    log_id = await _insert_audit_log_with_queue(
        db_session, created_at=old_date, exported=False
    )

    await db_session.execute(text("SELECT purge_exported_audit_logs()"))

    remaining = await db_session.execute(
        text("SELECT id FROM audit_log WHERE id = :id"), {"id": log_id}
    )
    assert remaining.fetchone() is not None, "Unexported audit log must NOT be purged"


@pytest.mark.asyncio
async def test_purge_exported_audit_logs_preserves_recent_rows(db_session: AsyncSession):
    """Audit logs within the 6-year window must be untouched even if exported."""
    recent_date = datetime.now(timezone.utc) - timedelta(days=365 * 4)
    log_id = await _insert_audit_log_with_queue(
        db_session, created_at=recent_date, exported=True
    )

    await db_session.execute(text("SELECT purge_exported_audit_logs()"))

    remaining = await db_session.execute(
        text("SELECT id FROM audit_log WHERE id = :id"), {"id": log_id}
    )
    assert remaining.fetchone() is not None, "Recent audit log must NOT be purged regardless of export status"


# ── pg_cron job registration test (Cloud SQL only) ────────────────────────────

@pytest.mark.skipif(
    _no_pgcron,
    reason="pg_cron not available in testcontainers/postgres:15. Set "
           "SMARTHANDOFF_INTEGRATION_CLOUD_SQL=true to run against Cloud SQL dev.",
)
@pytest.mark.asyncio
async def test_cron_jobs_registered(db_session: AsyncSession):
    """Scenario 3: at least 3 pg_cron jobs registered in cron.job."""
    expected_jobs = {
        "archive-old-encounters",
        "purge-old-audit-logs",
        # At least one of the materialised view refresh jobs from US-009:
        "refresh_mv_bed_board",
    }
    result = await db_session.execute(
        text("SELECT jobname FROM cron.job")
    )
    registered = {row[0] for row in result.fetchall()}

    missing = expected_jobs - registered
    assert not missing, (
        f"Expected pg_cron jobs not registered: {missing}. "
        f"Registered jobs: {registered}"
    )
```

### 3. Run the Test Suite

```bash
cd backend

# Run US-010 integration tests (testcontainers)
pytest tests/integration/test_data_retention.py -v

# Expected output:
# PASSED tests/integration/test_data_retention.py::test_archive_old_encounters_moves_expired_rows
# PASSED tests/integration/test_data_retention.py::test_archive_old_encounters_preserves_recent_rows
# PASSED tests/integration/test_data_retention.py::test_archive_old_encounters_deletes_originals
# PASSED tests/integration/test_data_retention.py::test_purge_exported_audit_logs_deletes_eligible_rows
# PASSED tests/integration/test_data_retention.py::test_purge_exported_audit_logs_skips_unexported_rows
# PASSED tests/integration/test_data_retention.py::test_purge_exported_audit_logs_preserves_recent_rows
# SKIPPED tests/integration/test_data_retention.py::test_cron_jobs_registered
#   [SKIPPED: pg_cron not available in testcontainers/postgres:15...]
```

### 4. Run pg_cron Registration Test Against Cloud SQL Dev

```bash
cd backend
SMARTHANDOFF_INTEGRATION_CLOUD_SQL=true \
DATABASE_URL="postgresql+asyncpg://<user>:<pass>@<cloud-sql-ip>/smarthandoff_dev" \
pytest tests/integration/test_data_retention.py::test_cron_jobs_registered -v
```

---

## File Checklist

| File | Action |
|---|---|
| `backend/tests/integration/test_data_retention.py` | Create |
| `backend/requirements-dev.txt` | Verify (no change expected if US-006/TASK-008 already applied) |

---

## Definition of Done Mapping

| DoD Item | Met By |
|---|---|
| Unit tests verify archival logic with synthetic past-dated records | 6 pytest tests with artificially aged discharge/created_at timestamps |
| pg_cron jobs visible in `SELECT * FROM cron.job` | `test_cron_jobs_registered` (Cloud SQL dev CI gate) |
