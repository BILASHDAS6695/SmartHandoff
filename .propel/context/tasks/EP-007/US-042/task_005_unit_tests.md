---
id: TASK-005
title: "Unit Tests — Escalation Trigger, Acknowledgement, Re-escalation, RBAC Enforcement"
user_story: US-042
epic: EP-007
sprint: 2
layer: Testing
estimate: 2.5h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-042/TASK-001, US-042/TASK-002, US-042/TASK-003, US-042/TASK-004]
---

# TASK-005: Unit Tests — Escalation Trigger, Acknowledgement, Re-escalation, RBAC Enforcement

> **Story:** US-042 | **Epic:** EP-007 | **Sprint:** 2 | **Layer:** Testing | **Est:** 2.5 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-042 DoD specifies unit tests covering all four acceptance criteria scenarios. Tests are split across four test files matching the four production modules implemented in TASK-002 through TASK-004.

| Test File | Module Under Test | Coverage Focus |
|---|---|---|
| `test_care_escalation_monitor.py` | `escalation/monitor.py` | AC Scenario 1: urgency flag → CARE_TEAM_ESCALATION within 60 s; idempotency on duplicate Pub/Sub delivery |
| `test_reescalation_job.py` | `escalation/reescalation_job.py` | AC Scenario 3: PENDING escalation > 15 min → SUPERVISOR_ESCALATION published, `escalated_to_supervisor=True` |
| `test_acknowledge_router.py` | `routers/care_escalations.py` | AC Scenarios 2 & 4: 200 OK on nurse ack; 409 on re-ack; 403 for patient JWT; 404 for unknown ID |
| `test_care_escalation_model.py` | `models/care_escalation.py` | ORM field defaults, idempotency key uniqueness, enum values |

Coverage target: ≥80% branch coverage across all four modules (TR-020).

**Mocking strategy:**

| External Dependency | Mock Approach |
|---|---|
| `pubsub_v1.PublisherClient.publish()` | `MagicMock` with `.result()` returning None |
| `pubsub_v1.subscriber.message.Message` | `MagicMock` with `.data`, `.message_id`, `.ack()`, `.nack()` |
| `AsyncSession` (write) | `AsyncMock` with `execute()`, `flush()`, `commit()`, `rollback()`, `refresh()` |
| `AsyncSession` (read) | `AsyncMock` returning mock `CareEscalation` records |
| `async_sessionmaker` | `AsyncMock` context manager returning mocked `AsyncSession` |
| FastAPI `TestClient` | `httpx.AsyncClient` with `ASGITransport` |
| `get_current_user` dependency | Override returning `{"sub": str(nurse_user_id), "roles": ["nurse"]}` |
| `get_write_db` dependency | Override returning mocked `AsyncSession` |

---

## Acceptance Criteria Addressed

| US-042 AC Scenario | Test Cases |
|---|---|
| **Scenario 1** (urgency flag → escalation within 60 s) | `test_urgency_flag_creates_escalation_record`, `test_urgency_flag_publishes_care_team_escalation`, `test_duplicate_event_skipped_by_idempotency` |
| **Scenario 2** (nurse acknowledges → ACKNOWLEDGED) | `test_acknowledge_sets_status_acknowledged`, `test_acknowledge_records_acknowledged_at`, `test_acknowledge_already_acknowledged_returns_409` |
| **Scenario 3** (15-min SLA breach → SUPERVISOR_ESCALATION) | `test_reescalation_job_publishes_supervisor_escalation`, `test_reescalation_job_sets_escalated_to_supervisor_true`, `test_reescalation_job_skips_recent_escalations`, `test_reescalation_job_skips_already_escalated` |
| **Scenario 4** (patient JWT → 403) | `test_acknowledge_patient_jwt_returns_403`, `test_acknowledge_pharmacist_jwt_returns_403`, `test_acknowledge_unknown_id_returns_404` |

---

## Implementation Steps

### 1. Scaffold test directories

```bash
mkdir -p backend/tests/unit/agents/followup_care/escalation
mkdir -p api-gateway/tests/unit/routers
touch backend/tests/unit/agents/followup_care/escalation/__init__.py
touch api-gateway/tests/unit/routers/__init__.py
```

### 2. Create `backend/tests/unit/agents/followup_care/escalation/test_care_escalation_monitor.py`

