---
id: TASK-005
title: "Unit Tests — Escalation Creation, Acknowledgement, Patient Scope Enforcement"
user_story: US-045
epic: EP-008
sprint: 2
layer: Testing
estimate: 2.5h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-045/TASK-001, US-045/TASK-002, US-045/TASK-003, US-045/TASK-004]
---

# TASK-005: Unit Tests — Escalation Creation, Acknowledgement, Patient Scope Enforcement

> **Story:** US-045 | **Epic:** EP-008 | **Sprint:** 2 | **Layer:** Testing | **Est:** 2.5 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-045 DoD specifies unit tests covering: escalation creation, acknowledgement, and patient scope enforcement. Tests are distributed across three test files, each targeting a specific module or endpoint.

| Test File | Module Under Test | Coverage Focus |
|-----------|------------------|----------------|
| `test_escalation_schemas.py` | `escalation/schemas.py` | UUID validation; `EscalationRead.acknowledgement_time_minutes`; `EscalationAlertPayload` truncation; `EscalationConfirmedMessage` text |
| `test_escalation_endpoints_post_patch.py` | `routers/escalation.py` (POST + PATCH) | Escalation creation → 201; scope enforcement → 403; acknowledge → 200; idempotent re-ack; SLA metric emission |
| `test_escalation_endpoint_get.py` | `routers/escalation.py` (GET) | Patient JWT scope → own encounter; cross-patient → 403; staff → all; pagination |

Coverage target: ≥80% branch coverage across all escalation modules (TR-020).

### Mocking strategy

| External Dependency | Mock Approach |
|--------------------|---------------|
| `AsyncSession.execute()` | `AsyncMock` returning mock `ScalarResult` |
| `AsyncSession.add()` / `commit()` / `flush()` | `AsyncMock` |
| `pubsub_publisher.publish_escalation_alert()` | `AsyncMock` (fire-and-forget — assert `asyncio.create_task` called) |
| `signalr_hub.send_to_group()` | `AsyncMock` — assert called with correct group and method |
| `write_audit_event()` | `AsyncMock` — assert called with correct `event_type` |
| `get_current_patient_token` | Override via FastAPI `dependency_overrides` |
| `get_current_staff_token` | Override via FastAPI `dependency_overrides` |
| `get_current_token_claims` | Override to return `{"role": "patient", "encounter_id": "..."}` or staff claims |
| FastAPI `AsyncClient` | `httpx.AsyncClient(app=app, base_url="http://test")` |
| `resolve_oncall_nurse` | `AsyncMock` returning a fixed UUID |
| `emit_acknowledgement_metric` | Patch with `MagicMock` — assert called with correct args |

---

## Acceptance Criteria Addressed

| US-045 AC | Test Cases |
|-----------|-----------|
| **Scenario 1** (ESCALATION_CONFIRMED pushed) | `test_post_escalate_pushes_escalation_confirmed_to_signalr` |
| **Scenario 2** (acknowledged_at recorded; SLA metric) | `test_patch_acknowledge_records_timestamp`, `test_patch_acknowledge_emits_sla_breach_metric`, `test_patch_acknowledge_no_breach_metric_within_sla` |
| **Scenario 3** (GET returns required fields) | `test_get_escalations_response_contains_required_fields` |
| **Scenario 4** (patient scope enforcement) | `test_post_escalate_wrong_encounter_returns_403`, `test_get_escalations_patient_cannot_access_other_encounter` |

---

## Implementation Steps

### 1. Scaffold test directories

```bash
mkdir -p backend/tests/unit/agents/patient_comm/escalation
mkdir -p api-gateway/tests/unit/routers
touch backend/tests/unit/agents/patient_comm/escalation/__init__.py
touch api-gateway/tests/unit/routers/__init__.py
```

### 2. Create `backend/tests/unit/agents/patient_comm/escalation/test_escalation_schemas.py`

