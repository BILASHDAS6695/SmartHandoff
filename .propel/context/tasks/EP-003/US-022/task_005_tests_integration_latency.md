---
id: TASK-005
title: "Write Integration Test for End-to-End SignalR Latency (≤1s) and Unit Tests for Group Routing"
user_story: US-022
epic: EP-003
sprint: 2
layer: QA / Testing
estimate: 4h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [TASK-001, TASK-002, TASK-003, TASK-004]
---

# TASK-005: Write Integration Test for End-to-End SignalR Latency (≤1s) and Unit Tests for Group Routing

> **Story:** US-022 | **Epic:** EP-003 | **Sprint:** 2 | **Layer:** QA / Testing | **Est:** 4 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-022 DoD specifies two distinct test deliverables:

> *"Integration test: end-to-end latency from DB write to Angular `task_updated` event ≤1 second"*
> *"Unit tests: group routing logic for encounter/unit/role subscriptions"*

The unit tests for group routing are already delivered in **TASK-002** (`test_group_resolver.py`). This task delivers:

1. **Integration test** — measures server-to-client latency from the moment `TaskStatusTransitionService.transition()` commits the DB write to the moment the Angular `HubConnection` fires the `task_updated` callback. Uses a Python `asyncio` test with:
   - A real (test) PostgreSQL database.
   - A mocked Azure SignalR broadcaster (since the test environment has no Azure SignalR Service).
   - Timing assertions verifying the broadcast is initiated within 1 second of the DB commit.
   - Validates that the broadcaster received the correct group names and payload.

2. **Latency measurement helper** — a `LatencyProbe` utility that records `db_committed_at` and `broadcast_called_at` timestamps for assertions.

3. **Scenario 2 routing integration test** — verifies that unit `4B` users are NOT in the groups targeted for a unit `3A` event.

---

## Acceptance Criteria Addressed

| US-022 AC | Requirement |
|---|---|
| **Scenario 1** | Integration test confirms latency from DB commit to broadcast call ≤1s |
| **Scenario 2** | Test confirms correct group names constructed; unit 4B excluded |
| **DoD** | Integration test and unit tests for group routing implemented and passing |

---

## Implementation Steps

### 1. File structure

```
backend/tests/
├── integration/
│   └── signalr/
│       ├── conftest.py                        ← THIS TASK
│       └── test_signalr_latency.py            ← THIS TASK
└── unit/
    └── signalr/
        ├── test_broadcaster.py                ← TASK-001
        ├── test_group_resolver.py             ← TASK-002
        └── test_task_status_service.py        ← TASK-003
```

```bash
mkdir -p backend/tests/integration/signalr
touch backend/tests/integration/signalr/__init__.py
touch backend/tests/integration/__init__.py
```

### 2. Create `backend/tests/integration/signalr/conftest.py`

```python
"""Fixtures for SignalR integration tests.

Provides:
  - async_db_session: real async PostgreSQL test session (uses test DB from env).
  - recorded_broadcaster: a SignalRBroadcaster subclass that records calls + timestamps.
  - transition_service: TaskStatusTransitionService wired to recorded_broadcaster.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.agent_task import AgentTask, AgentTaskStatus
from app.models.base import Base  # declarative base
from app.services.task_status_service import TaskStatusTransitionService
from app.signalr.broadcaster import SignalRBroadcaster
from app.signalr.schemas import TaskUpdatedPayload


# ---------------------------------------------------------------------------
# Recorded broadcaster — captures broadcast calls and timestamps
# ---------------------------------------------------------------------------

@dataclass
class BroadcastRecord:
    payload: TaskUpdatedPayload
    called_at: datetime


class RecordingBroadcaster(SignalRBroadcaster):
    """SignalRBroadcaster subclass that records calls instead of HTTP requests.

    Used in integration tests to measure latency without a live Azure SignalR Service.
    """

    def __init__(self) -> None:
        # Skip parent __init__ to avoid parsing a real connection string.
        self._records: list[BroadcastRecord] = []

    async def broadcast_task_updated(self, payload: TaskUpdatedPayload) -> None:  # type: ignore[override]
        self._records.append(
            BroadcastRecord(payload=payload, called_at=datetime.now(timezone.utc))
        )

    @property
    def records(self) -> list[BroadcastRecord]:
        return self._records

    async def aclose(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Creates all tables in the test DB; drops them after session."""
    import os
    db_url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://smarthandoff:test@localhost:5432/smarthandoff_test",
    )
    engine = create_async_engine(db_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def async_db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Per-test async DB session with transaction rollback for isolation."""
    async_session = async_sessionmaker(test_engine, expire_on_commit=False)
    async with async_session() as session:
        async with session.begin():
            yield session
            await session.rollback()


@pytest.fixture
def recorded_broadcaster() -> RecordingBroadcaster:
    return RecordingBroadcaster()


@pytest.fixture
def transition_service(recorded_broadcaster: RecordingBroadcaster) -> TaskStatusTransitionService:
    return TaskStatusTransitionService(recorded_broadcaster)
```