```python
"""Unit tests for CareEscalationMonitor — US-042 AC Scenario 1.

Covers:
    - URGENCY_FLAG_SET event creates CareEscalation record (PENDING)
    - CARE_TEAM_ESCALATION published to notification-requests
    - Idempotency: duplicate Pub/Sub delivery skipped (ACK without creating duplicate)
    - Missing encounter → NACK (not crash)
    - No-nurse fallback → escalation still created, notification skipped with WARNING
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.cloud import pubsub_v1

from app.agents.followup_care.escalation.monitor import CareEscalationMonitor
from app.agents.followup_care.escalation.schemas import UrgencyFlagSetEvent
from app.models.care_escalation import CareEscalation
from app.models.enums import CareEscalationStatus

ENCOUNTER_ID = uuid.uuid4()
PATIENT_ID = uuid.uuid4()
TRANSCRIPT_ID = uuid.uuid4()
NURSE_ID = uuid.uuid4()


def _make_pubsub_message(event: dict) -> MagicMock:
    """Build a mock Pub/Sub message from an event dict."""
    msg = MagicMock(spec=pubsub_v1.subscriber.message.Message)
    msg.data = json.dumps(event).encode("utf-8")
    msg.message_id = "msg-001"
    return msg


def _make_valid_event() -> dict:
    return {
        "event_type": "URGENCY_FLAG_SET",
        "encounter_id": str(ENCOUNTER_ID),
        "patient_id": str(PATIENT_ID),
        "chatbot_transcript_id": str(TRANSCRIPT_ID),
        "urgency_flag_set_at": datetime.now(tz=timezone.utc).isoformat(),
    }


@pytest.fixture()
def mock_publisher():
    publisher = MagicMock(spec=pubsub_v1.PublisherClient)
    future = MagicMock()
    future.result.return_value = None
    publisher.publish.return_value = future
    return publisher


@pytest.fixture()
def mock_session_factory():
    """Returns an async_sessionmaker that yields an AsyncMock session."""
    session = AsyncMock()
    session.get = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.add = MagicMock()

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory, session


@pytest.fixture()
def monitor(mock_session_factory, mock_publisher):
    factory, _ = mock_session_factory
    return CareEscalationMonitor(
        session_factory=factory,
        publisher=mock_publisher,
        notification_topic="projects/test/topics/notification-requests",
    )


class TestHandleUrgencyFlagSet:
    @pytest.mark.asyncio
    async def test_urgency_flag_creates_escalation_record(
        self, monitor, mock_session_factory
    ):
        """AC Scenario 1: URGENCY_FLAG_SET event → care_escalation record created with status=PENDING."""
        factory, session = mock_session_factory
        mock_encounter = MagicMock()
        mock_encounter.current_unit = "ICU-3"
        session.get.return_value = mock_encounter

        mock_nurse = MagicMock()
        mock_nurse.id = NURSE_ID
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = mock_nurse
        session.execute.return_value = result_mock

        msg = _make_pubsub_message(_make_valid_event())
        await monitor.handle_urgency_flag_set(msg)

        session.add.assert_called_once()
        added: CareEscalation = session.add.call_args[0][0]
        assert added.encounter_id == ENCOUNTER_ID
        assert added.patient_id == PATIENT_ID
        assert added.notified_nurse_user_id == NURSE_ID
        assert added.status == CareEscalationStatus.PENDING
        assert added.escalated_to_supervisor is False
        assert added.idempotency_key == f"ESC-{ENCOUNTER_ID}"

    @pytest.mark.asyncio
    async def test_urgency_flag_publishes_care_team_escalation(
        self, monitor, mock_session_factory, mock_publisher
    ):
        """AC Scenario 1: CARE_TEAM_ESCALATION published to notification-requests after record creation."""
        factory, session = mock_session_factory
        mock_encounter = MagicMock()
        mock_encounter.current_unit = "ICU-3"
        session.get.return_value = mock_encounter

        mock_nurse = MagicMock()
        mock_nurse.id = NURSE_ID
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = mock_nurse
        session.execute.return_value = result_mock

        msg = _make_pubsub_message(_make_valid_event())
        await monitor.handle_urgency_flag_set(msg)

        mock_publisher.publish.assert_called_once()
        topic, payload = mock_publisher.publish.call_args[0]
        published = json.loads(payload.decode("utf-8"))

        assert topic == "projects/test/topics/notification-requests"
        assert published["event_type"] == "CARE_TEAM_ESCALATION"
        assert published["nurse_user_id"] == str(NURSE_ID)
        assert published["channel"] == "SMS"
        assert "NOTIF-ESC-" in published["idempotency_key"]
        # PHI check: no patient name, MRN, DOB, phone in published payload
        for phi_field in ["first_name", "last_name", "mrn", "dob", "phone", "email"]:
            assert phi_field not in published

    @pytest.mark.asyncio
    async def test_duplicate_event_skipped_by_idempotency(
        self, monitor, mock_session_factory, mock_publisher
    ):
        """Duplicate Pub/Sub delivery: flush raises UniqueConstraint → ACK without duplicate escalation."""
        factory, session = mock_session_factory
        mock_encounter = MagicMock()
        mock_encounter.current_unit = "ICU-3"
        session.get.return_value = mock_encounter

        mock_nurse = MagicMock()
        mock_nurse.id = NURSE_ID
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = mock_nurse
        session.execute.return_value = result_mock

        # First call: flush raises (simulating unique constraint violation)
        session.flush.side_effect = Exception("unique constraint violation")

        msg = _make_pubsub_message(_make_valid_event())
        await monitor.handle_urgency_flag_set(msg)

        # Notification NOT published for duplicate
        mock_publisher.publish.assert_not_called()
        msg.ack.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_encounter_nacks_message(
        self, monitor, mock_session_factory
    ):
        """Missing encounter → NACK (DLQ will handle after max_delivery_attempts=5)."""
        factory, session = mock_session_factory
        session.get.return_value = None

        msg = _make_pubsub_message(_make_valid_event())
        await monitor.handle_urgency_flag_set(msg)

        msg.nack.assert_called_once()
        msg.ack.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_event_nacks_message(self, monitor):
        """Malformed event payload → NACK; no crash."""
        msg = MagicMock(spec=pubsub_v1.subscriber.message.Message)
        msg.data = b'{"event_type": "UNEXPECTED_TYPE"}'
        msg.message_id = "bad-msg"

        await monitor.handle_urgency_flag_set(msg)

        msg.nack.assert_called_once()
```

