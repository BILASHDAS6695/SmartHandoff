---
id: TASK-006
title: "Write Unit Tests and Performance Test for `TransitionCoordinatorAgent` — p95 <2 s under 50 Concurrent ADT Events"
user_story: US-020
epic: EP-003
sprint: 2
layer: Testing
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-020/TASK-001, US-020/TASK-002, US-020/TASK-003]
---

# TASK-006: Write Unit Tests and Performance Test for `TransitionCoordinatorAgent` — p95 <2 s under 50 Concurrent ADT Events

> **Story:** US-020 | **Epic:** EP-003 | **Sprint:** 2 | **Layer:** Testing | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-020 DoD mandates:

> *"Performance test: task creation latency p95 <2 seconds under 50 concurrent ADT events"*

This task covers:

1. **Unit tests** — fast, isolated pytest tests for `task_mapping.py`, `TransitionCoordinatorAgent`, `ADTSubscriber`, and SIGTERM handler
2. **Performance test** — `pytest-asyncio` test that fires 50 concurrent `process_event()` calls against a real test PostgreSQL instance and asserts p95 latency <2 s

Test scope explicitly avoids testing real Pub/Sub or Vertex AI — those are integration concerns outside sprint 2 budget.

---

## Acceptance Criteria Addressed

| US-020 AC | Requirement |
|---|---|
| **All Scenarios** | Unit tests cover each acceptance scenario |
| **DoD** | Performance test confirms p95 <2 s under 50 concurrent ADT events |

---

## Implementation Steps

### 1. Scaffold test directory

```
coordinator-agent/
└── tests/
    ├── conftest.py
    ├── unit/
    │   ├── test_task_mapping.py
    │   ├── test_coordinator_agent.py
    │   └── test_adt_subscriber.py
    └── performance/
        └── test_task_creation_latency.py
```

### 2. Create `coordinator-agent/tests/conftest.py`

```python
"""Shared pytest fixtures for coordinator-agent tests.

Provides:
  - ``mock_adt_event``      — minimal valid ADTEvent factory
  - ``mock_db_session``     — AsyncMock session factory (unit tests)
  - ``async_db_session``    — real asyncpg session factory (performance tests)
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# ADTEvent factory
# ---------------------------------------------------------------------------


def _make_adt_event(event_type: str = "ADT^A01") -> MagicMock:
    """Return a minimal MagicMock that satisfies ADTEvent interface."""
    event = MagicMock()
    event.encounter_id = uuid.uuid4()
    event.event_type.value = event_type
    event.event_timestamp = datetime.now(UTC)
    return event


@pytest.fixture
def mock_adt_event():
    return _make_adt_event("ADT^A01")


@pytest.fixture
def mock_transfer_event():
    return _make_adt_event("ADT^A02")


# ---------------------------------------------------------------------------
# Mock DB session (unit tests — no real DB)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db_session():
    """Returns an async_sessionmaker-like callable yielding a mock session."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [("fake-id",)] * 5  # 5 rows inserted
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.begin = MagicMock(return_value=mock_session)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return session_factory


# ---------------------------------------------------------------------------
# Real async DB session (performance tests — requires TEST_DATABASE_URL env)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def async_db_engine():
    import os
    db_url = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test_db")
    engine = create_async_engine(db_url, pool_size=20, max_overflow=30)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def async_db_session(async_db_engine):
    factory = async_sessionmaker(async_db_engine, class_=AsyncSession, expire_on_commit=False)
    return factory
```

### 3. Create `coordinator-agent/tests/unit/test_task_mapping.py`

```python
"""Unit tests for coordinator task type mapping (SC-1, SC-2)."""
import pytest

from app.coordinator.task_mapping import AgentTaskType, get_task_types_for_event


class TestAdmitEventMapping:
    """SC-1: ADT^A01 must create exactly 5 task types."""

    def test_admit_creates_five_tasks(self):
        tasks = get_task_types_for_event("ADT^A01")
        assert len(tasks) == 5

    def test_admit_includes_all_required_task_types(self):
        tasks = get_task_types_for_event("ADT^A01")
        required = {
            AgentTaskType.DOCUMENTATION,
            AgentTaskType.MEDICATION_RECONCILIATION,
            AgentTaskType.BED_MANAGEMENT,
            AgentTaskType.FOLLOW_UP_CARE,
            AgentTaskType.PATIENT_COMMUNICATION,
        }
        assert set(tasks) == required


class TestTransferEventMapping:
    """SC-2: ADT^A02 must NOT include DISCHARGE_SUMMARY."""

    def test_transfer_excludes_discharge_summary(self):
        tasks = get_task_types_for_event("ADT^A02")
        assert AgentTaskType.DISCHARGE_SUMMARY not in tasks

    def test_transfer_includes_bed_management(self):
        tasks = get_task_types_for_event("ADT^A02")
        assert AgentTaskType.BED_MANAGEMENT in tasks

    def test_transfer_includes_transfer_note(self):
        tasks = get_task_types_for_event("ADT^A02")
        assert AgentTaskType.TRANSFER_NOTE in tasks


class TestUnknownEventMapping:
    """Unknown event types return empty list — no tasks, no exception."""

    def test_unknown_event_type_returns_empty(self):
        result = get_task_types_for_event("ADT^A99")
        assert result == []

    def test_empty_string_returns_empty(self):
        result = get_task_types_for_event("")
        assert result == []
```