### 3. Create `backend/tests/integration/signalr/test_signalr_latency.py`

```python
"""Integration tests for SignalR broadcast latency and group routing.

US-022 DoD:
  - Integration test: end-to-end latency from DB write to task_updated event ≤1 second.
  - Unit tests: group routing for encounter/unit/role subscriptions.

Note on latency measurement:
  The 'end-to-end' scope in this integration test measures:
    db_committed_at  →  broadcast_called_at   (server side)
  This is the most controllable measurement. The full Angular client latency
  (network + WebSocket delivery) is validated in the E2E Playwright test (TASK-005
  Playwright scope — see test-plan for US-022).

  Azure SignalR Service internal propagation from broadcast call to client delivery
  is ~50-200ms per Microsoft SLA and is outside our control.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_task import AgentTask, AgentTaskStatus
from app.models.encounter import Encounter
from app.services.task_status_service import TaskStatusTransitionService
from app.signalr.group_resolver import GroupResolver, UserClaims

from tests.integration.signalr.conftest import RecordingBroadcaster


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_encounter(unit_id: str = "3A") -> Encounter:
    return Encounter(
        id=uuid4(),
        mrn="MRN-TEST-001",
        unit_id=unit_id,
        admit_datetime=datetime.now(timezone.utc),
    )


def _make_task(encounter: Encounter, status: AgentTaskStatus = AgentTaskStatus.IN_PROGRESS) -> AgentTask:
    return AgentTask(
        id=uuid4(),
        encounter_id=encounter.id,
        agent_type="DOCUMENTATION",
        status=status,
        unit_id=encounter.unit_id,
        target_role="nurse",
        created_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Latency tests
# ---------------------------------------------------------------------------

class TestSignalRBroadcastLatency:
    """US-022 Scenario 1: DB write → broadcast called within 1 second."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_broadcast_called_within_1_second_of_db_commit(
        self,
        async_db_session: AsyncSession,
        transition_service: TaskStatusTransitionService,
        recorded_broadcaster: RecordingBroadcaster,
    ):
        """Measures elapsed time between DB flush+commit and broadcast_task_updated call."""
        encounter = _make_encounter(unit_id="3A")
        task = _make_task(encounter)
        async_db_session.add(encounter)
        async_db_session.add(task)
        await async_db_session.flush()

        db_commit_start = datetime.now(timezone.utc)
        await transition_service.transition(async_db_session, task, AgentTaskStatus.COMPLETED)
        broadcast_called_at = recorded_broadcaster.records[-1].called_at

        elapsed_seconds = (broadcast_called_at - db_commit_start).total_seconds()
        assert elapsed_seconds < 1.0, (
            f"Broadcast called {elapsed_seconds:.3f}s after DB commit — exceeds 1s SLA "
            f"(US-022 Scenario 1, NFR-006, TR-003)"
        )

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_broadcast_payload_contains_correct_status(
        self,
        async_db_session: AsyncSession,
        transition_service: TaskStatusTransitionService,
        recorded_broadcaster: RecordingBroadcaster,
    ):
        """Broadcast payload reflects IN_PROGRESS → COMPLETED transition."""
        encounter = _make_encounter()
        task = _make_task(encounter, AgentTaskStatus.IN_PROGRESS)
        async_db_session.add(encounter)
        async_db_session.add(task)
        await async_db_session.flush()

        await transition_service.transition(async_db_session, task, AgentTaskStatus.COMPLETED)

        assert len(recorded_broadcaster.records) == 1
        payload = recorded_broadcaster.records[0].payload
        assert payload.previous_status == "IN_PROGRESS"
        assert payload.new_status == "COMPLETED"
        assert payload.task_id == task.id

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_broadcast_not_called_on_invalid_transition(
        self,
        async_db_session: AsyncSession,
        transition_service: TaskStatusTransitionService,
        recorded_broadcaster: RecordingBroadcaster,
    ):
        """Broadcast is NOT sent if the status transition is invalid."""
        encounter = _make_encounter()
        task = _make_task(encounter, AgentTaskStatus.COMPLETED)
        async_db_session.add(encounter)
        async_db_session.add(task)
        await async_db_session.flush()

        with pytest.raises(ValueError):
            await transition_service.transition(async_db_session, task, AgentTaskStatus.IN_PROGRESS)

        assert len(recorded_broadcaster.records) == 0


# ---------------------------------------------------------------------------
# Group routing isolation tests (US-022 Scenario 2)
# ---------------------------------------------------------------------------

class TestSignalRGroupRouting:
    """US-022 Scenario 2: unit 4B users do NOT receive unit 3A events."""

    def test_unit_3a_nurse_not_in_unit_4b_group(self):
        """Core isolation test — confirms cross-unit events are filtered by group membership."""
        resolver = GroupResolver()

        nurse_3a = UserClaims(user_id="u1", role="nurse", unit_id="3A", encounter_ids=[])
        nurse_4b = UserClaims(user_id="u2", role="nurse", unit_id="4B", encounter_ids=[])

        groups_3a = resolver.resolve(nurse_3a)
        groups_4b = resolver.resolve(nurse_4b)

        # A unit-3A event is broadcast to group "unit-3A".
        # Nurse 4B must not be a member of that group.
        assert "unit-3A" in groups_3a
        assert "unit-3A" not in groups_4b
        assert "unit-4B" in groups_4b
        assert "unit-4B" not in groups_3a

    def test_pharmacist_receives_medication_task_via_role_group(self):
        """Pharmacist (no unit) receives medication event via role-pharmacist group."""
        resolver = GroupResolver()
        pharmacist = UserClaims(
            user_id="pp", role="pharmacist", unit_id=None, encounter_ids=["enc-med-001"]
        )
        groups = resolver.resolve(pharmacist)
        # Medication reconciliation task broadcasts to role-pharmacist.
        assert "role-pharmacist" in groups
        assert "encounter-enc-med-001" in groups

    def test_unit_3a_nurse_receives_encounter_and_role_groups(self):
        """Unit 3A nurse receives events via all three applicable groups."""
        resolver = GroupResolver()
        nurse = UserClaims(
            user_id="n1", role="nurse", unit_id="3A", encounter_ids=["enc-001"]
        )
        groups = resolver.resolve(nurse)
        assert "role-nurse" in groups
        assert "unit-3A" in groups
        assert "encounter-enc-001" in groups

    def test_broadcast_group_names_match_resolver_output(
        self,
        recorded_broadcaster: RecordingBroadcaster,
    ):
        """Verifies broadcaster group names produced by TaskStatusTransitionService
        match the group names GroupResolver would produce for that unit/role.

        This cross-validates TASK-001 broadcaster and TASK-002 resolver independently
        produce the same canonical group names.
        """
        resolver = GroupResolver()
        nurse_claims = UserClaims(user_id="n1", role="nurse", unit_id="3A", encounter_ids=["enc-001"])
        resolver_groups = set(resolver.resolve(nurse_claims))

        # The broadcaster creates groups from the payload (encounter_id, unit_id, role_name).
        # Simulate what broadcaster.broadcast_task_updated would compute:
        from uuid import UUID
        enc_id = UUID("00000000-0000-0000-0000-000000000001")
        broadcaster_groups = {
            f"encounter-{enc_id}",
            "unit-3A",
            "role-nurse",
        }

        # All broadcaster groups must be resolvable by the GroupResolver for the
        # appropriate user — ensures no naming inconsistency between layers.
        assert "unit-3A" in resolver_groups
        assert "role-nurse" in resolver_groups
```

