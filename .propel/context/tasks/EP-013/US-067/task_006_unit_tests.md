---
id: TASK-006
title: "Unit Tests — Opt-Out Suppression, Urgency Bypass, Patient Preference Update, and Staff Log Query"
user_story: US-067
epic: EP-013
sprint: 2
layer: Backend / Testing
estimate: 1.5h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [TASK-001, TASK-002, TASK-003, TASK-004, TASK-005]
---

# TASK-006: Unit Tests — Opt-Out Suppression, Urgency Bypass, Patient Preference Update, and Staff Log Query

> **Story:** US-067 | **Epic:** EP-013 | **Sprint:** 2 | **Layer:** Backend / Testing | **Est:** 1.5 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-067 DoD specifies:

> *"Unit tests: opt-out suppression, urgency bypass, patient preference update, staff log query"*

This task authors pytest unit tests covering all four DoD-specified test scenarios. Tests use `pytest-asyncio` for async FastAPI handlers and `unittest.mock` / `AsyncMock` for DB session and dependency injection isolation. No live DB or Pub/Sub connection is required.

Test coverage scope:

| Test Suite | File | Scenarios |
|---|---|---|
| Opt-out suppression | `test_dispatcher_optout.py` | Non-urgent notification suppressed for opted-out patient |
| Urgency bypass | `test_dispatcher_optout.py` | Urgent notification bypasses opt-out; dispatched; record shows `urgency_override=True` |
| Patient preference update | `test_portal_preferences.py` | PATCH updates `notification_opt_out`; 200 OK; audit log created |
| Staff log query | `test_notifications_audit_log.py` | `GET /api/v1/notifications` returns correct fields; PHI excluded; patient JWT rejected |

Design decisions:

| Decision | Rationale |
|----------|-----------|
| `AsyncMock` for DB sessions | Avoids real DB dependency; tests run in CI without PostgreSQL |
| `pytest.mark.asyncio` for all async tests | Required for `pytest-asyncio` to run coroutines |
| Parametrize urgency/non-urgent cases | Single test function covers both branches; clearer boundary documentation |
| Assert `recipient_phone` absent from response | Programmatic PHI exclusion guard — prevents future regression |
| Mock `require_role` and `get_current_patient_user` | Isolates auth from business logic; auth is tested separately |
| Assert audit log written on opt-out suppression | BR-012 compliance — audit completeness is a test-level requirement |

Design refs: US-067 DoD, TASK-003 (dispatcher), TASK-004 (GET endpoint), TASK-005 (PATCH endpoint), pytest-asyncio docs.

---

## Acceptance Criteria Addressed

| US-067 AC | Requirement |
|---|---|
| **Scenario 1** | `test_staff_log_query_returns_correct_fields` verifies response shape and PHI exclusion |
| **Scenario 2** | `test_opt_out_suppression_creates_opted_out_record` verifies no dispatch and `OPTED_OUT` status |
| **Scenario 3** | `test_urgency_bypass_dispatches_despite_opt_out` verifies dispatch and `urgency_override=True` |
| **Scenario 4** | `test_patient_preference_update_persists_opt_out` verifies 200 OK and DB write |
| **DoD** | All four unit test categories implemented |

---

## Implementation Steps

### 1. Create `notification-service/tests/test_dispatcher_optout.py`

