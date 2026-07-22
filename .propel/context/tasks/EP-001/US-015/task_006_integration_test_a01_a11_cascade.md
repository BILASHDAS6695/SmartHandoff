---
id: TASK-006
title: "Write Integration Test — A01 Creates 5 AgentTasks → A11 Cancels All (Database + API Round-Trip)"
user_story: US-015
epic: EP-001
sprint: 2
layer: Testing
estimate: 2.5h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-015/TASK-001, US-015/TASK-002, US-015/TASK-003, US-015/TASK-004]
---

# TASK-006: Write Integration Test — A01 Creates 5 AgentTasks → A11 Cancels All (Database + API Round-Trip)

> **Story:** US-015 | **Epic:** EP-001 | **Sprint:** 2 | **Layer:** Testing | **Est:** 2.5 h
> **Status:** Done | **Date:** 2026-07-22

---

## Context

US-015 DoD specifies:

> *"Integration test: A01 → 5 tasks created → A11 → all tasks CANCELLED"*

This integration test verifies the complete A11 cancellation flow end-to-end across the database and the API layer — not just unit-level mocks. It confirms that:

1. An encounter seeded with `status=ADMITTED` and 5 `AgentTask` records in `PENDING` or `IN_PROGRESS` states is the correct precondition (simulating the state after A01 processing).
2. `POST /api/v1/encounters/{id}/cancel-event` with `event_type="A11"` atomically transitions the encounter to `PRE_ADMISSION` **and** cancels all 5 tasks.
3. The DB reflects the final state: no non-terminal tasks remain.
4. The API response includes the correct `tasks_cancelled` count.
5. Pub/Sub and SignalR are mocked — this test validates DB + API layer only, not the messaging infrastructure (that is covered by unit tests in TASK-005).

**Test database:**

The test uses an in-memory SQLite database via SQLAlchemy's `create_async_engine("sqlite+aiosqlite:///:memory:")` with Alembic migrations applied. This avoids Cloud SQL dependency in CI while still exercising the full ORM layer.

An alternative using PostgreSQL is provided as a docker-compose fixture for local development (`pytest -m integration --pg`).

**Why not mock the DB here:**

Unit tests (TASK-005) verify individual methods with mock sessions. This integration test verifies that the `CancellationService`, the `Encounter` ORM model's state machine, and the FastAPI endpoint all compose correctly against a real (in-memory) database — catching issues like missing `flush()` calls, incorrect JOIN behaviour, or ORM-level constraint violations that mocks cannot detect.

Design refs: US-015 DoD, DR-023 (encounter state machine), ADR-003 (PostgreSQL primary), TR-020 (CI/CD test requirements).

---

## Acceptance Criteria Addressed

| US-015 AC | Requirement |
|---|---|
| **Scenario 1 (full flow)** | A01 state + 5 AgentTasks → POST cancel-event A11 → all tasks CANCELLED; encounter PRE_ADMISSION |
| **DoD** | Integration test: A01 → 5 tasks created → A11 → all tasks CANCELLED |

---

## Implementation Steps

### 1. Scaffold integration test directory

```bash
mkdir -p api-gateway/tests/integration
touch api-gateway/tests/integration/__init__.py
```

### 2. Create `conftest.py` for in-memory DB fixture

```python
# api-gateway/tests/integration/conftest.py
"""Pytest fixtures for integration tests using an in-memory async SQLite DB."""
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.models.base import Base  # DeclarativeBase shared by all ORM models


@pytest_asyncio.fixture
async def async_db():
    """Provide an in-memory SQLite async session with schema created.

    Uses ``aiosqlite`` driver for asyncio-compatible SQLite.
    Schema is created fresh per test function (function scope).
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        yield session

    await engine.dispose()
```

### 3. Create `api-gateway/tests/integration/test_a01_a11_cascade.py`