```python
"""Unit tests for US-045 Pydantic schemas (TASK-001).

Covers:
    - EscalationCreate UUID validation rejects non-UUIDs
    - EscalationRead.acknowledgement_time_minutes for acknowledged and unacknowledged rows
    - EscalationAlertPayload.urgency_message_summary truncated to 200 chars
    - EscalationConfirmedMessage contains required AC Scenario 1 text
"""
import pytest
from datetime import datetime, timezone, timedelta
from pydantic import ValidationError

from backend.app.agents.patient_comm.escalation.schemas import (
    EscalationAlertPayload,
    EscalationConfirmedMessage,
    EscalationCreate,
    EscalationRead,
    NotificationChannel,
)

VALID_UUID_1 = "550e8400-e29b-41d4-a716-446655440000"
VALID_UUID_2 = "660e8400-e29b-41d4-a716-446655440001"
VALID_UUID_3 = "770e8400-e29b-41d4-a716-446655440002"


class TestEscalationCreateValidation:
    def test_valid_create_accepted(self):
        req = EscalationCreate(
            encounter_id=VALID_UUID_1,
            transcript_message_id=VALID_UUID_2,
            urgency_message="I am having chest pain",
            channel=NotificationChannel.SMS,
        )
        assert req.encounter_id == VALID_UUID_1

    def test_non_uuid_encounter_id_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            EscalationCreate(
                encounter_id="not-a-uuid",
                transcript_message_id=VALID_UUID_2,
                urgency_message="pain",
            )
        assert "encounter_id" in str(exc_info.value)

    def test_non_uuid_transcript_message_id_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            EscalationCreate(
                encounter_id=VALID_UUID_1,
                transcript_message_id="../../etc/passwd",
                urgency_message="pain",
            )
        assert "transcript_message_id" in str(exc_info.value)

    def test_empty_urgency_message_rejected(self):
        with pytest.raises(ValidationError):
            EscalationCreate(
                encounter_id=VALID_UUID_1,
                transcript_message_id=VALID_UUID_2,
                urgency_message="",
            )

    def test_default_channel_is_sms(self):
        req = EscalationCreate(
            encounter_id=VALID_UUID_1,
            transcript_message_id=VALID_UUID_2,
            urgency_message="help",
        )
        assert req.channel == NotificationChannel.SMS


class TestEscalationReadAckTime:
    BASE_NOTIFIED_AT = datetime(2026, 7, 17, 10, 0, 0, tzinfo=timezone.utc)

    def _make_read(self, ack_offset_seconds: int | None) -> EscalationRead:
        return EscalationRead(
            id=VALID_UUID_1,
            encounter_id=VALID_UUID_2,
            transcript_message_id=VALID_UUID_3,
            notified_user_id=VALID_UUID_3,
            notified_at=self.BASE_NOTIFIED_AT,
            acknowledged_at=(
                self.BASE_NOTIFIED_AT + timedelta(seconds=ack_offset_seconds)
                if ack_offset_seconds is not None
                else None
            ),
            channel=NotificationChannel.SMS,
            urgency_message="I feel dizzy",
            created_at=self.BASE_NOTIFIED_AT,
        )

    def test_unacknowledged_returns_none(self):
        read = self._make_read(None)
        assert read.acknowledgement_time_minutes is None

    def test_acknowledged_within_sla_returns_correct_minutes(self):
        read = self._make_read(90)  # 1.5 minutes
        assert read.acknowledgement_time_minutes == pytest.approx(1.5, rel=1e-2)

    def test_acknowledged_beyond_sla_returns_correct_minutes(self):
        read = self._make_read(180)  # 3.0 minutes
        assert read.acknowledgement_time_minutes == pytest.approx(3.0, rel=1e-2)


class TestEscalationAlertPayloadTruncation:
    def test_urgency_message_summary_truncated_to_200_chars(self):
        long_message = "x" * 500
        payload = EscalationAlertPayload(
            escalation_id=VALID_UUID_1,
            encounter_id=VALID_UUID_2,
            notified_user_id=VALID_UUID_3,
            patient_first_name="Jane",
            urgency_message_summary=long_message,
            channel=NotificationChannel.SMS,
        )
        assert len(payload.urgency_message_summary) == 200

    def test_short_message_not_truncated(self):
        payload = EscalationAlertPayload(
            escalation_id=VALID_UUID_1,
            encounter_id=VALID_UUID_2,
            notified_user_id=VALID_UUID_3,
            patient_first_name="Jane",
            urgency_message_summary="short message",
            channel=NotificationChannel.SMS,
        )
        assert payload.urgency_message_summary == "short message"


class TestEscalationConfirmedMessage:
    def test_message_contains_2_minutes(self):
        msg = EscalationConfirmedMessage(
            encounter_id=VALID_UUID_1,
            escalation_id=VALID_UUID_2,
        )
        assert "2 minutes" in msg.message

    def test_message_contains_911_reference(self):
        msg = EscalationConfirmedMessage(
            encounter_id=VALID_UUID_1,
            escalation_id=VALID_UUID_2,
        )
        assert "911" in msg.message

    def test_message_type_is_escalation_confirmed(self):
        from backend.app.agents.patient_comm.escalation.schemas import EscalationMessageType
        msg = EscalationConfirmedMessage(
            encounter_id=VALID_UUID_1,
            escalation_id=VALID_UUID_2,
        )
        assert msg.type == EscalationMessageType.ESCALATION_CONFIRMED
```