### 4. Create `coordinator-agent/tests/unit/test_coordinator_agent.py`

```python
"""Unit tests for TransitionCoordinatorAgent (SC-1, SC-2, SC-3, SC-4)."""
import pytest
import pytest_asyncio

from app.coordinator.agent import TransitionCoordinatorAgent


@pytest.mark.asyncio
class TestProcessEventAdmit:
    """SC-1: 5 AgentTask records created for ADT^A01."""

    async def test_returns_five_for_admit(self, mock_adt_event, mock_db_session):
        agent = TransitionCoordinatorAgent(db_session=mock_db_session)
        result = await agent.process_event(mock_adt_event)
        assert result == 5

    async def test_db_execute_called_once(self, mock_adt_event, mock_db_session):
        """Single atomic INSERT for all tasks."""
        agent = TransitionCoordinatorAgent(db_session=mock_db_session)
        await agent.process_event(mock_adt_event)
        # Session execute called exactly once (single batch INSERT)
        session = mock_db_session.return_value.__aenter__.return_value
        assert session.execute.call_count == 1


@pytest.mark.asyncio
class TestProcessEventTransfer:
    """SC-2: Transfer creates only relevant tasks."""

    async def test_transfer_does_not_create_discharge_summary(
        self, mock_transfer_event, mock_db_session
    ):
        mock_db_session.return_value.__aenter__.return_value.execute.return_value.fetchall.return_value = [
            ("id",), ("id",)
        ]
        agent = TransitionCoordinatorAgent(db_session=mock_db_session)
        result = await agent.process_event(mock_transfer_event)
        assert result == 2  # TRANSFER_NOTE + BED_MANAGEMENT only


@pytest.mark.asyncio
class TestIdempotency:
    """SC-4: Redelivered messages return 0 (ON CONFLICT DO NOTHING)."""

    async def test_idempotent_replay_returns_zero(self, mock_adt_event, mock_db_session):
        mock_db_session.return_value.__aenter__.return_value.execute.return_value.fetchall.return_value = []
        agent = TransitionCoordinatorAgent(db_session=mock_db_session)
        result = await agent.process_event(mock_adt_event)
        assert result == 0


@pytest.mark.asyncio
class TestUnknownEventType:
    """Unknown event type returns 0 without touching DB."""

    async def test_unknown_event_skips_db(self, mock_db_session):
        from unittest.mock import MagicMock
        event = MagicMock()
        event.encounter_id = __import__("uuid").uuid4()
        event.event_type.value = "ADT^A99"

        agent = TransitionCoordinatorAgent(db_session=mock_db_session)
        result = await agent.process_event(event)
        assert result == 0
        session = mock_db_session.return_value.__aenter__.return_value
        session.execute.assert_not_called()
```

### 5. Create `coordinator-agent/tests/unit/test_adt_subscriber.py`

```python
"""Unit tests for ADTSubscriber — shutdown_event and _deserialise_message."""
import asyncio
import json
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio

from app.pubsub.adt_subscriber import _deserialise_message


class TestDeserialiseMessage:
    """_deserialise_message must convert valid Pub/Sub bytes to ADTEvent."""

    def test_raises_on_invalid_json(self):
        msg = MagicMock()
        msg.data = b"not-json"
        with pytest.raises(ValueError, match="Cannot deserialise"):
            with patch("app.models.adt_event.ADTEvent"):
                _deserialise_message(msg)

    def test_raises_on_non_utf8(self):
        msg = MagicMock()
        msg.data = bytes([0xFF, 0xFE])  # invalid UTF-8
        with pytest.raises(ValueError, match="Cannot deserialise"):
            _deserialise_message(msg)


class TestShutdownEvent:
    """shutdown_event must be an asyncio.Event."""

    def test_shutdown_event_is_asyncio_event(self):
        from unittest.mock import AsyncMock
        from app.pubsub.adt_subscriber import ADTSubscriber

        sub = ADTSubscriber(callback=AsyncMock())
        assert isinstance(sub.shutdown_event, asyncio.Event)
        assert not sub.shutdown_event.is_set()

    def test_setting_shutdown_event(self):
        from unittest.mock import AsyncMock
        from app.pubsub.adt_subscriber import ADTSubscriber

        sub = ADTSubscriber(callback=AsyncMock())
        sub.shutdown_event.set()
        assert sub.shutdown_event.is_set()
```

