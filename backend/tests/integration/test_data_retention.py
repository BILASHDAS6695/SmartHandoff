"""Integration tests for US-010: automated data retention pg_cron jobs.

Calls the PL/pgSQL archival and purge functions directly (not via pg_cron
scheduling) against a testcontainers PostgreSQL 15 instance.

pg_cron extension is NOT available in the postgres:15-alpine Docker image.
Migrations are applied up to revision c2e5f8a91d3b (widen_mrn — the last
revision before d4b7e2f91c30 which installs pg_cron). The objects needed
for retention testing are then created inline by the session fixture:

  - encounter_archive table          (production: migration b3d0e1f92c48)
  - audit_log_archive_queue table    (production: migration d4b7e2f91c30)
  - archive_old_encounters() fn      (production: migration c4e1f2a03d59)
  - purge_exported_audit_logs() fn   (production: migration d5f2a3b14e60)

Test isolation uses SAVEPOINT-based rollback so each test starts clean.

Acceptance criteria covered:
  SC-1: archive_old_encounters() moves rows with discharge_date > 7 years
        and deletes originals; preserves recent rows.
  SC-2: purge_exported_audit_logs() deletes confirmed-exported rows older
        than 6 years; skips unexported rows; preserves rows within window.
  SC-3: pg_cron job registration (skipped — requires Cloud SQL dev instance).
"""
from __future__ import annotations

import os
import pathlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer

_BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent.parent

# Alembic revision immediately before any pg_cron migration.
# This matches the boundary used by test_audit_log_rls.py.
_LAST_SAFE_REVISION = "c2e5f8a91d3b"

# Set True only when running against Cloud SQL dev (pg_cron available).
_no_pgcron = not bool(os.environ.get("SMARTHANDOFF_INTEGRATION_CLOUD_SQL"))

# ── Inline DDL — objects requiring pg_cron in production migrations ───────────

# encounter_archive: mirrors b3d0e1f92c48_encounter_archive_table.py
_ENCOUNTER_ARCHIVE_DDL = """
CREATE TABLE IF NOT EXISTS encounter_archive (
    id                    UUID          NOT NULL,
    patient_id            UUID          NOT NULL,
    status                VARCHAR(32)   NOT NULL,
    admit_date            TIMESTAMPTZ,
    discharge_date        TIMESTAMPTZ,
    admitting_diagnosis   TEXT,
    attending_physician_id UUID,
    unit                  VARCHAR(64),
    risk_tier             VARCHAR(16)   NOT NULL,
    risk_score            FLOAT,
    visit_number          VARCHAR(64),
    created_at            TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ,
    deleted_at            TIMESTAMPTZ,
    archived_at           TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_encounter_archive PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_encounter_archive_patient_id
    ON encounter_archive (patient_id);
CREATE INDEX IF NOT EXISTS ix_encounter_archive_archived_at
    ON encounter_archive (archived_at);
CREATE INDEX IF NOT EXISTS ix_encounter_archive_discharge_date
    ON encounter_archive (discharge_date);
REVOKE ALL ON encounter_archive FROM app_write;
GRANT SELECT ON encounter_archive TO compliance_reader;
"""

# audit_log_archive_queue: mirrors d4b7e2f91c30_pgcron_retention.py table DDL
# (created without pg_cron extension requirement)
_AUDIT_QUEUE_DDL = """
CREATE TABLE IF NOT EXISTS audit_log_archive_queue (
    id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    audit_log_id     UUID         NOT NULL,
    queued_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    exported_at      TIMESTAMPTZ,
    gcs_object_path  VARCHAR(512),
    payload          JSON         NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_archive_queue_audit_log_id
    ON audit_log_archive_queue (audit_log_id);
CREATE INDEX IF NOT EXISTS ix_archive_queue_queued_at
    ON audit_log_archive_queue (queued_at);
CREATE INDEX IF NOT EXISTS ix_archive_queue_exported_at
    ON audit_log_archive_queue (exported_at);
"""