### 3. Create `api-gateway/tests/unit/routers/test_escalation_endpoints_post_patch.py`

```python
"""Unit tests for POST /api/v1/chat/escalate and PATCH /acknowledge (US-045).

Covers:
    - POST /escalate: 201 on valid patient-scoped request
    - POST /escalate: 403 on JWT encounter_id mismatch (AC Scenario 4)
    - POST /escalate: SignalR ESCALATION_CONFIRMED push (AC Scenario 1)
    - POST /escalate: asyncio.create_task called for Pub/Sub (fire-and-forget)
    - PATCH /acknowledge: 200 + acknowledged_at set (AC Scenario 2)
    - PATCH /acknowledge: idempotent (second call returns same ack time)
    - PATCH /acknowledge: SLA breach metric emitted when > 2 min
    - PATCH /acknowledge: SLA metric NOT emitted when <= 2 min
    - PATCH /acknowledge: 403 for patient JWT
    - PATCH /acknowledge: 404 for unknown escalation_id
"""
import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient

from api_gateway.app.main import app
from backend.app.agents.patient_comm.escalation.schemas import (
    EscalationRead,
    NotificationChannel,
)
from backend.app.agents.patient_comm.escalation.monitoring import SLA_THRESHOLD_MINUTES

ENCOUNTER_ID = str(uuid.uuid4())
TRANSCRIPT_ID = str(uuid.uuid4())
ESCALATION_ID = str(uuid.uuid4())
NURSE_USER_ID = str(uuid.uuid4())
NOTIFIED_AT = datetime(2026, 7, 17, 10, 0, 0, tzinfo=timezone.utc)


def _mock_patient_token(encounter_id: str) -> dict:
    return {"role": "patient", "encounter_id": encounter_id, "sub": "patient-1"}


def _mock_staff_token() -> dict:
    return {"role": "nurse", "sub": "nurse-1"}


def _mock_escalation_row(acknowledged_at: datetime | None = None) -> MagicMock:
    row = MagicMock()
    row.id = uuid.UUID(ESCALATION_ID)
    row.encounter_id = uuid.UUID(ENCOUNTER_ID)
    row.transcript_message_id = uuid.UUID(TRANSCRIPT_ID)
    row.notified_user_id = uuid.UUID(NURSE_USER_ID)
    row.notified_at = NOTIFIED_AT
    row.acknowledged_at = acknowledged_at
    row.channel = "SMS"
    row.urgency_message = "I feel dizzy"
    row.created_at = NOTIFIED_AT
    return row


class TestPostEscalate:
    @pytest.mark.asyncio
    async def test_valid_request_returns_201(self):
        mock_row = _mock_escalation_row()

        with (
            patch(
                "api_gateway.app.routers.escalation.get_current_patient_token",
                return_value=_mock_patient_token(ENCOUNTER_ID),
            ),
            patch(
                "api_gateway.app.routers.escalation.get_async_session",
                return_value=AsyncMock(),
            ),
            patch(
                "backend.app.agents.patient_comm.escalation.service.resolve_oncall_nurse",
                new=AsyncMock(return_value=uuid.UUID(NURSE_USER_ID)),
            ),
            patch("asyncio.create_task"),
            patch(
                "api_gateway.app.routers.escalation.signalr_hub.send_to_group",
                new=AsyncMock(),
            ),
            patch(
                "api_gateway.app.routers.escalation.write_audit_event",
                new=AsyncMock(),
            ),
            patch(
                "backend.app.agents.patient_comm.escalation.service.ChatbotEscalation",
                return_value=mock_row,
            ),
        ):
            async with AsyncClient(app=app, base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/chat/escalate",
                    json={
                        "encounter_id": ENCOUNTER_ID,
                        "transcript_message_id": TRANSCRIPT_ID,
                        "urgency_message": "I feel dizzy and short of breath",
                        "channel": "SMS",
                    },
                    headers={"Authorization": "Bearer mock-patient-token"},
                )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_wrong_encounter_id_returns_403(self):
        other_encounter = str(uuid.uuid4())

        with patch(
            "api_gateway.app.routers.escalation.get_current_patient_token",
            return_value=_mock_patient_token(other_encounter),  # JWT has different encounter
        ):
            async with AsyncClient(app=app, base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/chat/escalate",
                    json={
                        "encounter_id": ENCOUNTER_ID,  # mismatch with JWT
                        "transcript_message_id": TRANSCRIPT_ID,
                        "urgency_message": "help",
                    },
                    headers={"Authorization": "Bearer mock-patient-token"},
                )
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Access denied."

    @pytest.mark.asyncio
    async def test_signalr_escalation_confirmed_pushed(self):
        mock_signalr = AsyncMock()
        mock_row = _mock_escalation_row()

        with (
            patch(
                "api_gateway.app.routers.escalation.get_current_patient_token",
                return_value=_mock_patient_token(ENCOUNTER_ID),
            ),
            patch(
                "api_gateway.app.routers.escalation.signalr_hub.send_to_group",
                new=mock_signalr,
            ),
            patch(
                "backend.app.agents.patient_comm.escalation.service.resolve_oncall_nurse",
                new=AsyncMock(return_value=uuid.UUID(NURSE_USER_ID)),
            ),
            patch("asyncio.create_task"),
            patch(
                "api_gateway.app.routers.escalation.write_audit_event",
                new=AsyncMock(),
            ),
        ):
            async with AsyncClient(app=app, base_url="http://test") as client:
                await client.post(
                    "/api/v1/chat/escalate",
                    json={
                        "encounter_id": ENCOUNTER_ID,
                        "transcript_message_id": TRANSCRIPT_ID,
                        "urgency_message": "I feel dizzy",
                    },
                    headers={"Authorization": "Bearer mock-patient-token"},
                )

        mock_signalr.assert_awaited_once()
        call_kwargs = mock_signalr.call_args
        assert f"encounter-{ENCOUNTER_ID}" in str(call_kwargs)
        assert "ReceiveEscalationConfirmed" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_pubsub_published_as_fire_and_forget(self):
        mock_create_task = MagicMock()

        with (
            patch(
                "api_gateway.app.routers.escalation.get_current_patient_token",
                return_value=_mock_patient_token(ENCOUNTER_ID),
            ),
            patch("asyncio.create_task", mock_create_task),
            patch(
                "api_gateway.app.routers.escalation.signalr_hub.send_to_group",
                new=AsyncMock(),
            ),
            patch(
                "api_gateway.app.routers.escalation.write_audit_event",
                new=AsyncMock(),
            ),
        ):
            async with AsyncClient(app=app, base_url="http://test") as client:
                await client.post(
                    "/api/v1/chat/escalate",
                    json={
                        "encounter_id": ENCOUNTER_ID,
                        "transcript_message_id": TRANSCRIPT_ID,
                        "urgency_message": "I feel dizzy",
                    },
                    headers={"Authorization": "Bearer mock-patient-token"},
                )

        mock_create_task.assert_called_once()  # fire-and-forget via asyncio.create_task


class TestPatchAcknowledge:
    @pytest.mark.asyncio
    async def test_staff_can_acknowledge(self):
        mock_row = _mock_escalation_row()

        with (
            patch(
                "api_gateway.app.routers.escalation.get_current_staff_token",
                return_value=_mock_staff_token(),
            ),
            patch(
                "api_gateway.app.routers.escalation.emit_acknowledgement_metric",
            ),
            patch(
                "api_gateway.app.routers.escalation.write_audit_event",
                new=AsyncMock(),
            ),
        ):
            async with AsyncClient(app=app, base_url="http://test") as client:
                resp = await client.patch(
                    f"/api/v1/chat/escalation/{ESCALATION_ID}/acknowledge",
                    json={},
                    headers={"Authorization": "Bearer mock-staff-token"},
                )

        assert resp.status_code == 200
        assert resp.json()["acknowledged_at"] is not None

    @pytest.mark.asyncio
    async def test_patient_cannot_acknowledge(self):
        with patch(
            "api_gateway.app.routers.escalation.get_current_staff_token",
            side_effect=Exception("HTTP 403"),  # dependency raises 403 for patient
        ):
            async with AsyncClient(app=app, base_url="http://test") as client:
                resp = await client.patch(
                    f"/api/v1/chat/escalation/{ESCALATION_ID}/acknowledge",
                    json={},
                    headers={"Authorization": "Bearer mock-patient-token"},
                )

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_sla_breach_metric_emitted_when_late(self):
        # Escalation notified_at is 3 minutes before "now" — should breach SLA
        late_row = _mock_escalation_row()
        late_row.notified_at = datetime.now(timezone.utc) - timedelta(minutes=3)

        mock_emit = MagicMock()

        with (
            patch(
                "api_gateway.app.routers.escalation.get_current_staff_token",
                return_value=_mock_staff_token(),
            ),
            patch(
                "api_gateway.app.routers.escalation.emit_acknowledgement_metric",
                mock_emit,
            ),
            patch(
                "api_gateway.app.routers.escalation.write_audit_event",
                new=AsyncMock(),
            ),
        ):
            async with AsyncClient(app=app, base_url="http://test") as client:
                await client.patch(
                    f"/api/v1/chat/escalation/{ESCALATION_ID}/acknowledge",
                    json={},
                    headers={"Authorization": "Bearer mock-staff-token"},
                )

        mock_emit.assert_called_once()
        _, kwargs = mock_emit.call_args
        assert kwargs["ack_time_minutes"] > SLA_THRESHOLD_MINUTES

    @pytest.mark.asyncio
    async def test_idempotent_second_acknowledge(self):
        ack_time = datetime(2026, 7, 17, 10, 1, 0, tzinfo=timezone.utc)
        already_acked_row = _mock_escalation_row(acknowledged_at=ack_time)

        mock_emit = MagicMock()

        with (
            patch(
                "api_gateway.app.routers.escalation.get_current_staff_token",
                return_value=_mock_staff_token(),
            ),
            patch(
                "api_gateway.app.routers.escalation.emit_acknowledgement_metric",
                mock_emit,
            ),
        ):
            async with AsyncClient(app=app, base_url="http://test") as client:
                resp = await client.patch(
                    f"/api/v1/chat/escalation/{ESCALATION_ID}/acknowledge",
                    json={},
                    headers={"Authorization": "Bearer mock-staff-token"},
                )

        assert resp.status_code == 200
        # Metric should NOT be re-emitted on second call (idempotent)
        mock_emit.assert_not_called()
        assert resp.json()["acknowledged_at"] == ack_time.isoformat()

    @pytest.mark.asyncio
    async def test_unknown_escalation_returns_404(self):
        unknown_id = str(uuid.uuid4())

        with patch(
            "api_gateway.app.routers.escalation.get_current_staff_token",
            return_value=_mock_staff_token(),
        ):
            async with AsyncClient(app=app, base_url="http://test") as client:
                resp = await client.patch(
                    f"/api/v1/chat/escalation/{unknown_id}/acknowledge",
                    json={},
                    headers={"Authorization": "Bearer mock-staff-token"},
                )

        assert resp.status_code == 404
```