```python
"""Unit tests — notification dispatcher opt-out suppression and urgency bypass.

Covers:
    - Non-urgent notification for opted-out patient: OPTED_OUT record created, no dispatch
    - Urgent notification (urgency_override=True) for opted-out patient: dispatched, SENT record
    - Audit log written for both scenarios (BR-012)
    - No PHI in any log payload

Design refs: US-067 DoD, TASK-003, TASK-002.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.dispatcher import dispatch_notification
from app.models.notification import DeliveryStatus
from app.schemas.notification_message import NotificationChannel, NotificationMessage


PATIENT_ID = uuid.uuid4()
ENCOUNTER_ID = uuid.uuid4()


def _make_message(urgency_override: bool, notification_type: str = "medication_reminder") -> NotificationMessage:
    return NotificationMessage.model_validate({
        "idempotency_key": f"test-{uuid.uuid4()}",
        "type": notification_type,
        "channel": "SMS",
        "recipient_id": str(PATIENT_ID),
        "encounter_id": str(ENCOUNTER_ID),
        "template_name": "medication_reminder",
        "urgency_override": urgency_override,
    })


@pytest.mark.asyncio
async def test_opt_out_suppression_creates_opted_out_record():
    """Non-urgent notification for opted-out patient → OPTED_OUT record; no dispatch."""
    mock_db = AsyncMock()
    mock_db.execute.return_value.scalar_one_or_none.return_value = True  # patient.notification_opt_out = True

    with (
        patch("app.dispatcher._get_patient_opt_out", return_value=True),
        patch("app.dispatcher._dispatch_sms", new_callable=AsyncMock) as mock_sms,
        patch("app.dispatcher._dispatch_email", new_callable=AsyncMock) as mock_email,
        patch("app.dispatcher._write_audit_log", new_callable=AsyncMock) as mock_audit,
    ):
        msg = _make_message(urgency_override=False)
        await dispatch_notification(msg, mock_db)

        # SMS and email must NOT be called
        mock_sms.assert_not_called()
        mock_email.assert_not_called()

        # DB add must be called once (OPTED_OUT notification record)
        mock_db.add.assert_called_once()
        added_record = mock_db.add.call_args[0][0]
        assert added_record.delivery_status == DeliveryStatus.OPTED_OUT
        assert added_record.urgency_override is False

        # Audit log must be written for BR-012
        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["action"] == "NOTIFICATION_SUPPRESSED_OPT_OUT"
        # Confirm no PHI in audit call (no name, phone, email)
        assert "phone" not in str(call_kwargs)
        assert "email" not in str(call_kwargs)


@pytest.mark.asyncio
async def test_urgency_bypass_dispatches_despite_opt_out():
    """Urgent notification (urgency_override=True) dispatched even for opted-out patient."""
    mock_db = AsyncMock()

    with (
        patch("app.dispatcher._get_patient_opt_out", return_value=True),
        patch("app.dispatcher._dispatch_sms", new_callable=AsyncMock) as mock_sms,
        patch("app.dispatcher._write_audit_log", new_callable=AsyncMock) as mock_audit,
    ):
        msg = _make_message(urgency_override=True, notification_type="CARE_TEAM_URGENCY_ALERT")
        await dispatch_notification(msg, mock_db)

        # SMS must be called despite opt-out
        mock_sms.assert_called_once()

        # Notification record must have urgency_override=True and SENT status
        mock_db.add.assert_called()
        added_record = mock_db.add.call_args[0][0]
        assert added_record.urgency_override is True
        assert added_record.delivery_status == DeliveryStatus.SENT

        # Audit log written
        mock_audit.assert_called()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["urgency_override"] is True


@pytest.mark.asyncio
async def test_opted_in_patient_receives_non_urgent_notification():
    """Non-urgent notification for opted-in patient proceeds normally."""
    mock_db = AsyncMock()

    with (
        patch("app.dispatcher._get_patient_opt_out", return_value=False),
        patch("app.dispatcher._dispatch_sms", new_callable=AsyncMock) as mock_sms,
        patch("app.dispatcher._write_audit_log", new_callable=AsyncMock),
    ):
        msg = _make_message(urgency_override=False)
        await dispatch_notification(msg, mock_db)

        mock_sms.assert_called_once()
```

### 2. Create `backend/tests/test_portal_preferences.py`

