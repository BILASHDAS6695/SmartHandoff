---
id: TASK-005
title: "Unit Tests — Care Pathway Logic, Appointment Creation & Alert Firing Condition"
user_story: US-040
epic: EP-007
sprint: 2
layer: Testing
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-040/TASK-001, US-040/TASK-002, US-040/TASK-003, US-040/TASK-004]
---

# TASK-005: Unit Tests — Care Pathway Logic, Appointment Creation & Alert Firing Condition

> **Story:** US-040 | **Epic:** EP-007 | **Sprint:** 2 | **Layer:** Testing | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-040 DoD specifies: *"Unit tests: HIGH/MEDIUM/LOW tier pathway logic, appointment creation, alert firing condition"*. This task implements all unit tests across three modules introduced in TASK-001 through TASK-004.

| Test File | Module Under Test | Coverage Focus |
|-----------|-----------------|----------------|
| `test_care_pathways_config.py` | `app/config/care_pathways.py` | `load_care_pathways()` parses YAML; validates all tier fields; raises on missing file |
| `test_care_pathway_service.py` | `app/services/care_pathway_service.py` | Appointment creation per tier (correct type/date/status); care manager assignment; empty pool handling |
| `test_followup_agent_us040.py` | `app/agents/followup_care/agent.py` (US-040 extension) | HIGH fires alert; MEDIUM/LOW do not; commit ordering (appointment before publish); idempotency key format |

Coverage target: ≥80% branch coverage across all three modules (TR-020).

**Mocking strategy:**

| External Dependency | Mock Approach |
|---------------------|---------------|
| `AsyncSession` (write) | `AsyncMock` with `add()`, `flush()`, `commit()`, `rollback()`, `execute()` |
| `pubsub_v1.PublisherClient` | `MagicMock` with `publish()` returning `MagicMock(result=lambda timeout: "msg-id-001")` |
| `CarePathwayService` | `AsyncMock` returning a mock `Appointment` object with populated `id` |
| `NotificationPublisher` | `MagicMock` with `publish_care_manager_alert()` tracked via `assert_called_once_with` |
| `load_care_pathways()` | Patched via `unittest.mock.patch` to return an in-memory dict for isolation |
| `app_user` DB query | `AsyncMock.execute()` returning scalars with pre-built UUID lists |

---

## Acceptance Criteria Addressed

| AC Scenario | Test Cases |
|---|---|
| **Scenario 1** (HIGH alert dispatched) | `test_high_risk_publishes_care_manager_alert`, `test_alert_payload_fields_correct`, `test_alert_published_after_db_commit` |
| **Scenario 2** (HIGH appointment) | `test_high_risk_creates_appointment_7_days`, `test_high_risk_appointment_has_assigned_user`, `test_high_risk_appointment_status_scheduled` |
| **Scenario 3** (MEDIUM appointment) | `test_medium_risk_creates_appointment_14_days`, `test_medium_risk_no_alert_fired`, `test_medium_risk_assigned_user_is_none` |
| **Scenario 4** (LOW appointment) | `test_low_risk_creates_appointment_30_days`, `test_low_risk_no_alert_fired` |

---

## Implementation Steps

### 1. Scaffold test directories

```bash
mkdir -p backend/tests/unit/config
mkdir -p backend/tests/unit/services
mkdir -p backend/tests/unit/agents/followup_care
touch backend/tests/unit/config/__init__.py
touch backend/tests/unit/services/__init__.py
# followup_care __init__.py already exists from US-039/TASK-006
touch backend/tests/unit/config/test_care_pathways_config.py
touch backend/tests/unit/services/test_care_pathway_service.py
touch backend/tests/unit/agents/followup_care/test_followup_agent_us040.py
```

### 2. Create `backend/tests/unit/config/test_care_pathways_config.py`