```python
"""Integration test: A01 creates 5 AgentTasks → A11 cancels all.

Tests the full cancellation chain:
  - Precondition:  encounter.status=ADMITTED, 5 AgentTask records (PENDING + IN_PROGRESS)
  - Action:        POST /api/v1/encounters/{id}/cancel-event  {"event_type": "A11"}
  - Postcondition: encounter.status=PRE_ADMISSION; all 5 tasks status=CANCELLED
  - Verification:  DB query confirms no non-terminal tasks remain

Database: in-memory SQLite via async_db fixture (conftest.py).
Pub/Sub and SignalR are mocked — this test validates DB + API only.

Design refs: US-015 DoD, DR-023, ADR-003.
"""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app  # FastAPI application
from app.models.encounter import Encounter, EncounterStatus
from app.models.agent_task import AgentTask, AgentTaskStatus
from app.models.patient import Patient


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


async def _seed_admitted_encounter(db: AsyncSession) -> tuple[Encounter, list[AgentTask]]:
    """Seed DB with an ADMITTED encounter and 5 mixed-status AgentTasks."""
    patient = Patient(
        id=uuid4(),
        mrn_encrypted=b"encrypted-mrn",
        first_name_encrypted=b"encrypted-fn",
        last_name_encrypted=b"encrypted-ln",
        dob_encrypted=b"encrypted-dob",
    )
    db.add(patient)

    encounter = Encounter(
        id=uuid4(),
        patient_id=patient.id,
        status=EncounterStatus.ADMITTED.value,
        current_unit="ICU",
        previous_unit="ED",
    )
    db.add(encounter)

    # Mix of PENDING and IN_PROGRESS tasks (both are non-terminal)
    tasks = []
    for i, status in enumerate(
        [AgentTaskStatus.PENDING, AgentTaskStatus.PENDING,
         AgentTaskStatus.IN_PROGRESS, AgentTaskStatus.PENDING,
         AgentTaskStatus.IN_PROGRESS]
    ):
        task = AgentTask(
            id=uuid4(),
            encounter_id=encounter.id,
            agent_type=f"agent-type-{i}",
            status=status.value,
        )
        db.add(task)
        tasks.append(task)

    await db.commit()
    return encounter, tasks


# ------------------------------------------------------------------
# Integration test
# ------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a11_cancels_all_agent_tasks_and_reverts_encounter(async_db):
    """A11: all 5 non-terminal AgentTasks cancelled; encounter → PRE_ADMISSION."""

    encounter, seeded_tasks = await _seed_admitted_encounter(async_db)
    encounter_id = encounter.id

    # Patch CancellationDispatcher to avoid real Pub/Sub + SignalR in integration test
    with patch(
        "app.api.v1.encounters.get_cancellation_dispatcher",
        return_value=AsyncMock(dispatch_post_commit=AsyncMock()),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/encounters/{encounter_id}/cancel-event",
                json={"event_type": "A11"},
                headers={"Authorization": "Bearer test-service-jwt"},
            )

    # API response assertions
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["event_type"] == "A11"
    assert body["tasks_cancelled"] == 5
    assert body["encounter_id"] == str(encounter_id)

    # DB state assertions — reload from DB (bypass ORM cache)
    await async_db.expire_all()

    result = await async_db.execute(
        select(Encounter).where(Encounter.id == encounter_id)
    )
    updated_encounter = result.scalar_one()
    assert updated_encounter.status == EncounterStatus.PRE_ADMISSION.value, (
        f"Expected PRE_ADMISSION, got {updated_encounter.status}"
    )

    # Confirm all 5 tasks are CANCELLED
    tasks_result = await async_db.execute(
        select(func.count(AgentTask.id))
        .where(
            AgentTask.encounter_id == encounter_id,
            AgentTask.status != AgentTaskStatus.CANCELLED.value,
        )
    )
    non_cancelled_count = tasks_result.scalar()
    assert non_cancelled_count == 0, (
        f"Expected 0 non-cancelled tasks, found {non_cancelled_count}"
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a11_returns_404_for_unknown_encounter(async_db):
    """A11 on non-existent encounter returns HTTP 404."""
    unknown_id = uuid4()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/encounters/{unknown_id}/cancel-event",
            json={"event_type": "A11"},
            headers={"Authorization": "Bearer test-service-jwt"},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a13_discharge_docs_soft_cancelled_content_retained(async_db):
    """A13: discharge Document records get status=CANCELLED; content byte value unchanged."""
    from app.models.document import Document, DocumentStatus

    patient = Patient(id=uuid4(), mrn_encrypted=b"mrn", first_name_encrypted=b"fn",
                      last_name_encrypted=b"ln", dob_encrypted=b"dob")
    async_db.add(patient)

    encounter = Encounter(
        id=uuid4(),
        patient_id=patient.id,
        status=EncounterStatus.DISCHARGED.value,
    )
    async_db.add(encounter)

    original_content = b"encrypted-discharge-summary-content"
    doc = Document(
        id=uuid4(),
        encounter_id=encounter.id,
        document_type="DISCHARGE_SUMMARY",
        status=DocumentStatus.APPROVED.value,
        content=original_content,
    )
    async_db.add(doc)
    await async_db.commit()

    with patch(
        "app.api.v1.encounters.get_cancellation_dispatcher",
        return_value=AsyncMock(dispatch_post_commit=AsyncMock()),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/encounters/{encounter.id}/cancel-event",
                json={"event_type": "A13"},
                headers={"Authorization": "Bearer test-service-jwt"},
            )

    assert response.status_code == 200

    await async_db.expire_all()
    doc_result = await async_db.execute(select(Document).where(Document.id == doc.id))
    updated_doc = doc_result.scalar_one()

    assert updated_doc.status == DocumentStatus.CANCELLED.value
    assert updated_doc.content == original_content, "Document content must not be deleted"
```

### 4. Mark integration tests and configure pytest

In `api-gateway/pytest.ini` (or `pyproject.toml`), register the `integration` marker:

```ini
[pytest]
markers =
    integration: Integration tests requiring a database fixture (slower; run separately in CI)
```

Run integration tests:

```bash
cd api-gateway
pip install aiosqlite  # for SQLite async driver

# Run integration tests only
pytest tests/integration/ -m integration -v

# Run all tests (unit + integration)
pytest tests/ -v
```

---

## Definition of Done Checklist

- [ ] `async_db` fixture creates in-memory SQLite schema with Alembic metadata applied
- [ ] `test_a11_cancels_all_agent_tasks_and_reverts_encounter` passes: encounter is `PRE_ADMISSION`; 0 non-cancelled tasks in DB
- [ ] `test_a11_returns_404_for_unknown_encounter` passes
- [ ] `test_a13_discharge_docs_soft_cancelled_content_retained` passes: `status=CANCELLED`, `content` unchanged
- [ ] CancellationDispatcher mocked in all integration tests (no real Pub/Sub or SignalR calls)
- [ ] `integration` marker registered in `pytest.ini`
- [ ] Test passes in CI (`Cloud Build Step 5: Integration Tests`)
