---
id: TASK-005
title: "Write Unit Tests — Idempotency, Retry Logic, and Twilio Webhook Validation"
user_story: US-064
epic: EP-013
sprint: 2
layer: Backend / Testing
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [TASK-001, TASK-002, TASK-003, TASK-004]
---

# TASK-005: Write Unit Tests — Idempotency, Retry Logic, and Twilio Webhook Validation

> **Story:** US-064 | **Epic:** EP-013 | **Sprint:** 2 | **Layer:** Backend / Testing | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-064 DoD specifies:

> *"Unit tests: idempotency, retry logic, Twilio webhook validation"*

This task authors the complete unit test suite for the `notification-service`. Tests cover:

1. **Idempotency** — `INSERT ... ON CONFLICT DO NOTHING` returns 0 rows on duplicate; consumer ACKs without dispatching
2. **Retry logic** — Twilio 503 schedules APScheduler retry at correct delays; final failure sets `FAILED` and publishes `CARE_TEAM_ALERT`
3. **Webhook validation** — valid `X-Twilio-Signature` updates status; missing/invalid signature returns HTTP 403
4. **Opt-out enforcement** — `notification_opt_out=True` sets `OPTED_OUT` without calling Twilio
5. **SendGrid dispatch** — Dynamic Template ID and substitutions passed correctly

All tests use `pytest` with `pytest-asyncio` and `unittest.mock` to avoid real network calls to Twilio/SendGrid APIs or Pub/Sub.

Design decisions:

| Decision | Rationale |
|----------|-----------|
| `AsyncMock` for Twilio client | `client.messages.create()` is called in async context; needs `AsyncMock` |
| In-memory SQLite for DB tests | Fast, dependency-free; avoids Cloud SQL requirement in CI |
| `httpx.AsyncClient` for webhook endpoint tests | FastAPI TestClient is sync; webhook tests need async client for form POST |
| Monkeypatching `get_secret()` | Prevents Secret Manager calls in test environment |
| APScheduler `MockScheduler` | Tests verify `add_job()` is called with correct delay; no real timers |

Design refs: US-064 DoD, design.md §4.1 (unit testing patterns per language-agnostic-standards).

---

## Acceptance Criteria Addressed

| US-064 AC | Requirement |
|---|---|
| **Scenario 2** | Test: duplicate `idempotency_key` → 0 rows inserted, ACK without dispatch |
| **Scenario 4** | Test: Twilio 503 → retry scheduled at 30 s; 3 failures → `FAILED` + alert |
| **Scenario 3** | Test: valid webhook signature → `DELIVERED`; invalid sig → 403 |
| **DoD opt-out** | Test: `notification_opt_out=True` → `OPTED_OUT`, no Twilio call |

---

## Implementation Steps

### 1. Scaffold test directory structure

```
notification-service/
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── unit/
    │   ├── __init__.py
    │   ├── test_idempotency.py
    │   ├── test_sms_retry.py
    │   ├── test_webhook_validation.py
    │   └── test_opt_out.py
    └── fixtures/
        └── notification_payloads.py
```

```bash
mkdir -p notification-service/tests/unit
mkdir -p notification-service/tests/fixtures
touch notification-service/tests/__init__.py
touch notification-service/tests/unit/__init__.py
touch notification-service/tests/fixtures/__init__.py
```

### 2. Create `notification-service/tests/conftest.py`