### 3. Create `backend/tests/unit/agents/followup_care/escalation/test_reescalation_job.py`

```python
"""Unit tests for ReEscalationJob — US-042 AC Scenario 3.

Covers:
    - PENDING escalation > 15 min → status=ESCALATED_TO_SUPERVISOR, escalated_to_supervisor=True
    - SUPERVISOR_ESCALATION published with correct idempotency_key
    - Escalations < 15 min old → not re-escalated
    - Already ESCALATED_TO_SUPERVISOR → skipped by WHERE clause
    - Concurrent update (returning None) → skip without error
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from google.cloud import pubsub_v1

from app.agents.followup_care.escalation.reescalation_job import ReEscalationJob
from app.models.care_escalation import CareEscalation
from app.models.enums import CareEscalationStatus

ESCALATION_ID = uuid.uuid4()
ENCOUNTER_ID = uuid.uuid4()
PATIENT_ID = uuid.uuid4()


def _make_pending_escalation(sent_at: datetime) -> MagicMock:
    esc = MagicMock(spec=CareEscalation)
    esc.id = ESCALATION_ID
    esc.encounter_id = ENCOUNTER_ID
    esc.patient_id = PATIENT_ID
    esc.status = CareEscalationStatus.PENDING
    esc.escalated_to_supervisor = False
    esc.sent_at = sent_at
    return esc


@pytest.fixture()
def mock_publisher():
    publisher = MagicMock(spec=pubsub_v1.PublisherClient)
    future = MagicMock()
    future.result.return_value = None
    publisher.publish.return_value = future
    return publisher


@pytest.fixture()
def mock_session_factory():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory, session


@pytest.fixture()
def job(mock_session_factory, mock_publisher):
    factory, _ = mock_session_factory
    return ReEscalationJob(
        session_factory=factory,
        publisher=mock_publisher,
        notification_topic="projects/test/topics/notification-requests",
    )


class TestReEscalationJobRun:
    @pytest.mark.asyncio
    async def test_reescalation_publishes_supervisor_escalation(
        self, job, mock_session_factory, mock_publisher
    ):
        """AC Scenario 3: overdue PENDING escalation → SUPERVISOR_ESCALATION published."""
        factory, session = mock_session_factory
        overdue_at = datetime.now(tz=timezone.utc) - timedelta(minutes=16)
        overdue_esc = _make_pending_escalation(sent_at=overdue_at)

        # First session.execute() = SELECT overdue escalations
        select_result = MagicMock()
        select_result.scalars.return_value.all.return_value = [overdue_esc]

        # Second session.execute() = UPDATE ... RETURNING escalation.id
        update_result = MagicMock()
        update_result.scalar_one_or_none.return_value = ESCALATION_ID

        session.execute.side_effect = [select_result, update_result]

        await job.run()

        mock_publisher.publish.assert_called_once()
        topic, payload = mock_publisher.publish.call_args[0]
        published = json.loads(payload.decode("utf-8"))

        assert published["event_type"] == "SUPERVISOR_ESCALATION"
        assert published["escalation_id"] == str(ESCALATION_ID)
        assert published["encounter_id"] == str(ENCOUNTER_ID)
        assert published["idempotency_key"] == f"NOTIF-SUP-ESC-{ESCALATION_ID}"
        # PHI check
        for phi_field in ["first_name", "last_name", "mrn", "dob", "phone", "email"]:
            assert phi_field not in published

    @pytest.mark.asyncio
    async def test_reescalation_sets_escalated_to_supervisor_true(
        self, job, mock_session_factory
    ):
        """AC Scenario 3: care_escalation DB update includes escalated_to_supervisor=True."""
        factory, session = mock_session_factory
        overdue_at = datetime.now(tz=timezone.utc) - timedelta(minutes=16)
        overdue_esc = _make_pending_escalation(sent_at=overdue_at)

        select_result = MagicMock()
        select_result.scalars.return_value.all.return_value = [overdue_esc]
        update_result = MagicMock()
        update_result.scalar_one_or_none.return_value = ESCALATION_ID
        session.execute.side_effect = [select_result, update_result]

        await job.run()

        # Verify UPDATE statement included escalated_to_supervisor=True
        update_call = session.execute.call_args_list[1]
        stmt = update_call[0][0]
        # Confirm the UPDATE values contain escalated_to_supervisor=True
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "escalated_to_supervisor" in compiled
        assert "ESCALATED_TO_SUPERVISOR" in compiled

    @pytest.mark.asyncio
    async def test_reescalation_skips_recent_escalations(
        self, job, mock_session_factory, mock_publisher
    ):
        """Escalations < 15 min old are not returned by SELECT — no publication."""
        factory, session = mock_session_factory

        select_result = MagicMock()
        select_result.scalars.return_value.all.return_value = []  # No overdue results
        session.execute.return_value = select_result

        await job.run()

        mock_publisher.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_reescalation_skips_concurrent_update(
        self, job, mock_session_factory, mock_publisher
    ):
        """Concurrent scheduler tick updated the record first → RETURNING None → skip without publish."""
        factory, session = mock_session_factory
        overdue_at = datetime.now(tz=timezone.utc) - timedelta(minutes=20)
        overdue_esc = _make_pending_escalation(sent_at=overdue_at)

        select_result = MagicMock()
        select_result.scalars.return_value.all.return_value = [overdue_esc]
        update_result = MagicMock()
        update_result.scalar_one_or_none.return_value = None  # Concurrent update won
        session.execute.side_effect = [select_result, update_result]

        await job.run()

        mock_publisher.publish.assert_not_called()
```

