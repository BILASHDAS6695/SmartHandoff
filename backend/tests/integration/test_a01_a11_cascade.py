"""Integration tests for US-015: A11 (cancel admit) full cascade.

Tests end-to-end behaviour using a real async SQLAlchemy session against
an in-memory SQLite database (or the shared PostgreSQL testcontainer).

Scenarios covered:
  1. Full A11 cascade: encounter transitions + tasks cancelled + docs soft-cancelled
  2. A11 on unknown encounter → 404 (EncounterNotFoundError)
  3. A13 cancel discharge: document content retained, only status set to CANCELLED

PHI safety: all test data uses synthetic values — no real MRNs, names, or DOBs.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import EncounterNotFoundError
from app.models.agent_task import AgentTask, AgentTaskStatus
from app.models.document import Document, DocumentStatus
from app.models.encounter import Encounter, EncounterStatus
from app.models.patient import Patient
from app.services.cancellation_service import CancellationService

# async_db fixture is provided by tests/integration/conftest.py

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_patient(db: AsyncSession) -> Patient:
    """Seed a synthetic Patient row (all PHI fields use non-real test data)."""
    patient = Patient(
        id=uuid4(),
        first_name="TestFirst",
        last_name="TestLast",
        date_of_birth="1980-01-01",
        mrn_encrypted=f"MRN-TEST-{uuid4().hex[:8]}",  # unique per call
    )
    db.add(patient)
    await db.flush()
    return patient


async def _seed_encounter(
    db: AsyncSession,
    patient_id,
    status: EncounterStatus = EncounterStatus.ADMITTED,
    unit: str = "ICU-1",
    previous_unit: str | None = "WARD-3",
) -> Encounter:
    enc = Encounter(
        id=uuid4(),
        patient_id=patient_id,
        status=status.value,
        unit=unit,
        previous_unit=previous_unit,
    )
    db.add(enc)
    await db.flush()
    return enc


async def _seed_agent_task(
    db: AsyncSession,
    encounter_id,
    status: AgentTaskStatus = AgentTaskStatus.QUEUED,
    agent_type: str = "coordinator",
) -> AgentTask:
    task = AgentTask(
        id=uuid4(),
        encounter_id=encounter_id,
        agent_type=agent_type,
        status=status.value,
    )
    db.add(task)
    await db.flush()
    return task


async def _seed_document(
    db: AsyncSession,
    encounter_id,
    status: DocumentStatus = DocumentStatus.DRAFT,
    content: str = "Discharge summary content.",
) -> Document:
    doc = Document(
        id=uuid4(),
        encounter_id=encounter_id,
        document_type="discharge_summary",
        status=status.value,
        content=content,
    )
    db.add(doc)
    await db.flush()
    return doc


# ---------------------------------------------------------------------------
# Integration test: A11 full cascade
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a11_full_cascade(async_db: AsyncSession):
    """A11: encounter → PRE_ADMISSION, tasks cancelled, docs soft-cancelled."""
    svc = CancellationService()
    patient = await _seed_patient(async_db)
    enc = await _seed_encounter(async_db, patient_id=patient.id, status=EncounterStatus.ADMITTED)
    task = await _seed_agent_task(async_db, enc.id, AgentTaskStatus.QUEUED, agent_type="coordinator")
    doc = await _seed_document(async_db, enc.id, DocumentStatus.DRAFT)

    async with async_db.begin_nested():
        result = await svc.handle_cancel_admit(enc.id, async_db)

    assert result.event_type == "A11"
    assert result.tasks_cancelled >= 1
    assert result.docs_cancelled >= 1

    # Verify DB state
    await async_db.refresh(enc)
    await async_db.refresh(task)
    await async_db.refresh(doc)

    assert enc.status == EncounterStatus.PRE_ADMISSION.value
    assert task.status == AgentTaskStatus.CANCELLED.value
    assert doc.status == DocumentStatus.CANCELLED.value


# ---------------------------------------------------------------------------
# Integration test: A11 unknown encounter → EncounterNotFoundError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a11_unknown_encounter_raises_404(async_db: AsyncSession):
    """A11 on a non-existent encounter must raise EncounterNotFoundError."""
    svc = CancellationService()
    fake_id = uuid4()

    with pytest.raises(EncounterNotFoundError):
        await svc.handle_cancel_admit(fake_id, async_db)


# ---------------------------------------------------------------------------
# Integration test: A13 document content retained
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a13_document_content_retained(async_db: AsyncSession):
    """A13: document status set to CANCELLED but content is preserved."""
    svc = CancellationService()
    patient = await _seed_patient(async_db)
    enc = await _seed_encounter(
        async_db, patient_id=patient.id, status=EncounterStatus.DISCHARGED
    )
    original_content = "This discharge summary must be retained."
    doc = await _seed_document(
        async_db, enc.id, DocumentStatus.PENDING_APPROVAL, content=original_content
    )

    async with async_db.begin_nested():
        result = await svc.handle_cancel_discharge(enc.id, async_db)

    assert result.event_type == "A13"

    await async_db.refresh(doc)
    assert doc.status == DocumentStatus.CANCELLED.value
    assert doc.content == original_content  # content must be retained (DR-005)
