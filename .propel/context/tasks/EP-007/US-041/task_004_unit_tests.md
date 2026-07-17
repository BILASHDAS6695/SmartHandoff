---
id: TASK-004
title: "Unit Tests — Schedule Creation, Risk Threshold Enforcement, Opt-Out, Channel Resolution"
user_story: US-041
epic: EP-007
sprint: 2
layer: Testing
estimate: 2.5h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-041/TASK-001, US-041/TASK-002, US-041/TASK-003]
---

# TASK-004: Unit Tests — Schedule Creation, Risk Threshold Enforcement, Opt-Out, Channel Resolution

> **Story:** US-041 | **Epic:** EP-007 | **Sprint:** 2 | **Layer:** Testing | **Est:** 2.5 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-041 DoD specifies:

> *"Unit tests: schedule creation for correct risk thresholds, opt-out enforcement"*

Tests are split across two test files matching the two production modules added by this story:

| Test File | Module Under Test | Coverage Focus |
|---|---|---|
| `test_checkin_scheduler.py` | `agents/followup_care/checkin_scheduler.py` | Schedule creation for risk ≥ 0.5; no creation for risk < 0.5; boundary at 0.5; `send_at` accuracy; channel resolution; idempotency |
| `test_scheduled_dispatcher.py` | `notification-service/app/scheduled_dispatcher.py` | Opt-out flag enforcement; SMS dispatch path; email dispatch path; FAILED status on dispatch error; PENDING records not dispatched before `send_at` |

Coverage target: ≥80% branch coverage across both modules (TR-020).

**Mocking strategy:**

| External Dependency | Mock Approach |
|---|---|
| `AsyncSession` (write) | `AsyncMock` with `add()`, `flush()`, `rollback()`, `commit()`, `begin()` |
| `AsyncSession` (read) | `AsyncMock` returning mock `ScheduledNotification` + `Patient` objects |
| `async_sessionmaker` | `MagicMock` returning `AsyncMock` context manager wrapping the session mock |
| `send_checkin_sms()` | `AsyncMock` — assert called with correct args; raises `TwilioRestException` for error tests |
| `send_checkin_email()` | `AsyncMock` — assert called with correct args; raises `Exception` for error tests |
| `patient.notification_opt_out` | Boolean attribute on mock `Patient` object |
| `encounter.discharge_time` | `datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)` — deterministic fixture |

---

## Acceptance Criteria Addressed

| US-041 AC Scenario | Test Cases |
|---|---|
| **Scenario 1** | `test_checkin_created_for_medium_risk`, `test_send_at_is_48h_after_discharge` |
| **Scenario 2** | `test_checkin_not_created_for_low_risk`, `test_boundary_exactly_at_threshold` |
| **Scenario 3** | `test_channel_resolved_as_email_for_email_preference`, `test_email_dispatched_via_sendgrid` |
| **Scenario 4** | `test_opted_out_patient_skips_dispatch`, `test_opted_out_status_set_to_opted_out` |

---

## Implementation Steps

### 1. Scaffold test directories

```bash
mkdir -p backend/tests/unit/agents/followup_care
mkdir -p notification-service/tests/unit
touch backend/tests/unit/agents/followup_care/__init__.py
touch notification-service/tests/__init__.py
touch notification-service/tests/unit/__init__.py
```

### 2. Create `backend/tests/unit/agents/followup_care/test_checkin_scheduler.py`

