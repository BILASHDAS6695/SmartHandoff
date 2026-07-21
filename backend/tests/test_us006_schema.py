"""Integration tests for US-006: PostgreSQL Schema Migrations via Alembic.

Tests run against a real PostgreSQL 15 container (testcontainers).
Each test maps directly to one of the four US-006 acceptance criteria scenarios.
"""
from __future__ import annotations

import pathlib
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import EncounterStateTransitionError
from app.models import (
    AdtEvent,
    Encounter,
    EncounterStatus,
    Patient,
    RiskTier,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_patient(mrn: str = "MRN-TEST-001") -> Patient:
    """Create an unsaved Patient fixture. Uses stub encryption (no real PHI)."""
    return Patient(
        first_name="Test",
        last_name="Patient",
        date_of_birth="1980-01-01",
        mrn_encrypted=mrn,  # Stub encryption: stored as-is until US-007 replaces stub
        language_code="en",
    )


async def _make_encounter(
    session: AsyncSession,
    patient: Patient,
    status: str = EncounterStatus.REGISTERED.value,
) -> Encounter:
    """Persist a minimal encounter and return it."""
    encounter = Encounter(
        patient_id=patient.id,
        status=status,
        risk_tier=RiskTier.UNKNOWN.value,
    )
    session.add(encounter)
    await session.flush()
    return encounter


# ── Scenario 1: Clean migration applies without errors ─────────────────────

class TestScenario1CleanMigration:
    """AC Scenario 1: alembic upgrade head creates all 10 tables on a fresh DB."""

    @pytest.mark.asyncio
    async def test_all_10_tables_exist(self, db_session: AsyncSession) -> None:
        """Verify all 10 expected tables are present after upgrade head."""
        expected_tables = {
            "app_user",
            "patient",
            "encounter",
            "bed",
            "adt_event",
            "medication",
            "agent_task",
            "document",
            "audit_log",
            "chatbot_transcript",
        }
        result = await db_session.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' "
                "ORDER BY tablename"
            )
        )
        actual_tables = {row[0] for row in result.fetchall()}
        assert expected_tables.issubset(actual_tables), (
            f"Missing tables: {expected_tables - actual_tables}"
        )

    @pytest.mark.asyncio
    async def test_adt_event_source_message_id_unique_index_exists(
        self, db_session: AsyncSession
    ) -> None:
        """DR-022: Verify unique index on adt_event.source_message_id."""
        result = await db_session.execute(
            text(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE tablename = 'adt_event'
                  AND indexname = 'ix_adt_event_source_message_id'
                """
            )
        )
        row = result.fetchone()
        assert row is not None, "ix_adt_event_source_message_id index not found"
        assert "unique" in row[1].lower(), "Index is not UNIQUE"

    @pytest.mark.asyncio
    async def test_patient_mrn_encrypted_unique_index_exists(
        self, db_session: AsyncSession
    ) -> None:
        """DR-020, DR-004: Verify unique index on patient.mrn_encrypted."""
        result = await db_session.execute(
            text(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE tablename = 'patient'
                  AND indexname = 'ix_patient_mrn_encrypted'
                """
            )
        )
        assert result.fetchone() is not None, "ix_patient_mrn_encrypted index not found"

    @pytest.mark.asyncio
    async def test_encounter_composite_indexes_exist(
        self, db_session: AsyncSession
    ) -> None:
        """DR-004: Verify all three composite indexes on encounter table."""
        expected_indexes = {
            "ix_encounter_patient_admit",
            "ix_encounter_unit_status",
            "ix_encounter_risk_tier_status",
        }
        result = await db_session.execute(
            text(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'encounter'"
            )
        )
        actual_indexes = {row[0] for row in result.fetchall()}
        assert expected_indexes.issubset(actual_indexes), (
            f"Missing indexes: {expected_indexes - actual_indexes}"
        )

    @pytest.mark.asyncio
    async def test_patient_and_encounter_have_deleted_at_column(
        self, db_session: AsyncSession
    ) -> None:
        """DR-005: Verify soft-delete columns exist on patient and encounter."""
        for table_name in ("patient", "encounter"):
            result = await db_session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    f"WHERE table_name = '{table_name}' AND column_name = 'deleted_at'"
                )
            )
            assert result.fetchone() is not None, (
                f"deleted_at column missing from {table_name}"
            )


# ── Scenario 2: Encounter state machine enforced at ORM layer ──────────────