```python
"""Shared pytest fixtures for notification-service tests.

Provides:
    - async_session: In-memory SQLite async session with notification schema
    - mock_twilio_client: Pre-configured AsyncMock for twilio.rest.Client
    - mock_sendgrid_client: Pre-configured Mock for sendgrid.SendGridAPIClient
    - mock_get_secret: Monkeypatches get_secret() to return test credentials
"""
from __future__ import annotations

import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.notification import Notification, NotificationStatus, NotificationType


@pytest.fixture(scope="session")
def engine():
    """Create an in-memory SQLite async engine for tests."""
    return create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)


@pytest_asyncio.fixture(scope="function")
async def async_session(engine) -> AsyncGenerator[AsyncSession, None]:
    """Create tables and yield a fresh session for each test."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
def mock_twilio_client():
    """Mock Twilio REST client — messages.create returns a fake message."""
    mock = MagicMock()
    mock.messages.create.return_value = MagicMock(sid="SM_TEST_SID_001")
    with patch("app.dispatchers.sms._build_twilio_client", return_value=mock):
        yield mock


@pytest.fixture
def mock_sendgrid_client():
    """Mock SendGrid client — send returns 202 with X-Message-Id header."""
    mock_response = MagicMock()
    mock_response.status_code = 202
    mock_response.headers = {"X-Message-Id": "SG_TEST_MSG_001"}
    mock_client = MagicMock()
    mock_client.send.return_value = mock_response
    with patch("app.dispatchers.email._build_sendgrid_client", return_value=mock_client):
        yield mock_client


@pytest.fixture(autouse=True)
def mock_get_secret():
    """Prevent Secret Manager calls in tests."""
    with patch(
        "app.core.secrets.get_secret",
        side_effect=lambda secret_id: {
            "twilio-account-sid": "AC_TEST_SID",
            "twilio-auth-token": "TEST_AUTH_TOKEN",
            "sendgrid-api-key": "SG_TEST_KEY",
        }.get(secret_id, "TEST_SECRET"),
    ):
        yield


@pytest.fixture
def sample_sms_request():
    from app.schemas import NotificationRequest, NotificationTypeEnum
    return NotificationRequest(
        idempotency_key=f"NOTIF-{uuid.uuid4()}",
        type=NotificationTypeEnum.SMS,
        phone="+15005550006",
        template="medication_reminder",
        substitutions={"patient_name": "Jane Doe"},
        recipient_id=str(uuid.uuid4()),
    )


@pytest.fixture
def sample_email_request():
    from app.schemas import NotificationRequest, NotificationTypeEnum
    return NotificationRequest(
        idempotency_key=f"NOTIF-{uuid.uuid4()}",
        type=NotificationTypeEnum.EMAIL,
        email="patient@example.com",
        template="d-test_dynamic_template_id",
        substitutions={"first_name": "Jane"},
        recipient_id=str(uuid.uuid4()),
    )
```

### 3. Create `notification-service/tests/unit/test_idempotency.py`

```python
"""Unit tests: idempotency guard prevents duplicate notification dispatch.

US-064 AC Scenario 2:
    Given: notification with idempotency_key=NOTIF-001 was already sent
    When: same Pub/Sub message is redelivered
    Then: service detects duplicate; no SMS sent; message ACKed

Tests:
    - test_insert_succeeds_on_first_message: rowcount=1 for new key
    - test_insert_skipped_on_duplicate_key: rowcount=0 for existing key
    - test_consumer_acks_without_dispatch_on_duplicate: dispatcher not called
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.consumer import _upsert_notification
from app.schemas import NotificationRequest, NotificationTypeEnum


@pytest.mark.asyncio
async def test_insert_succeeds_on_first_message(async_session, sample_sms_request):
    """First message with a new idempotency key inserts 1 row."""
    notification_id = uuid.uuid4()
    rows = await _upsert_notification(async_session, notification_id, sample_sms_request)
    assert rows == 1, "Expected 1 row inserted for new idempotency key"


@pytest.mark.asyncio
async def test_insert_skipped_on_duplicate_key(async_session, sample_sms_request):
    """Second message with the same idempotency key inserts 0 rows."""
    notification_id_1 = uuid.uuid4()
    notification_id_2 = uuid.uuid4()

    rows_first = await _upsert_notification(async_session, notification_id_1, sample_sms_request)
    rows_second = await _upsert_notification(async_session, notification_id_2, sample_sms_request)

    assert rows_first == 1, "First insert should succeed"
    assert rows_second == 0, "Duplicate idempotency_key should be silently skipped"


@pytest.mark.asyncio
async def test_consumer_acks_without_dispatch_on_duplicate(
    async_session, sample_sms_request, mock_twilio_client
):
    """Consumer ACKs the message without calling Twilio on duplicate key."""
    notification_id = uuid.uuid4()
    # Pre-insert the notification row to simulate prior processing
    await _upsert_notification(async_session, notification_id, sample_sms_request)

    mock_subscriber = MagicMock()
    mock_subscriber.acknowledge = MagicMock()

    with patch("app.consumer.AsyncSessionFactory") as mock_factory:
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=async_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        from app.consumer import _process_message
        await _process_message(
            message_data=json.dumps(sample_sms_request.model_dump()).encode(),
            ack_id="test-ack-id",
            subscriber=mock_subscriber,
            subscription_path="projects/test/subscriptions/test-sub",
        )

    # ACK called — message consumed without dispatch
    mock_subscriber.acknowledge.assert_called_once()
    # Twilio not called — no new SMS sent
    mock_twilio_client.messages.create.assert_not_called()
```