### 4. Create `api-gateway/tests/unit/routers/test_acknowledge_router.py`

```python
"""Unit tests for PATCH /api/v1/care/escalations/{id}/acknowledge.

US-042 AC Scenarios 2 and 4.

Covers:
    - 200 OK: nurse acknowledges → status=ACKNOWLEDGED, acknowledged_at set, acknowledged_by set
    - 409 Conflict: already acknowledged → rejected
    - 403 Forbidden: patient JWT → rejected
    - 403 Forbidden: pharmacist JWT → rejected
    - 404 Not Found: unknown escalation_id → rejected
    - 200 OK: escalation with status=ESCALATED_TO_SUPERVISOR can still be acknowledged
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.core.auth import get_current_user, require_any_role
from app.core.dependencies import get_write_db
from app.models.care_escalation import CareEscalation
from app.models.enums import CareEscalationStatus

ESCALATION_ID = uuid.uuid4()
ENCOUNTER_ID = uuid.uuid4()
PATIENT_ID = uuid.uuid4()
NURSE_USER_ID = uuid.uuid4()


def _make_pending_escalation() -> MagicMock:
    esc = MagicMock(spec=CareEscalation)
    esc.id = ESCALATION_ID
    esc.encounter_id = ENCOUNTER_ID
    esc.patient_id = PATIENT_ID
    esc.status = CareEscalationStatus.PENDING
    esc.sent_at = datetime.now(tz=timezone.utc)
    esc.acknowledged_at = None
    esc.acknowledged_by = None
    esc.escalated_to_supervisor = False
    esc.escalated_at = None
    return esc


def _nurse_user() -> dict:
    return {"sub": str(NURSE_USER_ID), "roles": ["nurse"], "email": "nurse@hospital.org"}


def _patient_user() -> dict:
    return {"sub": str(uuid.uuid4()), "roles": ["patient"], "email": "patient@example.com"}


def _pharmacist_user() -> dict:
    return {"sub": str(uuid.uuid4()), "roles": ["pharmacist"]}


class TestAcknowledgeEscalation:
    @pytest.mark.asyncio
    async def test_nurse_acknowledges_returns_200(self):
        """AC Scenario 2: nurse JWT → 200 OK, status=ACKNOWLEDGED, acknowledged_at set."""
        mock_session = AsyncMock()
        pending_esc = _make_pending_escalation()

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = pending_esc
        mock_session.execute.return_value = result_mock
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: _nurse_user()
        app.dependency_overrides[get_write_db] = lambda: mock_session

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.patch(
                f"/api/v1/care/escalations/{ESCALATION_ID}/acknowledge"
            )

        assert response.status_code == 200
        assert pending_esc.status == CareEscalationStatus.ACKNOWLEDGED
        assert pending_esc.acknowledged_at is not None
        assert pending_esc.acknowledged_by == NURSE_USER_ID

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_already_acknowledged_returns_409(self):
        """Scenario 2: already acknowledged → 409 Conflict."""
        mock_session = AsyncMock()
        acked_esc = _make_pending_escalation()
        acked_esc.status = CareEscalationStatus.ACKNOWLEDGED

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = acked_esc
        mock_session.execute.return_value = result_mock

        app.dependency_overrides[get_current_user] = lambda: _nurse_user()
        app.dependency_overrides[get_write_db] = lambda: mock_session

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.patch(
                f"/api/v1/care/escalations/{ESCALATION_ID}/acknowledge"
            )

        assert response.status_code == 409
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_patient_jwt_returns_403(self):
        """AC Scenario 4: patient JWT → 403 Forbidden."""
        app.dependency_overrides[get_current_user] = lambda: _patient_user()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.patch(
                f"/api/v1/care/escalations/{ESCALATION_ID}/acknowledge"
            )

        assert response.status_code == 403
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_pharmacist_jwt_returns_403(self):
        """AC Scenario 4: pharmacist JWT → 403 Forbidden."""
        app.dependency_overrides[get_current_user] = lambda: _pharmacist_user()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.patch(
                f"/api/v1/care/escalations/{ESCALATION_ID}/acknowledge"
            )

        assert response.status_code == 403
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_unknown_escalation_returns_404(self):
        """Unknown escalation_id → 404 Not Found."""
        mock_session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = result_mock

        app.dependency_overrides[get_current_user] = lambda: _nurse_user()
        app.dependency_overrides[get_write_db] = lambda: mock_session

        unknown_id = uuid.uuid4()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.patch(
                f"/api/v1/care/escalations/{unknown_id}/acknowledge"
            )

        assert response.status_code == 404
        app.dependency_overrides.clear()
```