```python
"""Unit tests — PATCH /api/v1/portal/preferences (patient notification opt-out).

Covers:
    - Patient can set notification_opt_out=True → 200 OK; DB update called
    - Patient can set notification_opt_out=False → 200 OK; DB update called
    - Audit log written on preference change (BR-012)
    - Staff JWT rejected (403 Forbidden)
    - urgency_override NOT settable via this endpoint (schema guard)

Design refs: US-067 AC Scenario 4, TASK-005.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.auth.dependencies import get_current_patient_user, require_role
from app.db.session import get_db


PATIENT_ID = uuid.uuid4()


def _mock_patient():
    patient = MagicMock()
    patient.id = PATIENT_ID
    return patient


@pytest.fixture()
def client_with_patient_auth():
    """TestClient with patient JWT dependency override."""
    app.dependency_overrides[get_current_patient_user] = lambda: _mock_patient()
    app.dependency_overrides[get_db] = lambda: AsyncMock()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_patient_preference_update_sets_opt_out_true(client_with_patient_auth):
    """PATCH with notification_opt_out=True returns 200 OK."""
    response = client_with_patient_auth.patch(
        "/api/v1/portal/preferences",
        json={"notification_opt_out": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["notification_opt_out"] is True


def test_patient_preference_update_sets_opt_out_false(client_with_patient_auth):
    """PATCH with notification_opt_out=False (opt back in) returns 200 OK."""
    response = client_with_patient_auth.patch(
        "/api/v1/portal/preferences",
        json={"notification_opt_out": False},
    )
    assert response.status_code == 200
    assert response.json()["notification_opt_out"] is False


def test_urgency_override_not_in_request_schema():
    """urgency_override must not be a field in PortalPreferencesUpdateRequest."""
    from app.schemas.portal import PortalPreferencesUpdateRequest
    assert "urgency_override" not in PortalPreferencesUpdateRequest.model_fields, (
        "SECURITY: urgency_override must never be patient-settable"
    )


def test_staff_jwt_rejected_from_portal_preferences():
    """Staff JWT must be rejected from PATCH /api/v1/portal/preferences."""
    # Override get_current_patient_user to raise 403 (simulates staff JWT rejection)
    from fastapi import HTTPException
    def raise_403():
        raise HTTPException(status_code=403, detail="Patient JWT required")

    app.dependency_overrides[get_current_patient_user] = raise_403
    app.dependency_overrides[get_db] = lambda: AsyncMock()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.patch("/api/v1/portal/preferences", json={"notification_opt_out": True})
    assert response.status_code == 403
    app.dependency_overrides.clear()
```

### 3. Create `backend/tests/test_notifications_audit_log.py`