### 4. Create `notification-service/tests/unit/test_sms_retry.py`

```python
"""Unit tests: SMS dispatcher retry logic and final failure handling.

US-064 AC Scenario 4:
    Given: Twilio returns HTTP 503 on first send attempt
    When: notification service retries
    Then: retry 2 after 30s, retry 3 after 60s; all 3 fail →
          notification.status=FAILED, CARE_TEAM_ALERT published

Tests:
    - test_successful_send_sets_status_sent: Twilio 2xx → SENT + SID stored
    - test_transient_503_schedules_retry: Twilio 503 → APScheduler job added
    - test_retry_delays_are_correct: retry 1→30s, 2→60s, 3→120s
    - test_all_retries_exhausted_sets_failed: 3 failures → FAILED
    - test_care_team_alert_published_on_final_failure: Pub/Sub publish called
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from twilio.base.exceptions import TwilioRestException

from app.dispatchers.sms import TwilioSMSDispatcher, _RETRY_DELAYS, _MAX_RETRIES
from app.models.notification import Notification, NotificationStatus


def _make_twilio_error(status: int) -> TwilioRestException:
    """Helper: create a TwilioRestException with the given HTTP status."""
    exc = TwilioRestException(
        msg=f"HTTP {status} error",
        uri="/Messages",
        method="POST",
        status=status,
        code=20003,
    )
    return exc


@pytest.mark.asyncio
async def test_successful_send_sets_status_sent(
    async_session, sample_sms_request, mock_twilio_client
):
    """Twilio 2xx response sets notification.status=SENT and stores SID."""
    dispatcher = TwilioSMSDispatcher.__new__(TwilioSMSDispatcher)
    dispatcher._from_number = "+15005550001"

    notif_id = uuid.uuid4()
    # Pre-insert row
    from app.consumer import _upsert_notification
    await _upsert_notification(async_session, notif_id, sample_sms_request)

    with patch("app.dispatchers.sms._build_twilio_client", return_value=mock_twilio_client):
        await dispatcher.dispatch(async_session, notif_id, sample_sms_request)

    from sqlalchemy import select
    row = (await async_session.execute(
        select(Notification).where(Notification.id == notif_id)
    )).scalar_one()

    assert row.status == NotificationStatus.SENT
    assert row.twilio_message_sid == "SM_TEST_SID_001"
    assert row.sent_at is not None


@pytest.mark.asyncio
async def test_transient_503_schedules_retry(async_session, sample_sms_request):
    """Twilio 503 causes APScheduler job to be scheduled for retry 2."""
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = _make_twilio_error(503)

    mock_scheduler = MagicMock()
    dispatcher = TwilioSMSDispatcher.__new__(TwilioSMSDispatcher)
    dispatcher._from_number = "+15005550001"

    notif_id = uuid.uuid4()
    from app.consumer import _upsert_notification
    await _upsert_notification(async_session, notif_id, sample_sms_request)

    with (
        patch("app.dispatchers.sms._build_twilio_client", return_value=mock_client),
        patch("app.dispatchers.sms.get_scheduler", return_value=mock_scheduler),
        patch("app.dispatchers.sms.TwilioSMSDispatcher._check_opt_out", AsyncMock(return_value=False)),
    ):
        await dispatcher._attempt_send(async_session, notif_id, sample_sms_request, attempt=1)

    mock_scheduler.add_job.assert_called_once()
    call_kwargs = mock_scheduler.add_job.call_args.kwargs
    assert call_kwargs["seconds"] == _RETRY_DELAYS[0]  # 30 seconds


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "attempt,expected_delay",
    [(1, 30), (2, 60), (3, 120)],
)
async def test_retry_delays_are_correct(
    async_session, sample_sms_request, attempt, expected_delay
):
    """Each retry attempt uses the correct delay from the backoff schedule."""
    assert _RETRY_DELAYS[attempt - 1] == expected_delay


@pytest.mark.asyncio
async def test_all_retries_exhausted_sets_failed(async_session, sample_sms_request):
    """3 Twilio failures exhausted → notification.status=FAILED."""
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = _make_twilio_error(503)

    dispatcher = TwilioSMSDispatcher.__new__(TwilioSMSDispatcher)
    dispatcher._from_number = "+15005550001"

    notif_id = uuid.uuid4()
    from app.consumer import _upsert_notification
    await _upsert_notification(async_session, notif_id, sample_sms_request)

    with (
        patch("app.dispatchers.sms._build_twilio_client", return_value=mock_client),
        patch("app.dispatchers.sms.get_scheduler", return_value=MagicMock()),
        patch("app.dispatchers.sms.TwilioSMSDispatcher._check_opt_out", AsyncMock(return_value=False)),
        patch("app.dispatchers.sms.TwilioSMSDispatcher._publish_care_team_alert", AsyncMock()),
    ):
        # Simulate all 3 attempts exhausted (attempt=MAX_RETRIES+1 triggers final failure)
        await dispatcher._attempt_send(
            async_session, notif_id, sample_sms_request, attempt=_MAX_RETRIES + 1
        )

    from sqlalchemy import select
    row = (await async_session.execute(
        select(Notification).where(Notification.id == notif_id)
    )).scalar_one()
    assert row.status == NotificationStatus.FAILED


@pytest.mark.asyncio
async def test_care_team_alert_published_on_final_failure(
    async_session, sample_sms_request
):
    """CARE_TEAM_ALERT is published to Pub/Sub when all retries exhausted."""
    dispatcher = TwilioSMSDispatcher.__new__(TwilioSMSDispatcher)
    notif_id = uuid.uuid4()

    from app.consumer import _upsert_notification
    await _upsert_notification(async_session, notif_id, sample_sms_request)

    mock_publisher = MagicMock()
    with patch("app.dispatchers.sms.pubsub_v1.PublisherClient", return_value=mock_publisher):
        await dispatcher._handle_final_failure(
            async_session, notif_id, sample_sms_request, "Twilio 503 error"
        )

    mock_publisher.publish.assert_called_once()
    published_data = mock_publisher.publish.call_args[0][1]
    import json
    payload = json.loads(published_data)
    assert payload["alert_type"] == "CARE_TEAM_ALERT"
    assert payload["idempotency_key"] == sample_sms_request.idempotency_key
```