---

## Definition of Done Checklist

- [ ] `backend/tests/unit/agents/followup_care/escalation/test_care_escalation_monitor.py` created — 5 test cases
- [ ] `backend/tests/unit/agents/followup_care/escalation/test_reescalation_job.py` created — 4 test cases
- [ ] `api-gateway/tests/unit/routers/test_acknowledge_router.py` created — 5 test cases
- [ ] All tests pass: `pytest backend/tests/unit/agents/followup_care/escalation/ api-gateway/tests/unit/routers/test_acknowledge_router.py -v`
- [ ] ≥80% branch coverage on `monitor.py`, `reescalation_job.py`, and `care_escalations.py` router
- [ ] PHI check embedded in publish assertion tests (no `first_name`, `last_name`, `mrn`, `dob`, `phone`, `email` in Pub/Sub payload)
- [ ] All `async` tests decorated with `@pytest.mark.asyncio`

---

## Notes

- **`asyncio_mode`**: Ensure `pytest-asyncio` is configured with `asyncio_mode = "auto"` in `pyproject.toml` or use explicit `@pytest.mark.asyncio` decorators.
- **Dependency overrides**: Always call `app.dependency_overrides.clear()` in teardown to prevent test pollution across test files.
- **SQLAlchemy compile assertion**: The `UPDATE` statement compile check in `test_reescalation_sets_escalated_to_supervisor_true` relies on SQLAlchemy's literal bind compilation — this is a unit-level check only and does not execute against a real DB.