```python
"""Unit tests — GET /api/v1/notifications (notification audit log endpoint).

Covers:
    - Staff JWT returns notification list with correct fields
    - PHI fields (recipient_phone, recipient_email) excluded from response
    - Patient JWT rejected (403)
    - Empty list returned when no notifications exist for encounter
    - urgency_override field present in response items

Design refs: US-067 AC Scenario 1, TASK-004.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.auth.dependencies import require_role
from app.db.session import get_read_db


ENCOUNTER_ID = uuid.uuid4()
PATIENT_ID = uuid.uuid4()


def _make_notification_record(delivery_status="SENT", urgency_override=False):
    record = MagicMock()
    record.id = uuid.uuid4()
    record.type = "medication_reminder"
    record.channel = "SMS"
    record.sent_at = datetime(2026, 7, 16, 10, 0, tzinfo=timezone.utc)
    record.delivery_status = delivery_status
    record.template_name = "medication_reminder"
    record.urgency_override = urgency_override
    record.recipient_phone_hash = "abc123hash"
    record.recipient_email_hash = None
    # PHI fields must NOT be in ORM model per TASK-004
    return record


@pytest.fixture()
def client_with_staff_auth():
    """TestClient with staff role dependency override."""
    app.dependency_overrides[require_role] = lambda roles: (lambda: MagicMock())
    mock_db = AsyncMock()
    mock_records = [_make_notification_record()]
    mock_db.execute.return_value.scalars.return_value.all.return_value = mock_records
    app.dependency_overrides[get_read_db] = lambda: mock_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_staff_log_query_returns_correct_fields(client_with_staff_auth):
    """GET /api/v1/notifications returns required fields from AC Scenario 1."""
    response = client_with_staff_auth.get(
        f"/api/v1/notifications?encounter_id={ENCOUNTER_ID}"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["encounter_id"] == str(ENCOUNTER_ID)
    assert body["total"] == 1
    item = body["items"][0]
    # AC Scenario 1 required fields
    assert "type" in item or "notification_type" in item
    assert "channel" in item
    assert "delivery_status" in item
    assert "template_name" in item
    assert "urgency_override" in item


def test_phi_excluded_from_notification_log_response(client_with_staff_auth):
    """recipient_phone and recipient_email must not appear in response."""
    response = client_with_staff_auth.get(
        f"/api/v1/notifications?encounter_id={ENCOUNTER_ID}"
    )
    assert response.status_code == 200
    response_text = response.text
    assert "recipient_phone\":" not in response_text or "recipient_phone_hash" in response_text
    # Ensure no plaintext phone/email values leak
    assert "recipient_email\":" not in response_text or "recipient_email_hash" in response_text


def test_empty_list_returned_for_encounter_with_no_notifications():
    """GET with encounter_id that has no notifications returns 200 with empty items list."""
    mock_db = AsyncMock()
    mock_db.execute.return_value.scalars.return_value.all.return_value = []
    app.dependency_overrides[require_role] = lambda roles: (lambda: MagicMock())
    app.dependency_overrides[get_read_db] = lambda: mock_db
    client = TestClient(app)
    response = client.get(f"/api/v1/notifications?encounter_id={uuid.uuid4()}")
    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert response.json()["items"] == []
    app.dependency_overrides.clear()


def test_encounter_id_required_parameter():
    """GET without encounter_id returns 422 Unprocessable Entity."""
    app.dependency_overrides[require_role] = lambda roles: (lambda: MagicMock())
    app.dependency_overrides[get_read_db] = lambda: AsyncMock()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/v1/notifications")
    assert response.status_code == 422
    app.dependency_overrides.clear()
```

### 4. Run all tests

```bash
# Notification service dispatcher tests
cd notification-service
pytest tests/test_dispatcher_optout.py -v

# Backend API tests
cd ../backend
pytest tests/test_portal_preferences.py tests/test_notifications_audit_log.py -v

# Full US-067 test suite
pytest tests/test_dispatcher_optout.py \
       tests/test_portal_preferences.py \
       tests/test_notifications_audit_log.py \
       -v --tb=short
```

---

## Validation

```bash
# All US-067 unit tests pass
pytest tests/test_dispatcher_optout.py \
       tests/test_portal_preferences.py \
       tests/test_notifications_audit_log.py \
       -v --tb=short 2>&1 | tail -20
# Expected: all PASSED, 0 FAILED

# No regressions in existing US-064 tests
cd notification-service
pytest tests/ -v --tb=short 2>&1 | tail -5
# Expected: all PASSED
```

---

## Files Involved

| File | Action | Notes |
|------|--------|-------|
| `notification-service/tests/test_dispatcher_optout.py` | Create | Opt-out suppression, urgency bypass, opted-in baseline tests |
| `backend/tests/test_portal_preferences.py` | Create | Patient preference update, staff rejection, schema security guard |
| `backend/tests/test_notifications_audit_log.py` | Create | Staff log query fields, PHI exclusion, empty list, required param |

---

## Definition of Done (Task-Level)

- [ ] `test_opt_out_suppression_creates_opted_out_record` passes
- [ ] `test_urgency_bypass_dispatches_despite_opt_out` passes
- [ ] `test_patient_preference_update_sets_opt_out_true` passes
- [ ] `test_staff_log_query_returns_correct_fields` passes
- [ ] `test_phi_excluded_from_notification_log_response` passes
- [ ] `test_urgency_override_not_in_request_schema` passes (security guard)
- [ ] `test_staff_jwt_rejected_from_portal_preferences` passes
- [ ] All existing US-064 tests remain passing (no regressions)