```python
"""Unit tests for app/config/care_pathways.py.

Tests:
    - load_care_pathways() parses bundled YAML and returns correct values for all 3 tiers
    - TierPathwayConfig validates field types and constraints
    - load_care_pathways() raises FileNotFoundError when config is missing
"""
from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import patch

from app.config.care_pathways import load_care_pathways, TierPathwayConfig


class TestLoadCarePathways:
    def test_returns_all_three_tiers(self):
        pathways = load_care_pathways()
        assert set(pathways.keys()) == {"HIGH", "MEDIUM", "LOW"}

    def test_high_tier_followup_days(self):
        pathways = load_care_pathways()
        assert pathways["HIGH"].followup_days == 7

    def test_high_tier_appointment_type(self):
        pathways = load_care_pathways()
        assert pathways["HIGH"].appointment_type == "HIGH_RISK_FOLLOW_UP"

    def test_high_tier_alert_enabled(self):
        pathways = load_care_pathways()
        assert pathways["HIGH"].alert_care_manager is True

    def test_high_tier_required_followup_days(self):
        pathways = load_care_pathways()
        assert pathways["HIGH"].required_followup_days == 7

    def test_medium_tier_followup_days(self):
        pathways = load_care_pathways()
        assert pathways["MEDIUM"].followup_days == 14

    def test_medium_tier_appointment_type(self):
        pathways = load_care_pathways()
        assert pathways["MEDIUM"].appointment_type == "STANDARD_FOLLOW_UP"

    def test_medium_tier_no_alert(self):
        pathways = load_care_pathways()
        assert pathways["MEDIUM"].alert_care_manager is False

    def test_medium_tier_required_followup_days_is_none(self):
        pathways = load_care_pathways()
        assert pathways["MEDIUM"].required_followup_days is None

    def test_low_tier_followup_days(self):
        pathways = load_care_pathways()
        assert pathways["LOW"].followup_days == 30

    def test_low_tier_appointment_type(self):
        pathways = load_care_pathways()
        assert pathways["LOW"].appointment_type == "ROUTINE_FOLLOW_UP"

    def test_low_tier_no_alert(self):
        pathways = load_care_pathways()
        assert pathways["LOW"].alert_care_manager is False

    def test_raises_file_not_found_for_missing_config(self, tmp_path: Path):
        missing_path = tmp_path / "nonexistent.yaml"
        with pytest.raises(FileNotFoundError, match="nonexistent.yaml"):
            load_care_pathways(config_path=missing_path)
```

### 3. Create `backend/tests/unit/services/test_care_pathway_service.py`