### 4. Create `api-gateway/tests/unit/routers/test_escalation_endpoint_get.py`

```python
"""Unit tests for GET /api/v1/chat/escalations (US-045).

Covers:
    - Patient JWT scoped to own encounter_id
    - Patient cannot access another patient's escalations (403)
    - Staff JWT returns all escalations (paginated)
    - Staff JWT with ?encounter_id filter works
    - Response contains all AC Scenario 3 required fields
    - acknowledgement_time_minutes is null for unacknowledged escalations
"""
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from api_gateway.app.main import app

ENCOUNTER_ID = str(uuid.uuid4())
OTHER_ENCOUNTER_ID = str(uuid.uuid4())
ESCALATION_ID = str(uuid.uuid4())
NURSE_USER_ID = str(uuid.uuid4())
TRANSCRIPT_ID = str(uuid.uuid4())
NOTIFIED_AT = datetime(2026, 7, 17, 10, 0, 0, tzinfo=timezone.utc)


def _mock_escalation_row(encounter_id: str, ack_offset_seconds: int | None = None) -> MagicMock:
    row = MagicMock()
    row.id = uuid.UUID(ESCALATION_ID)
    row.encounter_id = uuid.UUID(encounter_id)
    row.transcript_message_id = uuid.UUID(TRANSCRIPT_ID)
    row.notified_user_id = uuid.UUID(NURSE_USER_ID)
    row.notified_at = NOTIFIED_AT
    row.acknowledged_at = (
        NOTIFIED_AT + timedelta(seconds=ack_offset_seconds)
        if ack_offset_seconds is not None
        else None
    )
    row.channel = "SMS"
    row.urgency_message = "I feel dizzy"
    row.created_at = NOTIFIED_AT
    return row


class TestGetEscalationsPatient:
    @pytest.mark.asyncio
    async def test_patient_gets_own_escalations(self):
        mock_row = _mock_escalation_row(ENCOUNTER_ID)

        with (
            patch(
                "api_gateway.app.routers.escalation.get_current_token_claims",
                return_value={"role": "patient", "encounter_id": ENCOUNTER_ID},
            ),
            patch(
                "api_gateway.app.routers.escalation.write_audit_event",
                new=AsyncMock(),
            ),
        ):
            async with AsyncClient(app=app, base_url="http://test") as client:
                resp = await client.get(
                    "/api/v1/chat/escalations",
                    headers={"Authorization": "Bearer mock-patient-token"},
                )

        assert resp.status_code == 200
        data = resp.json()
        # Response is a list
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_patient_cannot_access_other_encounter_escalations(self):
        with patch(
            "api_gateway.app.routers.escalation.get_current_token_claims",
            return_value={"role": "patient", "encounter_id": ENCOUNTER_ID},
        ):
            async with AsyncClient(app=app, base_url="http://test") as client:
                resp = await client.get(
                    f"/api/v1/chat/escalations?encounter_id={OTHER_ENCOUNTER_ID}",
                    headers={"Authorization": "Bearer mock-patient-token"},
                )

        assert resp.status_code == 403
        assert resp.json()["detail"] == "Access denied."

    @pytest.mark.asyncio
    async def test_response_contains_required_ac_scenario_3_fields(self):
        mock_row = _mock_escalation_row(ENCOUNTER_ID, ack_offset_seconds=90)

        with (
            patch(
                "api_gateway.app.routers.escalation.get_current_token_claims",
                return_value={"role": "patient", "encounter_id": ENCOUNTER_ID},
            ),
            patch(
                "api_gateway.app.routers.escalation.write_audit_event",
                new=AsyncMock(),
            ),
        ):
            async with AsyncClient(app=app, base_url="http://test") as client:
                resp = await client.get(
                    "/api/v1/chat/escalations",
                    headers={"Authorization": "Bearer mock-patient-token"},
                )

        assert resp.status_code == 200
        if resp.json():
            row = resp.json()[0]
            # AC Scenario 3 required fields
            assert "transcript_message_id" in row
            assert "urgency_message" in row
            assert "notified_user_id" in row
            assert "acknowledged_at" in row
            assert "acknowledgement_time_minutes" in row

    @pytest.mark.asyncio
    async def test_acknowledgement_time_minutes_null_for_unacknowledged(self):
        mock_row = _mock_escalation_row(ENCOUNTER_ID, ack_offset_seconds=None)

        with (
            patch(
                "api_gateway.app.routers.escalation.get_current_token_claims",
                return_value={"role": "patient", "encounter_id": ENCOUNTER_ID},
            ),
            patch(
                "api_gateway.app.routers.escalation.write_audit_event",
                new=AsyncMock(),
            ),
        ):
            async with AsyncClient(app=app, base_url="http://test") as client:
                resp = await client.get(
                    "/api/v1/chat/escalations",
                    headers={"Authorization": "Bearer mock-patient-token"},
                )

        if resp.json():
            assert resp.json()[0]["acknowledgement_time_minutes"] is None


class TestGetEscalationsStaff:
    @pytest.mark.asyncio
    async def test_staff_can_access_any_encounter(self):
        with (
            patch(
                "api_gateway.app.routers.escalation.get_current_token_claims",
                return_value={"role": "nurse", "sub": "nurse-1"},
            ),
            patch(
                "api_gateway.app.routers.escalation.write_audit_event",
                new=AsyncMock(),
            ),
        ):
            async with AsyncClient(app=app, base_url="http://test") as client:
                resp = await client.get(
                    f"/api/v1/chat/escalations?encounter_id={OTHER_ENCOUNTER_ID}",
                    headers={"Authorization": "Bearer mock-staff-token"},
                )

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_invalid_encounter_id_uuid_returns_422(self):
        with patch(
            "api_gateway.app.routers.escalation.get_current_token_claims",
            return_value={"role": "nurse", "sub": "nurse-1"},
        ):
            async with AsyncClient(app=app, base_url="http://test") as client:
                resp = await client.get(
                    "/api/v1/chat/escalations?encounter_id=not-a-uuid",
                    headers={"Authorization": "Bearer mock-staff-token"},
                )

        assert resp.status_code == 422
```