class TestScenario2EncounterStateMachine:
    """AC Scenario 2: Invalid transitions raise EncounterStateTransitionError (409)."""

    @pytest.mark.asyncio
    async def test_invalid_discharged_to_admitted_raises_409(
        self, db_session: AsyncSession
    ) -> None:
        """DISCHARGED → ADMITTED without A13 flag must raise EncounterStateTransitionError."""
        patient = _make_patient(mrn=f"MRN-SM-{uuid.uuid4().hex[:6]}")
        db_session.add(patient)
        await db_session.flush()

        encounter = await _make_encounter(
            db_session, patient, status=EncounterStatus.ADMITTED.value
        )
        # Transition ADMITTED → DISCHARGED (valid)
        encounter.status = EncounterStatus.DISCHARGED.value
        await db_session.flush()

        # Attempt DISCHARGED → ADMITTED without A13 flag — must raise
        with pytest.raises(EncounterStateTransitionError) as exc_info:
            encounter.status = EncounterStatus.ADMITTED.value

        assert exc_info.value.status_code == 409
        assert exc_info.value.from_status == EncounterStatus.DISCHARGED.value
        assert exc_info.value.to_status == EncounterStatus.ADMITTED.value

        # Verify encounter status did NOT change
        assert encounter.status == EncounterStatus.DISCHARGED.value

    @pytest.mark.asyncio
    async def test_a13_cancel_with_flag_succeeds(
        self, db_session: AsyncSession
    ) -> None:
        """DISCHARGED → ADMITTED with A13 session flag must succeed."""
        patient = _make_patient(mrn=f"MRN-A13-{uuid.uuid4().hex[:6]}")
        db_session.add(patient)
        await db_session.flush()

        encounter = await _make_encounter(
            db_session, patient, status=EncounterStatus.ADMITTED.value
        )
        encounter.status = EncounterStatus.DISCHARGED.value
        await db_session.flush()

        # Set A13 cancel flag on the session
        db_session.info["allow_a13_cancel_discharge"] = str(encounter.id)
        encounter.status = EncounterStatus.ADMITTED.value  # Must NOT raise

        assert encounter.status == EncounterStatus.ADMITTED.value
        # Confirm flag was consumed by the listener
        assert "allow_a13_cancel_discharge" not in db_session.info

    @pytest.mark.asyncio
    async def test_valid_transitions_succeed(
        self, db_session: AsyncSession
    ) -> None:
        """Full valid lifecycle: REGISTERED → ADMITTED → TRANSFERRED → DISCHARGED."""
        patient = _make_patient(mrn=f"MRN-VT-{uuid.uuid4().hex[:6]}")
        db_session.add(patient)
        await db_session.flush()

        encounter = await _make_encounter(db_session, patient)

        encounter.status = EncounterStatus.ADMITTED.value
        encounter.status = EncounterStatus.TRANSFERRED.value
        encounter.status = EncounterStatus.DISCHARGED.value

        await db_session.flush()
        assert encounter.status == EncounterStatus.DISCHARGED.value

    @pytest.mark.asyncio
    async def test_invalid_transition_registered_to_discharged_raises(
        self, db_session: AsyncSession
    ) -> None:
        """REGISTERED → DISCHARGED (skipping ADMITTED) must raise."""
        patient = _make_patient(mrn=f"MRN-IT-{uuid.uuid4().hex[:6]}")
        db_session.add(patient)
        await db_session.flush()

        encounter = await _make_encounter(db_session, patient)

        with pytest.raises(EncounterStateTransitionError):
            encounter.status = EncounterStatus.DISCHARGED.value


# ── Scenario 3: MRN unique constraint prevents duplicate patients ───────────

class TestScenario3MrnUniqueConstraint:
    """AC Scenario 3: Duplicate MRN raises IntegrityError (UniqueConstraintViolation)."""

    @pytest.mark.asyncio
    async def test_duplicate_mrn_raises_integrity_error(
        self, db_session: AsyncSession
    ) -> None:
        """DR-020: Two patients with the same MRN must not both be persisted."""
        mrn = f"MRN-DUP-{uuid.uuid4().hex[:8]}"

        patient_a = _make_patient(mrn=mrn)
        db_session.add(patient_a)
        await db_session.flush()  # Persists patient_a successfully

        # Attempt to insert a second patient with the same MRN
        patient_b = _make_patient(mrn=mrn)
        db_session.add(patient_b)

        with pytest.raises(IntegrityError) as exc_info:
            await db_session.flush()

        # Confirm it is a unique constraint violation on mrn_encrypted
        assert "mrn_encrypted" in str(exc_info.value).lower() or \
               "uq_patient_mrn_encrypted" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_duplicate_adt_source_message_id_raises_integrity_error(
        self, db_session: AsyncSession
    ) -> None:
        """DR-022: Two ADT events with the same MSH-10 message ID must be rejected."""
        patient = _make_patient(mrn=f"MRN-ADT-{uuid.uuid4().hex[:6]}")
        db_session.add(patient)
        await db_session.flush()

        encounter = await _make_encounter(
            db_session, patient, status=EncounterStatus.ADMITTED.value
        )

        message_id = f"MSG-{uuid.uuid4().hex}"

        event_a = AdtEvent(
            encounter_id=encounter.id,
            source_message_id=message_id,
            event_type="A01",
            event_timestamp=datetime.now(tz=timezone.utc),
        )
        db_session.add(event_a)
        await db_session.flush()

        # Duplicate message
        event_b = AdtEvent(
            encounter_id=encounter.id,
            source_message_id=message_id,  # Same MSH-10
            event_type="A01",
            event_timestamp=datetime.now(tz=timezone.utc),
        )
        db_session.add(event_b)

        with pytest.raises(IntegrityError) as exc_info:
            await db_session.flush()

        assert "source_message_id" in str(exc_info.value).lower() or \
               "uq_adt_event_source_message_id" in str(exc_info.value).lower()