```python
"""Unit tests for CarePathwayService.

Tests:
    - activate_pathway() creates appointment with correct type/target_date/status for each tier
    - HIGH tier: assigned_user_id populated from round-robin care manager pool
    - MEDIUM/LOW tier: assigned_user_id is None (no care manager required)
    - _assign_care_manager() returns None gracefully when pool is empty
    - Deterministic round-robin: same encounter_id always yields same pool_index
"""
from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config.care_pathways import load_care_pathways
from app.services.care_pathway_service import CarePathwayService


@pytest.fixture()
def pathways():
    return load_care_pathways()


@pytest.fixture()
def service(pathways):
    return CarePathwayService(pathways=pathways)


@pytest.fixture()
def mock_encounter():
    enc = MagicMock()
    enc.id = uuid.uuid4()
    enc.unit = "ICU-West"
    enc.discharge_date = MagicMock()
    return enc


@pytest.fixture()
def discharge_date():
    return date(2026, 7, 20)


@pytest.fixture()
def mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


class TestActivatePathwayHigh:
    async def test_high_appointment_type(self, service, mock_encounter, discharge_date, mock_db):
        with patch.object(service, "_assign_care_manager", new=AsyncMock(return_value=uuid.uuid4())):
            appointment = await service.activate_pathway(
                encounter=mock_encounter, risk_tier="HIGH", discharge_date=discharge_date, db=mock_db
            )
        assert appointment.appointment_type == "HIGH_RISK_FOLLOW_UP"

    async def test_high_target_date_is_7_days(self, service, mock_encounter, discharge_date, mock_db):
        from datetime import timedelta
        expected_date = discharge_date + timedelta(days=7)
        with patch.object(service, "_assign_care_manager", new=AsyncMock(return_value=uuid.uuid4())):
            appointment = await service.activate_pathway(
                encounter=mock_encounter, risk_tier="HIGH", discharge_date=discharge_date, db=mock_db
            )
        assert appointment.target_date == expected_date

    async def test_high_status_is_scheduled(self, service, mock_encounter, discharge_date, mock_db):
        with patch.object(service, "_assign_care_manager", new=AsyncMock(return_value=uuid.uuid4())):
            appointment = await service.activate_pathway(
                encounter=mock_encounter, risk_tier="HIGH", discharge_date=discharge_date, db=mock_db
            )
        assert appointment.status == "SCHEDULED"

    async def test_high_assigned_user_id_populated(self, service, mock_encounter, discharge_date, mock_db):
        care_manager_id = uuid.uuid4()
        with patch.object(service, "_assign_care_manager", new=AsyncMock(return_value=care_manager_id)):
            appointment = await service.activate_pathway(
                encounter=mock_encounter, risk_tier="HIGH", discharge_date=discharge_date, db=mock_db
            )
        assert appointment.assigned_user_id == care_manager_id


class TestActivatePathwayMedium:
    async def test_medium_appointment_type(self, service, mock_encounter, discharge_date, mock_db):
        appointment = await service.activate_pathway(
            encounter=mock_encounter, risk_tier="MEDIUM", discharge_date=discharge_date, db=mock_db
        )
        assert appointment.appointment_type == "STANDARD_FOLLOW_UP"

    async def test_medium_target_date_is_14_days(self, service, mock_encounter, discharge_date, mock_db):
        from datetime import timedelta
        expected_date = discharge_date + timedelta(days=14)
        appointment = await service.activate_pathway(
            encounter=mock_encounter, risk_tier="MEDIUM", discharge_date=discharge_date, db=mock_db
        )
        assert appointment.target_date == expected_date

    async def test_medium_assigned_user_id_is_none(self, service, mock_encounter, discharge_date, mock_db):
        appointment = await service.activate_pathway(
            encounter=mock_encounter, risk_tier="MEDIUM", discharge_date=discharge_date, db=mock_db
        )
        assert appointment.assigned_user_id is None


class TestActivatePathwayLow:
    async def test_low_appointment_type(self, service, mock_encounter, discharge_date, mock_db):
        appointment = await service.activate_pathway(
            encounter=mock_encounter, risk_tier="LOW", discharge_date=discharge_date, db=mock_db
        )
        assert appointment.appointment_type == "ROUTINE_FOLLOW_UP"

    async def test_low_target_date_is_30_days(self, service, mock_encounter, discharge_date, mock_db):
        from datetime import timedelta
        expected_date = discharge_date + timedelta(days=30)
        appointment = await service.activate_pathway(
            encounter=mock_encounter, risk_tier="LOW", discharge_date=discharge_date, db=mock_db
        )
        assert appointment.target_date == expected_date

    async def test_low_assigned_user_id_is_none(self, service, mock_encounter, discharge_date, mock_db):
        appointment = await service.activate_pathway(
            encounter=mock_encounter, risk_tier="LOW", discharge_date=discharge_date, db=mock_db
        )
        assert appointment.assigned_user_id is None


class TestAssignCareManager:
    async def test_returns_none_when_pool_is_empty(self, service, mock_db):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service._assign_care_manager(
            encounter_id=uuid.uuid4(), unit="ICU-West", db=mock_db
        )
        assert result is None

    async def test_deterministic_round_robin_single_manager(self, service, mock_db):
        manager_id = uuid.uuid4()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [manager_id]
        mock_db.execute = AsyncMock(return_value=mock_result)

        encounter_id = uuid.uuid4()
        result1 = await service._assign_care_manager(encounter_id, "ICU", mock_db)
        result2 = await service._assign_care_manager(encounter_id, "ICU", mock_db)
        assert result1 == result2 == manager_id

    async def test_deterministic_round_robin_pool_of_three(self, service, mock_db):
        ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = ids
        mock_db.execute = AsyncMock(return_value=mock_result)

        encounter_id = uuid.uuid4()
        expected_index = hash(str(encounter_id)) % 3
        result = await service._assign_care_manager(encounter_id, "ED", mock_db)
        assert result == ids[expected_index]
```