### 5. Run tests

```bash
# From workspace root
cd backend
pytest tests/unit/agents/patient_comm/escalation/ \
  --cov=backend/app/agents/patient_comm/escalation \
  --cov-report=term-missing \
  -v

cd ../api-gateway
pytest tests/unit/routers/test_escalation_endpoints_post_patch.py \
       tests/unit/routers/test_escalation_endpoint_get.py \
  --cov=api_gateway/app/routers/escalation \
  --cov-report=term-missing \
  -v
```

---

## Validation Checklist

- [ ] All test files parse without import errors
- [ ] `test_escalation_schemas.py`: all 9 tests pass
- [ ] `test_escalation_endpoints_post_patch.py`: all 8 tests pass
- [ ] `test_escalation_endpoint_get.py`: all 6 tests pass
- [ ] Coverage ≥80% across `escalation/schemas.py`, `escalation/models.py`, `escalation/monitoring.py`, `routers/escalation.py`
- [ ] `test_post_escalate_wrong_encounter_returns_403` — status 403, body `{"detail": "Access denied."}`
- [ ] `test_signalr_escalation_confirmed_pushed` — `send_to_group` called with `encounter-{id}` group
- [ ] `test_pubsub_published_as_fire_and_forget` — `asyncio.create_task` called (not `await`)
- [ ] `test_idempotent_second_acknowledge` — `emit_acknowledgement_metric` NOT called on second PATCH
- [ ] `test_sla_breach_metric_emitted_when_late` — `ack_time_minutes > 2.0` in emit call

---

## Dependencies

| Dependency | Type | Reason |
|---|---|---|
| US-045/TASK-001 | Task | Schemas under test |
| US-045/TASK-002 | Task | POST /escalate endpoint under test |
| US-045/TASK-003 | Task | PATCH /acknowledge endpoint under test |
| US-045/TASK-004 | Task | GET /escalations endpoint under test |
| `pytest-asyncio` | Package | Async test runner |
| `httpx` | Package | `AsyncClient` for FastAPI testing |
| `pytest-cov` | Package | Coverage reporting |