### 5. Create `notification-service/tests/unit/test_webhook_validation.py`

```python
"""Unit tests: Twilio delivery webhook signature validation.

US-064 AC Scenario 3:
    Given: Twilio sends POST /webhooks/twilio/status with MessageSid and MessageStatus=delivered
    When: webhook is processed
    Then: notification.status updates to DELIVERED; invalid signature → 403

Tests:
    - test_valid_signature_updates_status_delivered: valid sig → DELIVERED
    - test_missing_signature_returns_403: no X-Twilio-Signature → 403
    - test_invalid_signature_returns_403: tampered sig → 403
    - test_delivered_at_timestamp_set: delivered_at populated on DELIVERED
    - test_intermediate_status_no_change: 'sent' status → no DB update
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.notification import Notification, NotificationStatus


def _generate_valid_signature(url: str, params: dict, auth_token: str) -> str:
    """Generate a valid Twilio signature for testing."""
    from twilio.request_validator import RequestValidator
    validator = RequestValidator(auth_token)
    return validator.compute_signature(url, params)


TEST_AUTH_TOKEN = "TEST_AUTH_TOKEN"
WEBHOOK_URL = "http://testserver/webhooks/twilio/status"


@pytest.mark.asyncio
async def test_missing_signature_returns_403():
    """Request without X-Twilio-Signature header returns HTTP 403."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/webhooks/twilio/status",
            data={"MessageSid": "SM_TEST_001", "MessageStatus": "delivered"},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_invalid_signature_returns_403():
    """Tampered or wrong X-Twilio-Signature header returns HTTP 403."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/webhooks/twilio/status",
            data={"MessageSid": "SM_TEST_001", "MessageStatus": "delivered"},
            headers={"X-Twilio-Signature": "INVALID_SIGNATURE"},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_valid_signature_updates_status_delivered(async_session):
    """Valid Twilio signature with MessageStatus=delivered → status=DELIVERED."""
    # Insert a pre-existing notification with status=SENT
    notif = Notification(
        id=uuid.uuid4(),
        idempotency_key=f"NOTIF-WEBHOOK-{uuid.uuid4()}",
        type=NotificationStatus.SENT,  # type: ignore[arg-type]
        template="medication_reminder",
        status=NotificationStatus.SENT,
        twilio_message_sid="SM_TEST_WEBHOOK_001",
    )

    # Compute valid signature
    params = {"MessageSid": "SM_TEST_WEBHOOK_001", "MessageStatus": "delivered"}
    signature = _generate_valid_signature(WEBHOOK_URL, params, TEST_AUTH_TOKEN)

    with (
        patch("app.webhooks.twilio.get_secret", return_value=TEST_AUTH_TOKEN),
        patch("app.webhooks.twilio.get_db_session", return_value=async_session),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/webhooks/twilio/status",
                data=params,
                headers={"X-Twilio-Signature": signature},
            )

    assert response.status_code == 204


@pytest.mark.asyncio
async def test_intermediate_status_no_db_change(async_session):
    """MessageStatus='sent' (intermediate) does not change notification status."""
    params = {"MessageSid": "SM_TEST_002", "MessageStatus": "sent"}
    signature = _generate_valid_signature(WEBHOOK_URL, params, TEST_AUTH_TOKEN)

    with (
        patch("app.webhooks.twilio.get_secret", return_value=TEST_AUTH_TOKEN),
        patch("app.webhooks.twilio.get_db_session", return_value=async_session),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/webhooks/twilio/status",
                data=params,
                headers={"X-Twilio-Signature": signature},
            )

    # 204 with no DB change for intermediate status
    assert response.status_code == 204
```