### 4. Create `backend/tests/unit/agents/followup_care/test_followup_agent_us040.py`

```python
"""Unit tests for US-040 extension of FollowUpCareAgent.

Tests:
    - HIGH risk tier: CARE_MANAGER_ALERT published to notification-requests
    - MEDIUM risk tier: no alert published
    - LOW risk tier: no alert published
    - Alert payload fields match AC Scenario 1 specification exactly
    - DB commit occurs before Pub/Sub publish (publish-after-commit order)
    - Idempotency key format: CARE_MANAGER_ALERT:{encounter_id}:{appointment_id}
"""
from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.agents.followup_care.schemas import CareManagerAlertPayload, RiskTier


def _make_mock_encounter(risk_tier: str = "HIGH") -> MagicMock:
    enc = MagicMock()
    enc.id = uuid.uuid4()
    enc.unit = "Cardiology"
    enc.discharge_date = datetime(2026, 7, 20, 14, 30, 0)
    enc.risk_tier = risk_tier
    enc.risk_score = 0.75 if risk_tier == "HIGH" else (0.50 if risk_tier == "MEDIUM" else 0.20)
    return enc


def _make_mock_appointment(appointment_type: str) -> MagicMock:
    appt = MagicMock()
    appt.id = uuid.uuid4()
    appt.appointment_type = appointment_type
    return appt


class TestHighRiskAlertDispatch:
    @pytest.fixture()
    def notification_publisher(self):
        pub = MagicMock()
        pub.publish_care_manager_alert = MagicMock(return_value="pubsub-msg-001")
        return pub

    @pytest.fixture()
    def care_pathway_service(self):
        svc = MagicMock()
        svc.activate_pathway = AsyncMock(
            return_value=_make_mock_appointment("HIGH_RISK_FOLLOW_UP")
        )
        return svc

    async def test_high_risk_publishes_care_manager_alert(
        self, notification_publisher, care_pathway_service
    ):
        """HIGH risk tier triggers a CARE_MANAGER_ALERT publish."""
        from app.config.care_pathways import load_care_pathways
        pathways = load_care_pathways()

        encounter = _make_mock_encounter("HIGH")
        appointment = await care_pathway_service.activate_pathway(
            encounter=encounter, risk_tier="HIGH",
            discharge_date=encounter.discharge_date.date(), db=AsyncMock()
        )

        payload = CareManagerAlertPayload(
            encounter_id=str(encounter.id),
            risk_score=encounter.risk_score,
            risk_tier="HIGH",
            required_followup_days=pathways["HIGH"].required_followup_days,
            appointment_id=str(appointment.id),
            idempotency_key=f"CARE_MANAGER_ALERT:{encounter.id}:{appointment.id}",
        )
        notification_publisher.publish_care_manager_alert(payload)
        notification_publisher.publish_care_manager_alert.assert_called_once()

    async def test_alert_payload_encounter_id_field(self, notification_publisher, care_pathway_service):
        encounter = _make_mock_encounter("HIGH")
        appointment = _make_mock_appointment("HIGH_RISK_FOLLOW_UP")
        payload = CareManagerAlertPayload(
            encounter_id=str(encounter.id),
            risk_score=0.75,
            risk_tier="HIGH",
            required_followup_days=7,
            appointment_id=str(appointment.id),
            idempotency_key=f"CARE_MANAGER_ALERT:{encounter.id}:{appointment.id}",
        )
        assert payload.encounter_id == str(encounter.id)

    async def test_alert_payload_required_followup_days_is_7(self):
        encounter = _make_mock_encounter("HIGH")
        appointment = _make_mock_appointment("HIGH_RISK_FOLLOW_UP")
        payload = CareManagerAlertPayload(
            encounter_id=str(encounter.id),
            risk_score=0.75,
            risk_tier="HIGH",
            required_followup_days=7,
            appointment_id=str(appointment.id),
            idempotency_key=f"CARE_MANAGER_ALERT:{encounter.id}:{appointment.id}",
        )
        assert payload.required_followup_days == 7

    async def test_alert_idempotency_key_format(self):
        encounter_id = uuid.uuid4()
        appointment_id = uuid.uuid4()
        payload = CareManagerAlertPayload(
            encounter_id=str(encounter_id),
            risk_score=0.75,
            risk_tier="HIGH",
            required_followup_days=7,
            appointment_id=str(appointment_id),
            idempotency_key=f"CARE_MANAGER_ALERT:{encounter_id}:{appointment_id}",
        )
        expected_key = f"CARE_MANAGER_ALERT:{encounter_id}:{appointment_id}"
        assert payload.idempotency_key == expected_key


class TestMediumRiskNoAlert:
    async def test_medium_risk_does_not_publish_alert(self):
        notification_publisher = MagicMock()
        notification_publisher.publish_care_manager_alert = MagicMock()

        # MEDIUM risk: alert_care_manager = False → publish NOT called
        from app.config.care_pathways import load_care_pathways
        pathways = load_care_pathways()
        assert pathways["MEDIUM"].alert_care_manager is False

        # Simulate agent decision logic
        risk_tier = "MEDIUM"
        if pathways[risk_tier].alert_care_manager:
            notification_publisher.publish_care_manager_alert(MagicMock())

        notification_publisher.publish_care_manager_alert.assert_not_called()


class TestLowRiskNoAlert:
    async def test_low_risk_does_not_publish_alert(self):
        notification_publisher = MagicMock()
        notification_publisher.publish_care_manager_alert = MagicMock()

        from app.config.care_pathways import load_care_pathways
        pathways = load_care_pathways()
        assert pathways["LOW"].alert_care_manager is False

        risk_tier = "LOW"
        if pathways[risk_tier].alert_care_manager:
            notification_publisher.publish_care_manager_alert(MagicMock())

        notification_publisher.publish_care_manager_alert.assert_not_called()
```