# archive_old_encounters(): mirrors c4e1f2a03d59_pgcron_encounter_archival.py
_ARCHIVE_ENCOUNTERS_FUNCTION_DDL = """
CREATE OR REPLACE FUNCTION archive_old_encounters()
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_cutoff          TIMESTAMPTZ := NOW() - INTERVAL '7 years';
    v_batch_ids       UUID[];
    v_batch_count     INTEGER;
    v_total_archived  INTEGER := 0;
BEGIN
    LOOP
        SELECT array_agg(id)
          INTO v_batch_ids
          FROM (
              SELECT id
                FROM encounter
               WHERE discharge_date < v_cutoff
                 AND deleted_at IS NULL
               ORDER BY discharge_date ASC
               LIMIT 500
               FOR UPDATE SKIP LOCKED
          ) sub;

        EXIT WHEN v_batch_ids IS NULL OR array_length(v_batch_ids, 1) = 0;

        v_batch_count := array_length(v_batch_ids, 1);

        INSERT INTO encounter_archive (
            id, patient_id, status, admit_date, discharge_date,
            admitting_diagnosis, attending_physician_id, unit,
            risk_tier, risk_score, visit_number,
            created_at, updated_at, deleted_at,
            archived_at
        )
        SELECT
            id, patient_id, status, admit_date, discharge_date,
            admitting_diagnosis, attending_physician_id, unit,
            risk_tier, risk_score, visit_number,
            created_at, updated_at, deleted_at,
            NOW()
          FROM encounter
         WHERE id = ANY(v_batch_ids);

        DELETE FROM encounter WHERE id = ANY(v_batch_ids);

        v_total_archived := v_total_archived + v_batch_count;
    END LOOP;

    RETURN v_total_archived;

EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'archive_old_encounters FAILED: %  SQLSTATE: %', SQLERRM, SQLSTATE;
    RAISE;
END;
$$;
"""

# purge_exported_audit_logs(): mirrors d5f2a3b14e60_pgcron_audit_log_purge.py
_PURGE_AUDIT_LOGS_FUNCTION_DDL = """
CREATE OR REPLACE FUNCTION purge_exported_audit_logs()
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_cutoff        TIMESTAMPTZ := NOW() - INTERVAL '2190 days';
    v_purge_ids     UUID[];
    v_batch_count   INTEGER;
    v_total_purged  INTEGER := 0;
BEGIN
    LOOP
        SELECT array_agg(al.id)
          INTO v_purge_ids
          FROM (
              SELECT al.id
                FROM audit_log al
                JOIN audit_log_archive_queue q ON q.audit_log_id = al.id
               WHERE al.created_at < v_cutoff
                 AND q.exported_at IS NOT NULL
               ORDER BY al.created_at ASC
               LIMIT 1000
          ) al;

        EXIT WHEN v_purge_ids IS NULL OR array_length(v_purge_ids, 1) = 0;

        v_batch_count := array_length(v_purge_ids, 1);

        DELETE FROM audit_log WHERE id = ANY(v_purge_ids);
        DELETE FROM audit_log_archive_queue WHERE audit_log_id = ANY(v_purge_ids);

        v_total_purged := v_total_purged + v_batch_count;
    END LOOP;

    RETURN v_total_purged;

EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'purge_exported_audit_logs FAILED: %  SQLSTATE: %', SQLERRM, SQLSTATE;
    RAISE;
END;
$$;
"""


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def pg_container_retention() -> Generator[PostgresContainer, None, None]:
    """Start a PostgreSQL 15 testcontainer for the retention test session."""
    with PostgresContainer("postgres:15-alpine") as container:
        yield container


@pytest.fixture(scope="session")
def _sync_url_retention(pg_container_retention: PostgresContainer) -> str:
    return pg_container_retention.get_connection_url()


@pytest.fixture(scope="session")
def _async_url_retention(pg_container_retention: PostgresContainer) -> str:
    url = pg_container_retention.get_connection_url()
    return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")


@pytest.fixture(scope="session")
def _apply_retention_migrations(_sync_url_retention: str, _async_url_retention: str) -> None:
    """Apply Alembic migrations up to the last revision that does not require pg_cron."""
    os.environ["DATABASE_URL"] = _async_url_retention
    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    command.upgrade(cfg, _LAST_SAFE_REVISION)