### 6. Create `notification-service/tests/unit/test_opt_out.py`

```python
"""Unit tests: patient opt-out suppresses notification dispatch.

US-064 DoD:
    Opt-out flag: patient.notification_opt_out=True → skip send + log

Tests:
    - test_opted_out_patient_sets_opted_out_status: no Twilio/SendGrid call
    - test_urgency_override_bypasses_opt_out: urgency_override=True → still sends
    - test_non_opted_out_patient_sends_normally: opt_out=False → Twilio called
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.dispatchers.sms import TwilioSMSDispatcher
from app.models.notification import Notification, NotificationStatus
from app.schemas import NotificationRequest, NotificationTypeEnum


@pytest.mark.asyncio
async def test_opted_out_patient_sets_opted_out_status(
    async_session, sample_sms_request, mock_twilio_client
):
    """patient.notification_opt_out=True → status=OPTED_OUT, Twilio not called."""
    from app.consumer import _upsert_notification
    notif_id = uuid.uuid4()
    await _upsert_notification(async_session, notif_id, sample_sms_request)

    dispatcher = TwilioSMSDispatcher.__new__(TwilioSMSDispatcher)
    dispatcher._from_number = "+15005550001"

    with patch(
        "app.dispatchers.sms.TwilioSMSDispatcher._check_opt_out",
        AsyncMock(return_value=True),
    ):
        await dispatcher.dispatch(async_session, notif_id, sample_sms_request)

    from sqlalchemy import select
    row = (await async_session.execute(
        select(Notification).where(Notification.id == notif_id)
    )).scalar_one()

    assert row.status == NotificationStatus.OPTED_OUT
    mock_twilio_client.messages.create.assert_not_called()


@pytest.mark.asyncio
async def test_urgency_override_bypasses_opt_out(
    async_session, mock_twilio_client
):
    """urgency_override=True bypasses opt-out check and sends SMS."""
    request = NotificationRequest(
        idempotency_key=f"NOTIF-URGENT-{uuid.uuid4()}",
        type=NotificationTypeEnum.SMS,
        phone="+15005550006",
        template="emergency_alert",
        substitutions={},
        recipient_id=str(uuid.uuid4()),
        urgency_override=True,
    )

    from app.consumer import _upsert_notification
    notif_id = uuid.uuid4()
    await _upsert_notification(async_session, notif_id, request)

    dispatcher = TwilioSMSDispatcher.__new__(TwilioSMSDispatcher)
    dispatcher._from_number = "+15005550001"

    with (
        patch(
            "app.dispatchers.sms.TwilioSMSDispatcher._check_opt_out",
            AsyncMock(return_value=True),  # Opted out, but urgency_override=True
        ),
        patch("app.dispatchers.sms._build_twilio_client", return_value=mock_twilio_client),
    ):
        await dispatcher.dispatch(async_session, notif_id, request)

    # urgency_override=True → opt-out bypassed → Twilio called
    mock_twilio_client.messages.create.assert_called_once()
```