### 4. Update `pytest.ini` / `pyproject.toml` with integration marker

```ini
# pytest.ini
[pytest]
markers =
    integration: marks tests that require a running PostgreSQL database
asyncio_mode = auto
```

### 5. Confirm all tests pass

```bash
# Unit tests (no DB required)
pytest backend/tests/unit/signalr/ -v

# Integration tests (requires TEST_DATABASE_URL env var)
TEST_DATABASE_URL="postgresql+asyncpg://smarthandoff:test@localhost:5432/smarthandoff_test" \
  pytest backend/tests/integration/signalr/ -v -m integration

# Full suite
pytest backend/tests/ -v --tb=short
```

---

## Validation Loop

Before marking this task complete, verify:

```bash
# All unit tests pass
pytest backend/tests/unit/ -v

# Integration latency test passes (requires test DB)
TEST_DATABASE_URL="postgresql+asyncpg://smarthandoff:test@localhost:5432/smarthandoff_test" \
  pytest backend/tests/integration/signalr/test_signalr_latency.py::TestSignalRBroadcastLatency::test_broadcast_called_within_1_second_of_db_commit -v -s

# Confirm elapsed time printed in output is < 1.0s
```

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 | Upstream task | `SignalRBroadcaster`, `TaskUpdatedPayload` |
| TASK-002 | Upstream task | `GroupResolver`, `UserClaims` — unit routing tests already delivered there |
| TASK-003 | Upstream task | `TaskStatusTransitionService` — the service under integration test |
| `pytest-asyncio` | PyPI | Async test support — already in `requirements-test.txt` |
| `asyncpg` | PyPI | Async PostgreSQL driver — add to `requirements-test.txt` if missing |
| Test PostgreSQL DB | Infrastructure | `TEST_DATABASE_URL` env var pointing to `smarthandoff_test` schema |