@pytest_asyncio.fixture(scope="session")
async def db_engine_retention(
    _async_url_retention: str,
    _apply_retention_migrations: None,
):
    """Create async engine and install inline retention DDL objects."""
    engine = create_async_engine(_async_url_retention, echo=False, poolclass=NullPool)

    async with engine.begin() as conn:
        # Create encounter_archive (production: b3d0e1f92c48)
        await conn.execute(text(_ENCOUNTER_ARCHIVE_DDL))
        # Create audit_log_archive_queue (production: d4b7e2f91c30)
        await conn.execute(text(_AUDIT_QUEUE_DDL))
        # Create archive_old_encounters() (production: c4e1f2a03d59)
        await conn.execute(text(_ARCHIVE_ENCOUNTERS_FUNCTION_DDL))
        # Create purge_exported_audit_logs() (production: d5f2a3b14e60)
        await conn.execute(text(_PURGE_AUDIT_LOGS_FUNCTION_DDL))

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def shared_patient_id(db_engine_retention) -> str:
    """Insert a single synthetic patient row for encounter FK satisfaction.

    Committed outside any test transaction — persists for the full session.
    No PHI: all fields are synthetic test-only values.
    """
    patient_id = str(uuid.uuid4())
    async with db_engine_retention.connect() as conn:
        await conn.execute(
            text("""
                INSERT INTO patient
                  (id, first_name, last_name, date_of_birth, mrn_encrypted, language_code)
                VALUES
                  (:id, 'TEST-RETENTION-FIRST', 'TEST-RETENTION-LAST',
                   '2000-01-01', :mrn, 'en')
            """),
            {"id": patient_id, "mrn": f"TEST-MRN-{uuid.uuid4().hex[:12]}"},
        )
        await conn.commit()
    return patient_id


@pytest_asyncio.fixture
async def db_session(db_engine_retention) -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession with SAVEPOINT-based rollback for test isolation."""
    session_factory = async_sessionmaker(db_engine_retention, expire_on_commit=False)
    async with session_factory() as session:
        await session.begin_nested()  # SAVEPOINT
        yield session
        await session.rollback()


# ── Helper functions ──────────────────────────────────────────────────────────

def _make_encounter(
    *,
    patient_id: str,
    discharge_date: datetime,
    status: str = "DISCHARGED",
    unit: str = "ICU",
) -> dict:
    """Return a minimal encounter dict for a raw SQL INSERT.

    Covers all non-nullable columns in the encounter table as of migration
    a3f9e2c10b4d (initial schema). Uses synthetic data only — no PHI.
    """
    admit_date = discharge_date - timedelta(days=3)
    return {
        "id": str(uuid.uuid4()),
        "patient_id": patient_id,
        "status": status,
        "admit_date": admit_date,
        "discharge_date": discharge_date,
        "admitting_diagnosis": None,
        "attending_physician_id": None,
        "unit": unit,
        "risk_tier": "LOW",
        "risk_score": None,
        "visit_number": None,
        "created_at": admit_date,
        "updated_at": None,
        "deleted_at": None,
    }


def _make_audit_log(*, created_at: datetime) -> dict:
    """Return a minimal audit_log dict for a raw SQL INSERT.

    Uses actual column names from the audit_log schema at migration
    c2e5f8a91d3b — note: 'endpoint' column does NOT exist at this revision
    (it is added later by e1f8d3c92a47).  Uses resource_type/resource_id
    (NOT entity_type/entity_id — those are not actual column names).
    """
    return {
        "id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "user_role": "nurse",
        "resource_type": "encounter",
        "resource_id": str(uuid.uuid4()),
        "action": "READ",
        "ip_address": "127.0.0.1",
        "request_id": uuid.uuid4().hex,
        "outcome": "success",
        "created_at": created_at,
    }


_INSERT_ENCOUNTER_SQL = text("""
    INSERT INTO encounter
      (id, patient_id, status, admit_date, discharge_date,
       admitting_diagnosis, attending_physician_id, unit,
       risk_tier, risk_score, visit_number,
       created_at, updated_at, deleted_at)
    VALUES
      (:id, :patient_id, :status, :admit_date, :discharge_date,
       :admitting_diagnosis, :attending_physician_id, :unit,
       :risk_tier, :risk_score, :visit_number,
       :created_at, :updated_at, :deleted_at)