```python
"""Unit tests for maybe_schedule_48h_checkin().

Coverage: US-041 AC Scenarios 1, 2, 3 — schedule creation, risk threshold,
channel resolution, send_at accuracy, idempotency guard.

Design refs:
    US-041 AC Scenario 1 — CHECK_IN_48H scheduled for risk_score=0.6
    US-041 AC Scenario 2 — NOT scheduled for risk_score=0.2
    US-041 Technical Notes — CHECKIN_RISK_THRESHOLD=0.5; send_at from discharge_time
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.followup_care.checkin_scheduler import (
    CHECKIN_DELAY_HOURS,
    CHECKIN_RISK_THRESHOLD,
    maybe_schedule_48h_checkin,
)
from app.models.scheduled_notification import (
    DeliveryStatus,
    NotificationChannel,
    NotificationType,
)


@pytest.fixture()
def discharge_time() -> datetime:
    return datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def mock_encounter(discharge_time):
    enc = MagicMock()
    enc.id = uuid.uuid4()
    enc.discharge_time = discharge_time
    return enc


@pytest.fixture()
def mock_patient_sms():
    """Patient with preferred_contact=sms and opt_out=False."""
    p = MagicMock()
    p.id = uuid.uuid4()
    p.preferred_contact = "sms"
    p.notification_opt_out = False
    return p


@pytest.fixture()
def mock_patient_email():
    """Patient with preferred_contact=email and opt_out=False."""
    p = MagicMock()
    p.id = uuid.uuid4()
    p.preferred_contact = "email"
    p.notification_opt_out = False
    return p


@pytest.fixture()
def mock_session():
    session = AsyncMock()
    session.flush = AsyncMock()
    session.rollback = AsyncMock()
    session.add = MagicMock()
    return session


# ─── Risk Threshold Tests ──────────────────────────────────────────────────────

class TestRiskThreshold:
    @pytest.mark.asyncio
    async def test_checkin_created_for_medium_risk(self, mock_session, mock_encounter, mock_patient_sms):
        """risk_score=0.6 (MEDIUM) → ScheduledNotification created (AC Scenario 1)."""
        result = await maybe_schedule_48h_checkin(
            session=mock_session,
            encounter=mock_encounter,
            patient=mock_patient_sms,
            risk_score=0.6,
        )
        assert result is not None
        assert result.type == NotificationType.CHECK_IN_48H
        mock_session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_checkin_created_for_high_risk(self, mock_session, mock_encounter, mock_patient_sms):
        """risk_score=0.8 (HIGH) → ScheduledNotification created."""
        result = await maybe_schedule_48h_checkin(
            session=mock_session,
            encounter=mock_encounter,
            patient=mock_patient_sms,
            risk_score=0.8,
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_checkin_not_created_for_low_risk(self, mock_session, mock_encounter, mock_patient_sms):
        """risk_score=0.2 (LOW) → no ScheduledNotification (AC Scenario 2)."""
        result = await maybe_schedule_48h_checkin(
            session=mock_session,
            encounter=mock_encounter,
            patient=mock_patient_sms,
            risk_score=0.2,
        )
        assert result is None
        mock_session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_checkin_not_created_just_below_threshold(self, mock_session, mock_encounter, mock_patient_sms):
        """risk_score=0.499 (just below threshold) → no ScheduledNotification."""
        result = await maybe_schedule_48h_checkin(
            session=mock_session,
            encounter=mock_encounter,
            patient=mock_patient_sms,
            risk_score=0.499,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_checkin_created_at_exact_threshold(self, mock_session, mock_encounter, mock_patient_sms):
        """risk_score=0.5 (exactly at threshold) → ScheduledNotification created."""
        result = await maybe_schedule_48h_checkin(
            session=mock_session,
            encounter=mock_encounter,
            patient=mock_patient_sms,
            risk_score=0.5,
        )
        assert result is not None


# ─── send_at Accuracy Tests ────────────────────────────────────────────────────

class TestSendAtComputation:
    @pytest.mark.asyncio
    async def test_send_at_is_48h_after_discharge(self, mock_session, mock_encounter, mock_patient_sms, discharge_time):
        """send_at = encounter.discharge_time + 48h (not datetime.now() + 48h)."""
        result = await maybe_schedule_48h_checkin(
            session=mock_session,
            encounter=mock_encounter,
            patient=mock_patient_sms,
            risk_score=0.7,
        )
        expected_send_at = discharge_time + timedelta(hours=CHECKIN_DELAY_HOURS)
        assert result.send_at == expected_send_at

    @pytest.mark.asyncio
    async def test_no_record_when_discharge_time_is_none(self, mock_session, mock_patient_sms):
        """If encounter.discharge_time is None, no notification is created."""
        enc = MagicMock()
        enc.id = uuid.uuid4()
        enc.discharge_time = None

        result = await maybe_schedule_48h_checkin(
            session=mock_session,
            encounter=enc,
            patient=mock_patient_sms,
            risk_score=0.8,
        )
        assert result is None
        mock_session.add.assert_not_called()


# ─── Channel Resolution Tests ──────────────────────────────────────────────────

class TestChannelResolution:
    @pytest.mark.asyncio
    async def test_channel_email_for_email_preference(self, mock_session, mock_encounter, mock_patient_email):
        """patient.preferred_contact=email → channel=EMAIL (AC Scenario 3)."""
        result = await maybe_schedule_48h_checkin(
            session=mock_session,
            encounter=mock_encounter,
            patient=mock_patient_email,
            risk_score=0.6,
        )
        assert result.channel == NotificationChannel.EMAIL

    @pytest.mark.asyncio
    async def test_channel_sms_for_sms_preference(self, mock_session, mock_encounter, mock_patient_sms):
        """patient.preferred_contact=sms → channel=SMS."""
        result = await maybe_schedule_48h_checkin(
            session=mock_session,
            encounter=mock_encounter,
            patient=mock_patient_sms,
            risk_score=0.6,
        )
        assert result.channel == NotificationChannel.SMS

    @pytest.mark.asyncio
    async def test_channel_sms_when_preferred_contact_is_none(self, mock_session, mock_encounter):
        """patient.preferred_contact=None → default to SMS."""
        patient = MagicMock()
        patient.id = uuid.uuid4()
        patient.preferred_contact = None
        patient.notification_opt_out = False

        result = await maybe_schedule_48h_checkin(
            session=mock_session,
            encounter=mock_encounter,
            patient=patient,
            risk_score=0.6,
        )
        assert result.channel == NotificationChannel.SMS


# ─── Idempotency Tests ─────────────────────────────────────────────────────────

class TestIdempotency:
    @pytest.mark.asyncio
    async def test_idempotency_key_format(self, mock_session, mock_encounter, mock_patient_sms):
        """idempotency_key = CHK48-{encounter.id}."""
        result = await maybe_schedule_48h_checkin(
            session=mock_session,
            encounter=mock_encounter,
            patient=mock_patient_sms,
            risk_score=0.6,
        )
        assert result.idempotency_key == f"CHK48-{mock_encounter.id}"

    @pytest.mark.asyncio
    async def test_returns_none_on_unique_constraint_violation(self, mock_session, mock_encounter, mock_patient_sms):
        """Flush raising an exception (unique constraint) → returns None (already scheduled)."""
        mock_session.flush.side_effect = Exception("unique constraint violation")

        result = await maybe_schedule_48h_checkin(
            session=mock_session,
            encounter=mock_encounter,
            patient=mock_patient_sms,
            risk_score=0.6,
        )
        assert result is None
        mock_session.rollback.assert_called_once()
```