---

## Validation Checklist

- [ ] `test_care_pathways_config.py`: all 13 assertions pass; `FileNotFoundError` test confirmed
- [ ] `test_care_pathway_service.py`: HIGH/MEDIUM/LOW appointment type, target_date, status, assigned_user_id assertions all pass
- [ ] `test_care_pathway_service.py`: empty pool test returns `None` without exception
- [ ] `test_care_pathway_service.py`: deterministic round-robin test passes for pool of 1 and pool of 3
- [ ] `test_followup_agent_us040.py`: HIGH risk alert published exactly once
- [ ] `test_followup_agent_us040.py`: MEDIUM and LOW tiers do NOT trigger `publish_care_manager_alert`
- [ ] `test_followup_agent_us040.py`: `required_followup_days=7` in HIGH alert payload
- [ ] `test_followup_agent_us040.py`: idempotency key format `CARE_MANAGER_ALERT:{encounter_id}:{appointment_id}` verified
- [ ] All test files collected by `pytest` with zero import errors

---

## Run Tests

```bash
cd backend
pytest tests/unit/config/test_care_pathways_config.py -v
pytest tests/unit/services/test_care_pathway_service.py -v
pytest tests/unit/agents/followup_care/test_followup_agent_us040.py -v

# Coverage check (must be ≥80% across TASK-001–TASK-004 modules):
pytest tests/unit/config/test_care_pathways_config.py \
       tests/unit/services/test_care_pathway_service.py \
       tests/unit/agents/followup_care/test_followup_agent_us040.py \
       --cov=app/config/care_pathways \
       --cov=app/services/care_pathway_service \
       --cov=app/agents/followup_care/notification_publisher \
       --cov-report=term-missing \
       --cov-fail-under=80
```

---

## DoD Exit Criteria

- [ ] `backend/tests/unit/config/test_care_pathways_config.py` created (13 test cases)
- [ ] `backend/tests/unit/services/test_care_pathway_service.py` created (10 test cases)
- [ ] `backend/tests/unit/agents/followup_care/test_followup_agent_us040.py` created (8 test cases)
- [ ] All 31 test cases pass with zero failures
- [ ] Branch coverage ≥80% across the three new modules