### 6. Create `coordinator-agent/tests/performance/test_task_creation_latency.py`

```python
"""Performance test: task creation p95 < 2 s under 50 concurrent ADT events.

Requires:
  - TEST_DATABASE_URL env var pointing to a PostgreSQL test database
  - ``agent_task`` table created via Alembic migrations

Run with:
    pytest tests/performance/ -v -s --timeout=120
"""
from __future__ import annotations

import asyncio
import statistics
import time
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from app.coordinator.agent import TransitionCoordinatorAgent


def _make_admit_event() -> MagicMock:
    event = MagicMock()
    event.encounter_id = uuid.uuid4()
    event.event_type.value = "ADT^A01"
    event.event_timestamp = datetime.now(UTC)
    return event


@pytest.mark.asyncio
@pytest.mark.performance
async def test_task_creation_p95_under_2_seconds(async_db_session):
    """50 concurrent ADT^A01 events; p95 task creation latency must be <2 s."""
    coordinator = TransitionCoordinatorAgent(db_session=async_db_session)
    events = [_make_admit_event() for _ in range(50)]

    async def timed_process(event: MagicMock) -> float:
        start = time.monotonic()
        await coordinator.process_event(event)
        return time.monotonic() - start

    # Fire all 50 events concurrently
    latencies: list[float] = await asyncio.gather(
        *[timed_process(e) for e in events]
    )

    latencies_sorted = sorted(latencies)
    p95_index = int(len(latencies_sorted) * 0.95) - 1
    p95_latency = latencies_sorted[p95_index]
    p50_latency = statistics.median(latencies_sorted)

    print(f"\nTask creation latency (50 concurrent ADT events):")
    print(f"  p50: {p50_latency:.3f}s")
    print(f"  p95: {p95_latency:.3f}s")
    print(f"  max: {max(latencies_sorted):.3f}s")

    assert p95_latency < 2.0, (
        f"p95 task creation latency {p95_latency:.3f}s exceeds 2.0s SLA (FR-004)"
    )
```

---

## Validation

Run from `coordinator-agent/`:

```bash
# Unit tests (no DB required)
pytest tests/unit/ -v

# Performance tests (requires TEST_DATABASE_URL)
export TEST_DATABASE_URL="postgresql+asyncpg://test:test@localhost/coordinator_test"
pytest tests/performance/ -v -s -m performance --timeout=120
```

Expected output:
```
tests/unit/test_task_mapping.py::TestAdmitEventMapping::test_admit_creates_five_tasks PASSED
tests/unit/test_task_mapping.py::TestTransferEventMapping::test_transfer_excludes_discharge_summary PASSED
...
tests/performance/test_task_creation_latency.py::test_task_creation_p95_under_2_seconds
  Task creation latency (50 concurrent ADT events):
    p50: 0.041s
    p95: 0.089s  ← must be < 2.0s
    max: 0.112s
PASSED
```

---

## Files Created / Modified

| Action | Path |
|--------|------|
| CREATE | `coordinator-agent/tests/conftest.py` |
| CREATE | `coordinator-agent/tests/unit/test_task_mapping.py` |
| CREATE | `coordinator-agent/tests/unit/test_coordinator_agent.py` |
| CREATE | `coordinator-agent/tests/unit/test_adt_subscriber.py` |
| CREATE | `coordinator-agent/tests/performance/test_task_creation_latency.py` |

---

## Definition of Done Checklist

- [ ] All unit tests in `tests/unit/` pass with `pytest tests/unit/ -v`
- [ ] `test_admit_creates_five_tasks` confirms exactly 5 task types for ADT^A01
- [ ] `test_transfer_excludes_discharge_summary` confirms SC-2 routing
- [ ] `test_idempotent_replay_returns_zero` confirms ON CONFLICT DO NOTHING
- [ ] `test_setting_shutdown_event` confirms `asyncio.Event` is used for SIGTERM
- [ ] Performance test `p95_latency < 2.0` assertion passes against test DB
- [ ] No real Pub/Sub or Vertex AI calls in unit tests (all mocked)
- [ ] Performance test output logged with p50, p95, max values for CI evidence