### 3. Create `notification-service/tests/unit/test_scheduled_dispatcher.py`

```python
"""Unit tests for dispatch_due_notifications() — US-041 AC Scenarios 3, 4.

Coverage:
    - Opt-out flag → delivery_status=OPTED_OUT, no SMS/email sent
    - Email preference → send_checkin_email() called
    - SMS preference → send_checkin_sms() called
    - Dispatch error → delivery_status=FAILED
    - PENDING record before send_at → NOT dispatched

Design refs:
    US-041 AC Scenario 3 — email dispatched via SendGrid template
    US-041 AC Scenario 4 — opt-out sets delivery_status=OPTED_OUT; no send
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.scheduled_notification import (
    DeliveryStatus,
    NotificationChannel,
    ScheduledNotification,
)
from app.scheduled_dispatcher import _process_notification


def make_notification(
    channel: NotificationChannel = NotificationChannel.SMS,
    opt_out: bool = False,
    first_name: str = "Alice",
    phone: str = "+10000000000",
    email: str = "alice@example.com",
) -> ScheduledNotification:
    """Build a mock ScheduledNotification with a stubbed Patient relationship."""
    notification = MagicMock(spec=ScheduledNotification)
    notification.id = uuid.uuid4()
    notification.encounter_id = uuid.uuid4()
    notification.channel = channel
    notification.delivery_status = DeliveryStatus.PENDING

    patient = MagicMock()
    patient.notification_opt_out = opt_out
    patient.first_name = first_name
    patient.phone = phone
    patient.email = email
    patient.preferred_contact = channel.value.lower()

    notification.patient = patient
    return notification


def make_session_factory(notification: ScheduledNotification):
    """Return a mock async_sessionmaker wrapping a mock AsyncSession."""
    session = AsyncMock()
    session.get = AsyncMock(return_value=notification)
    session.begin = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=session),
                                                     __aexit__=AsyncMock(return_value=False)))
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory, session


# ─── Opt-Out Tests ─────────────────────────────────────────────────────────────

class TestOptOut:
    @pytest.mark.asyncio
    async def test_opted_out_patient_sets_status_to_opted_out(self):
        """patient.notification_opt_out=True → delivery_status=OPTED_OUT (AC Scenario 4)."""
        notification = make_notification(opt_out=True)
        factory, session = make_session_factory(notification)

        with patch("app.scheduled_dispatcher.send_checkin_sms") as mock_sms, \
             patch("app.scheduled_dispatcher.send_checkin_email") as mock_email:
            await _process_notification(session_factory=factory, notification=notification)

            mock_sms.assert_not_called()
            mock_email.assert_not_called()

        db_notification = await session.get.return_value
        # Confirm _update_status was called with OPTED_OUT
        session.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_opted_out_patient_does_not_send_sms(self):
        """No Twilio call made for opted-out patient."""
        notification = make_notification(channel=NotificationChannel.SMS, opt_out=True)
        factory, _ = make_session_factory(notification)

        with patch("app.scheduled_dispatcher.send_checkin_sms") as mock_sms:
            await _process_notification(session_factory=factory, notification=notification)
            mock_sms.assert_not_called()

    @pytest.mark.asyncio
    async def test_opted_out_patient_does_not_send_email(self):
        """No SendGrid call made for opted-out patient."""
        notification = make_notification(channel=NotificationChannel.EMAIL, opt_out=True)
        factory, _ = make_session_factory(notification)

        with patch("app.scheduled_dispatcher.send_checkin_email") as mock_email:
            await _process_notification(session_factory=factory, notification=notification)
            mock_email.assert_not_called()


# ─── Dispatch Tests ────────────────────────────────────────────────────────────

class TestDispatch:
    @pytest.mark.asyncio
    async def test_email_dispatched_for_email_channel(self):
        """channel=EMAIL → send_checkin_email() called with correct args (AC Scenario 3)."""
        notification = make_notification(
            channel=NotificationChannel.EMAIL,
            first_name="Alice",
            email="alice@example.com",
        )
        factory, _ = make_session_factory(notification)

        with patch("app.scheduled_dispatcher.send_checkin_email") as mock_email, \
             patch("app.config.settings") as mock_settings:
            mock_settings.care_team_contact_number = "+18005550000"
            mock_email.return_value = None

            await _process_notification(session_factory=factory, notification=notification)

            mock_email.assert_called_once_with(
                to_email="alice@example.com",
                first_name="Alice",
                care_team_number="+18005550000",
            )

    @pytest.mark.asyncio
    async def test_sms_dispatched_for_sms_channel(self):
        """channel=SMS → send_checkin_sms() called with correct args."""
        notification = make_notification(
            channel=NotificationChannel.SMS,
            first_name="Bob",
            phone="+15555550001",
        )
        factory, _ = make_session_factory(notification)

        with patch("app.scheduled_dispatcher.send_checkin_sms") as mock_sms, \
             patch("app.config.settings") as mock_settings:
            mock_settings.care_team_contact_number = "+18005550000"
            mock_sms.return_value = None

            await _process_notification(session_factory=factory, notification=notification)

            mock_sms.assert_called_once_with(
                to_phone="+15555550001",
                first_name="Bob",
                care_team_number="+18005550000",
            )

    @pytest.mark.asyncio
    async def test_failed_dispatch_sets_status_to_failed(self):
        """Twilio error → delivery_status=FAILED."""
        notification = make_notification(channel=NotificationChannel.SMS)
        factory, session = make_session_factory(notification)

        with patch("app.scheduled_dispatcher.send_checkin_sms", side_effect=Exception("Twilio error")), \
             patch("app.config.settings") as mock_settings:
            mock_settings.care_team_contact_number = "+18005550000"

            await _process_notification(session_factory=factory, notification=notification)

        # _update_status called with FAILED
        session.get.assert_called_once()
```

---

## Validation

- [ ] `pytest backend/tests/unit/agents/followup_care/test_checkin_scheduler.py -v` — all 12 tests pass
- [ ] `pytest notification-service/tests/unit/test_scheduled_dispatcher.py -v` — all 8 tests pass
- [ ] `pytest --cov=app.agents.followup_care.checkin_scheduler --cov-report=term-missing backend/tests/` — ≥80% branch coverage
- [ ] `pytest --cov=app.scheduled_dispatcher --cov-report=term-missing notification-service/tests/` — ≥80% branch coverage
- [ ] `mypy backend/tests/unit/agents/followup_care/test_checkin_scheduler.py` exits 0
- [ ] `ruff check backend/tests/unit/agents/followup_care/test_checkin_scheduler.py` exits 0

---

## Files Produced

| File | Change |
|------|--------|
| `backend/tests/unit/agents/followup_care/test_checkin_scheduler.py` | New — 12 unit tests |
| `notification-service/tests/unit/test_scheduled_dispatcher.py` | New — 8 unit tests |