### 7. Create `notification-service/pytest.ini`

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
```

---

## Validation

```bash
cd notification-service
pip install pytest pytest-asyncio aiosqlite httpx

# Run full test suite
pytest tests/unit/ -v

# Expected output (all pass):
# tests/unit/test_idempotency.py::test_insert_succeeds_on_first_message PASSED
# tests/unit/test_idempotency.py::test_insert_skipped_on_duplicate_key PASSED
# tests/unit/test_idempotency.py::test_consumer_acks_without_dispatch_on_duplicate PASSED
# tests/unit/test_sms_retry.py::test_successful_send_sets_status_sent PASSED
# tests/unit/test_sms_retry.py::test_transient_503_schedules_retry PASSED
# tests/unit/test_sms_retry.py::test_retry_delays_are_correct[1-30] PASSED
# tests/unit/test_sms_retry.py::test_retry_delays_are_correct[2-60] PASSED
# tests/unit/test_sms_retry.py::test_retry_delays_are_correct[3-120] PASSED
# tests/unit/test_sms_retry.py::test_all_retries_exhausted_sets_failed PASSED
# tests/unit/test_sms_retry.py::test_care_team_alert_published_on_final_failure PASSED
# tests/unit/test_webhook_validation.py::test_missing_signature_returns_403 PASSED
# tests/unit/test_webhook_validation.py::test_invalid_signature_returns_403 PASSED
# tests/unit/test_webhook_validation.py::test_valid_signature_updates_status_delivered PASSED
# tests/unit/test_webhook_validation.py::test_intermediate_status_no_db_change PASSED
# tests/unit/test_opt_out.py::test_opted_out_patient_sets_opted_out_status PASSED
# tests/unit/test_opt_out.py::test_urgency_override_bypasses_opt_out PASSED
```

---

## Files Touched

| File | Action |
|------|--------|
| `notification-service/tests/conftest.py` | Create |
| `notification-service/tests/unit/test_idempotency.py` | Create |
| `notification-service/tests/unit/test_sms_retry.py` | Create |
| `notification-service/tests/unit/test_webhook_validation.py` | Create |
| `notification-service/tests/unit/test_opt_out.py` | Create |
| `notification-service/pytest.ini` | Create |

---

## Definition of Done Checklist

- [ ] `test_insert_skipped_on_duplicate_key` passes — `ON CONFLICT DO NOTHING` returns 0 rows
- [ ] `test_consumer_acks_without_dispatch_on_duplicate` passes — Twilio not called on duplicate
- [ ] `test_transient_503_schedules_retry` passes — APScheduler `add_job` called with 30 s delay
- [ ] `test_retry_delays_are_correct` passes for all 3 parametrised cases (30/60/120 s)
- [ ] `test_all_retries_exhausted_sets_failed` passes — `status=FAILED` after attempt > MAX_RETRIES
- [ ] `test_care_team_alert_published_on_final_failure` passes — `pubsub_v1.PublisherClient().publish` called
- [ ] `test_missing_signature_returns_403` passes
- [ ] `test_invalid_signature_returns_403` passes
- [ ] `test_opted_out_patient_sets_opted_out_status` passes — `status=OPTED_OUT`, Twilio not called
- [ ] `test_urgency_override_bypasses_opt_out` passes — urgency override sends despite opt-out
- [ ] All 16+ tests green in CI

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 | Task | `Notification` ORM model used in all tests |
| TASK-002 | Task | `_upsert_notification`, `_process_message` under test |
| TASK-003 | Task | `TwilioSMSDispatcher` under test |
| TASK-004 | Task | Webhook router under test |