# ── Scenario 4: Soft delete preserves patient records ──────────────────────

class TestScenario4SoftDelete:
    """AC Scenario 4: Soft delete sets deleted_at; excludes from standard queries."""

    @pytest.mark.asyncio
    async def test_soft_delete_sets_deleted_at(
        self, db_session: AsyncSession
    ) -> None:
        """soft_delete() must set deleted_at to a non-null UTC timestamp."""
        patient = _make_patient(mrn=f"MRN-SD-{uuid.uuid4().hex[:6]}")
        db_session.add(patient)
        await db_session.flush()

        assert patient.deleted_at is None

        patient.soft_delete()
        await db_session.flush()

        assert patient.deleted_at is not None
        assert patient.is_deleted is True

    @pytest.mark.asyncio
    async def test_soft_deleted_patient_excluded_from_standard_query(
        self, db_session: AsyncSession
    ) -> None:
        """Standard query with `WHERE deleted_at IS NULL` must exclude soft-deleted records."""
        mrn = f"MRN-SDE-{uuid.uuid4().hex[:6]}"
        patient = _make_patient(mrn=mrn)
        db_session.add(patient)
        await db_session.flush()

        patient_id = patient.id
        patient.soft_delete()
        await db_session.flush()

        # Standard query (active records only)
        result = await db_session.execute(
            select(Patient).where(
                Patient.id == patient_id,
                Patient.deleted_at.is_(None),
            )
        )
        assert result.scalar_one_or_none() is None, (
            "Soft-deleted patient should not appear in standard query"
        )

    @pytest.mark.asyncio
    async def test_soft_deleted_patient_retrievable_with_include_deleted(
        self, db_session: AsyncSession
    ) -> None:
        """Admin query without deleted_at filter must return soft-deleted records."""
        mrn = f"MRN-SDR-{uuid.uuid4().hex[:6]}"
        patient = _make_patient(mrn=mrn)
        db_session.add(patient)
        await db_session.flush()

        patient_id = patient.id
        patient.soft_delete()
        await db_session.flush()

        # Query without filter (include all)
        result = await db_session.execute(
            select(Patient).where(Patient.id == patient_id)
        )
        retrieved = result.scalar_one_or_none()
        assert retrieved is not None, "Soft-deleted patient not retrievable without filter"
        assert retrieved.is_deleted is True


# ── DoD: alembic downgrade -1 reversibility ────────────────────────────────

class TestAlembicDowngrade:
    """DoD: Both migrations must be reversible via `alembic downgrade -1`."""

    def test_downgrade_audit_log_rls(self, database_url: str) -> None:
        """alembic downgrade -1 removes audit_log RLS without error."""
        import os
        from alembic import command
        from alembic.config import Config

        _backend = pathlib.Path(__file__).resolve().parent.parent
        os.environ["DATABASE_URL"] = database_url
        cfg = Config(str(_backend / "alembic.ini"))
        cfg.set_main_option("script_location", str(_backend / "alembic"))

        # Downgrade one step (removes audit_log_rls migration)
        command.downgrade(cfg, "-1")

        # Upgrade back to head for remaining tests
        command.upgrade(cfg, "head")

    def test_downgrade_initial_schema(self, database_url: str) -> None:
        """alembic downgrade base removes all 10 tables without FK violations."""
        import os
        from alembic import command
        from alembic.config import Config

        _backend = pathlib.Path(__file__).resolve().parent.parent
        os.environ["DATABASE_URL"] = database_url
        cfg = Config(str(_backend / "alembic.ini"))
        cfg.set_main_option("script_location", str(_backend / "alembic"))

        # Downgrade to base (removes all tables)
        command.downgrade(cfg, "base")

        # Upgrade back to head for remaining tests
        command.upgrade(cfg, "head")