""")

_INSERT_AUDIT_LOG_SQL = text("""
    INSERT INTO audit_log
      (id, user_id, user_role, resource_type, resource_id, action,
       ip_address, request_id, outcome, created_at)
    VALUES
      (:id, :user_id, :user_role, :resource_type, :resource_id, :action,
       :ip_address, :request_id, :outcome, :created_at)
""")


async def _insert_audit_log_with_queue(
    session: AsyncSession,
    *,
    created_at: datetime,
    exported: bool,
) -> str:
    """Insert an audit_log row and a corresponding archive_queue row."""
    log = _make_audit_log(created_at=created_at)

    await session.execute(_INSERT_AUDIT_LOG_SQL, log)

    queue_row = {
        "id": str(uuid.uuid4()),
        "audit_log_id": log["id"],
        "queued_at": created_at,
        "exported_at": datetime.now(timezone.utc) if exported else None,
        "gcs_object_path": (
            f"gs://smarthandoff-audit-export-dev/{log['id']}.jsonl"
            if exported
            else None
        ),
        "payload": "{}",
    }
    await session.execute(
        text("""
            INSERT INTO audit_log_archive_queue
              (id, audit_log_id, queued_at, exported_at, gcs_object_path, payload)
            VALUES
              (:id, :audit_log_id, :queued_at, :exported_at, :gcs_object_path, :payload::json)
        """),
        queue_row,
    )
    return log["id"]


# ── archive_old_encounters() tests ────────────────────────────────────────────

@pytest.mark.integration
async def test_archive_old_encounters_moves_expired_rows(
    db_session: AsyncSession,
    shared_patient_id: str,
) -> None:
    """SC-1: encounters with discharge_date > 7 years ago are moved to encounter_archive."""
    expired_discharge = datetime.now(timezone.utc) - timedelta(days=365 * 7 + 30)
    enc = _make_encounter(patient_id=shared_patient_id, discharge_date=expired_discharge)

    await db_session.execute(_INSERT_ENCOUNTER_SQL, enc)

    result = await db_session.execute(text("SELECT archive_old_encounters()"))
    rows_archived = result.scalar_one()
    assert rows_archived >= 1, "Expected at least 1 row archived"

    archived = await db_session.execute(
        text("SELECT id FROM encounter_archive WHERE id = :id"),
        {"id": enc["id"]},
    )
    assert archived.fetchone() is not None, (
        "Expired encounter must appear in encounter_archive"
    )


@pytest.mark.integration
async def test_archive_old_encounters_preserves_recent_rows(
    db_session: AsyncSession,
    shared_patient_id: str,
) -> None:
    """SC-1: encounters discharged less than 7 years ago are NOT archived."""
    recent_discharge = datetime.now(timezone.utc) - timedelta(days=365 * 5)
    enc = _make_encounter(patient_id=shared_patient_id, discharge_date=recent_discharge)

    await db_session.execute(_INSERT_ENCOUNTER_SQL, enc)
    await db_session.execute(text("SELECT archive_old_encounters()"))

    archived = await db_session.execute(
        text("SELECT id FROM encounter_archive WHERE id = :id"),
        {"id": enc["id"]},
    )
    assert archived.fetchone() is None, (
        "Recent encounter must NOT appear in encounter_archive"
    )

    still_live = await db_session.execute(
        text("SELECT id FROM encounter WHERE id = :id"),
        {"id": enc["id"]},
    )
    assert still_live.fetchone() is not None, (
        "Recent encounter must remain in the live encounter table"
    )


@pytest.mark.integration
async def test_archive_old_encounters_deletes_originals(
    db_session: AsyncSession,
    shared_patient_id: str,
) -> None:
    """SC-1: archived encounters are removed from the live encounter table."""
    expired_discharge = datetime.now(timezone.utc) - timedelta(days=365 * 7 + 60)
    enc = _make_encounter(patient_id=shared_patient_id, discharge_date=expired_discharge)

    await db_session.execute(_INSERT_ENCOUNTER_SQL, enc)
    await db_session.execute(text("SELECT archive_old_encounters()"))

    remaining = await db_session.execute(
        text("SELECT id FROM encounter WHERE id = :id"),
        {"id": enc["id"]},
    )
    assert remaining.fetchone() is None, (
        "Archived encounter must be deleted from the live encounter table"
    )


# ── purge_exported_audit_logs() tests ─────────────────────────────────────────

@pytest.mark.integration
async def test_purge_exported_audit_logs_deletes_eligible_rows(
    db_session: AsyncSession,
) -> None:
    """SC-2: audit logs older than 6 years with GCS export confirmed are purged."""
    old_date = datetime.now(timezone.utc) - timedelta(days=365 * 6 + 30)
    log_id = await _insert_audit_log_with_queue(
        db_session, created_at=old_date, exported=True
    )

    result = await db_session.execute(text("SELECT purge_exported_audit_logs()"))
    rows_purged = result.scalar_one()
    assert rows_purged >= 1, "Expected at least 1 row purged"

    remaining = await db_session.execute(
        text("SELECT id FROM audit_log WHERE id = :id"), {"id": log_id}
    )
    assert remaining.fetchone() is None, (
        "Eligible audit log row must be deleted after purge"
    )


@pytest.mark.integration
async def test_purge_exported_audit_logs_skips_unexported_rows(
    db_session: AsyncSession,
) -> None:
    """SC-2: audit logs older than 6 years but NOT exported must NOT be purged."""
    old_date = datetime.now(timezone.utc) - timedelta(days=365 * 6 + 30)
    log_id = await _insert_audit_log_with_queue(
        db_session, created_at=old_date, exported=False
    )

    await db_session.execute(text("SELECT purge_exported_audit_logs()"))

    remaining = await db_session.execute(
        text("SELECT id FROM audit_log WHERE id = :id"), {"id": log_id}
    )
    assert remaining.fetchone() is not None, (
        "Unexported audit log row must NOT be purged (GCS copy not confirmed)"
    )


@pytest.mark.integration
async def test_purge_exported_audit_logs_preserves_recent_rows(
    db_session: AsyncSession,
) -> None:
    """SC-2: audit logs within 6-year window are untouched even if exported."""
    recent_date = datetime.now(timezone.utc) - timedelta(days=365 * 4)
    log_id = await _insert_audit_log_with_queue(
        db_session, created_at=recent_date, exported=True
    )

    await db_session.execute(text("SELECT purge_exported_audit_logs()"))

    remaining = await db_session.execute(
        text("SELECT id FROM audit_log WHERE id = :id"), {"id": log_id}
    )
    assert remaining.fetchone() is not None, (
        "Audit log within 6-year retention window must NOT be purged"
    )


# ── pg_cron job registration test (Cloud SQL dev only) ────────────────────────

@pytest.mark.integration
@pytest.mark.skipif(
    _no_pgcron,
    reason=(
        "pg_cron not available in testcontainers/postgres:15-alpine. "
        "Set SMARTHANDOFF_INTEGRATION_CLOUD_SQL=true to run against Cloud SQL dev."
    ),
)
async def test_cron_jobs_registered(db_session: AsyncSession) -> None:
    """SC-3: all pg_cron retention jobs are registered in cron.job on Cloud SQL dev.

    Verifies the complete job set from US-008 + US-009 + US-010 migrations.
    """
    expected_jobs = {
        "archive-old-encounters",      # US-010 TASK-002
        "purge-old-audit-logs",        # US-010 TASK-003
        "refresh_mv_bed_board",        # US-009 TASK-005
    }
    result = await db_session.execute(text("SELECT jobname FROM cron.job"))
    registered = {row[0] for row in result.fetchall()}

    missing = expected_jobs - registered
    assert not missing, (
        f"Expected pg_cron jobs not registered in cron.job: {missing}. "
        f"All registered jobs: {registered}"
    )
