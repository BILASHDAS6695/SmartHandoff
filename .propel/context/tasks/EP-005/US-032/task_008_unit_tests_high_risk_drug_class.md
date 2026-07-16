---
id: TASK-008
title: "Unit Tests — HighRiskDrugClassDetector, Alert Resolution RBAC, SLA Monitor"
user_story: US-032
epic: EP-005
sprint: 2
layer: Quality Assurance
estimate: 4h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-032/TASK-002, US-032/TASK-005, US-032/TASK-006, US-032/TASK-007]
---

# TASK-008: Unit Tests — HighRiskDrugClassDetector, Alert Resolution RBAC, SLA Monitor

> **Story:** US-032 | **Epic:** EP-005 | **Sprint:** 2 | **Layer:** Quality Assurance | **Est:** 4 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-032 DoD requires unit tests covering:
- Each high-risk drug class detection (AC Scenario 1)
- RBAC enforcement on the resolve endpoint (AC Scenario 4)
- SLA breach detection (AC Scenario 3)

All tests use `pytest` + `pytest-asyncio` + `unittest.mock`. No real database or Pub/Sub connections — external dependencies are mocked.

**Design references:**
- US-032 AC Scenarios 1, 3, 4
- design.md §4.1 — FastAPI; SQLAlchemy async; Pydantic v2
- `.github/instructions/unit-testing-standards.instructions.md`

---

## Acceptance Criteria Addressed

| US-032 AC | Coverage |
|-----------|----------|
| **Scenario 1** | Parametrised tests for all four drug classes |
| **Scenario 3** | SLA breach detection and idempotency |
| **Scenario 4** | 403 RBAC enforcement; 200 for pharmacist |
| **DoD** | Unit tests: each high-risk class, RBAC enforcement, SLA breach |

---

## Implementation Steps

### 1. Create `backend/tests/unit/test_high_risk_drug_class_detector.py`

```python
"""Unit tests for HighRiskDrugClassDetector.

Design refs:
    US-032 AC Scenario 1 — detection per drug class
    US-032 Technical Notes — case-insensitive; dose-stripped matching
"""
from __future__ import annotations

import pytest

from app.agents.medication_reconciliation.drug_interaction.checker import (
    DischargedMedication,
)
from app.agents.medication_reconciliation.high_risk.detector import (
    HighRiskDrugClassDetector,
)
from app.agents.medication_reconciliation.high_risk.config_loader import (
    HighRiskDrugConfig,
)
from pathlib import Path

# Use the real YAML config for integration-style unit tests
_REAL_CONFIG = HighRiskDrugConfig(
    Path(__file__).parents[3] / "config" / "high_risk_drugs.yaml"
)


@pytest.fixture
def detector() -> HighRiskDrugClassDetector:
    return HighRiskDrugClassDetector(config=_REAL_CONFIG)


@pytest.mark.parametrize(
    "drug_name, expected_class",
    [
        # ANTICOAGULANT
        ("Warfarin 5mg", "ANTICOAGULANT"),
        ("Heparin 5000 Units/mL", "ANTICOAGULANT"),
        ("Enoxaparin 40mg", "ANTICOAGULANT"),
        ("Rivaroxaban 20mg", "ANTICOAGULANT"),
        # INSULIN
        ("Insulin Glargine 100 Units/mL", "INSULIN"),
        ("Insulin Aspart 10 Units", "INSULIN"),
        ("Insulin NPH 70/30", "INSULIN"),
        # OPIOID
        ("Oxycodone 10mg ER", "OPIOID"),
        ("Hydrocodone 5mg", "OPIOID"),
        ("Morphine Sulfate 15mg", "OPIOID"),
        ("Fentanyl 25mcg patch", "OPIOID"),
        # CHEMOTHERAPY
        ("Methotrexate 2.5mg", "CHEMOTHERAPY"),
        ("Cyclophosphamide 50mg", "CHEMOTHERAPY"),
    ],
)
def test_detects_high_risk_drug_class(
    detector: HighRiskDrugClassDetector, drug_name: str, expected_class: str
) -> None:
    """Each high-risk drug name must match the correct ISMP class."""
    meds = [DischargedMedication(rxcui="00000", drug_name=drug_name)]
    matches = detector.detect(meds)
    assert len(matches) == 1
    assert matches[0].drug_class == expected_class
    assert matches[0].severity == "HIGH"


def test_non_high_risk_drug_returns_no_match(
    detector: HighRiskDrugClassDetector,
) -> None:
    """Non-high-risk drugs must not trigger a detection."""
    meds = [DischargedMedication(rxcui="00001", drug_name="Amoxicillin 500mg")]
    assert detector.detect(meds) == []


def test_detection_is_case_insensitive(detector: HighRiskDrugClassDetector) -> None:
    """Drug name matching must be case-insensitive."""
    meds = [DischargedMedication(rxcui="00002", drug_name="WARFARIN 5MG")]
    matches = detector.detect(meds)
    assert len(matches) == 1
    assert matches[0].drug_class == "ANTICOAGULANT"


def test_multiple_high_risk_drugs_returns_multiple_matches(
    detector: HighRiskDrugClassDetector,
) -> None:
    """A list with multiple high-risk drugs must return one match per drug."""
    meds = [
        DischargedMedication(rxcui="11289", drug_name="Warfarin 5mg"),
        DischargedMedication(rxcui="7804", drug_name="Oxycodone 10mg"),
    ]
    matches = detector.detect(meds)
    assert len(matches) == 2
    classes = {m.drug_class for m in matches}
    assert classes == {"ANTICOAGULANT", "OPIOID"}


def test_dose_stripped_before_matching(detector: HighRiskDrugClassDetector) -> None:
    """Dose tokens must be stripped before lookup."""
    # "morphine 15 mg" after stripping → "morphine"
    meds = [DischargedMedication(rxcui="7052", drug_name="morphine 15 mg")]
    matches = detector.detect(meds)
    assert len(matches) == 1
    assert matches[0].normalised_name == "morphine"


def test_empty_medication_list_returns_empty(
    detector: HighRiskDrugClassDetector,
) -> None:
    """Empty input list must return an empty result."""
    assert detector.detect([]) == []
```

### 2. Create `backend/tests/unit/test_alert_resolve_endpoint.py`

```python
"""Unit tests for PATCH /api/v1/alerts/{id}/resolve endpoint.

Tests RBAC enforcement and resolution workflow.

Design refs:
    US-032 AC Scenario 2 — successful pharmacist resolution
    US-032 AC Scenario 4 — 403 for non-pharmacist role
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


def _make_alert(status: str = "ACTIVE") -> MagicMock:
    alert = MagicMock()
    alert.id = uuid.uuid4()
    alert.encounter_id = uuid.uuid4()
    alert.alert_type = "HIGH_RISK_DRUG_CLASS"
    alert.severity = "HIGH"
    alert.status = status
    alert.drug_class = "ANTICOAGULANT"
    alert.drug_name = "Warfarin"
    alert.drug_pair = None
    alert.interaction_description = None
    alert.source = "SYSTEM"
    alert.sla_breached = False
    alert.resolved_by_user_id = None
    alert.resolved_at = None
    alert.resolution_type = None
    alert.created_at = datetime.now(timezone.utc)
    return alert


@pytest.fixture
def pharmacist_headers() -> dict[str, str]:
    """JWT header with PHARMACIST role (mocked by test auth override)."""
    return {"Authorization": "Bearer pharmacist-test-token"}


@pytest.fixture
def nurse_headers() -> dict[str, str]:
    """JWT header with NURSE role."""
    return {"Authorization": "Bearer nurse-test-token"}


def test_pharmacist_can_resolve_active_alert(pharmacist_headers: dict) -> None:
    """AC Scenario 2: Pharmacist resolves an ACTIVE alert → 200, status=RESOLVED."""
    alert = _make_alert(status="ACTIVE")

    with (
        patch("app.routers.alerts.get_db_session") as mock_db,
        patch("app.routers.alerts.require_role") as mock_rbac,
        patch("app.routers.alerts.publish_message", new_callable=AsyncMock),
    ):
        mock_session = AsyncMock()
        mock_session.get.return_value = alert
        mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_rbac.return_value = lambda: MagicMock(id=uuid.uuid4(), role="PHARMACIST")

        with TestClient(app) as client:
            response = client.patch(
                f"/api/v1/alerts/{alert.id}/resolve",
                json={"resolution_type": "REVIEWED_ACCEPTABLE", "resolution_note": "Reviewed OK"},
                headers=pharmacist_headers,
            )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "RESOLVED"
    assert data["resolution_type"] == "REVIEWED_ACCEPTABLE"
    assert data["resolved_at"] is not None
    assert data["resolved_by_user_id"] is not None


def test_nurse_cannot_resolve_alert(nurse_headers: dict) -> None:
    """AC Scenario 4: Nurse JWT → 403 Forbidden; alert unchanged."""
    alert_id = uuid.uuid4()

    with patch("app.routers.alerts.require_role") as mock_rbac:
        from fastapi import HTTPException
        mock_rbac.return_value = MagicMock(
            side_effect=HTTPException(status_code=403, detail="Forbidden")
        )

        with TestClient(app) as client:
            response = client.patch(
                f"/api/v1/alerts/{alert_id}/resolve",
                json={"resolution_type": "REVIEWED_ACCEPTABLE"},
                headers=nurse_headers,
            )

    assert response.status_code == 403


def test_resolve_unknown_alert_returns_404(pharmacist_headers: dict) -> None:
    """Resolving a non-existent alert_id → 404 Not Found."""
    with (
        patch("app.routers.alerts.get_db_session") as mock_db,
        patch("app.routers.alerts.require_role"),
    ):
        mock_session = AsyncMock()
        mock_session.get.return_value = None
        mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_session)

        with TestClient(app) as client:
            response = client.patch(
                f"/api/v1/alerts/{uuid.uuid4()}/resolve",
                json={"resolution_type": "REVIEWED_ACCEPTABLE"},
                headers=pharmacist_headers,
            )

    assert response.status_code == 404


def test_resolve_already_resolved_alert_returns_409(
    pharmacist_headers: dict,
) -> None:
    """Resolving an already-resolved alert → 409 Conflict."""
    alert = _make_alert(status="RESOLVED")

    with (
        patch("app.routers.alerts.get_db_session") as mock_db,
        patch("app.routers.alerts.require_role"),
    ):
        mock_session = AsyncMock()
        mock_session.get.return_value = alert
        mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_session)

        with TestClient(app) as client:
            response = client.patch(
                f"/api/v1/alerts/{alert.id}/resolve",
                json={"resolution_type": "REVIEWED_ACCEPTABLE"},
                headers=pharmacist_headers,
            )

    assert response.status_code == 409
```

### 3. Create `backend/tests/unit/test_alert_sla_monitor.py`

```python
"""Unit tests for AlertSLAMonitor.

Design refs:
    US-032 AC Scenario 3 — 24h SLA breach; CHARGE_PHARMACIST_ESCALATION; sla_breached=True
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.alert_sla_monitor import AlertSLAMonitor


def _make_alert(
    hours_old: int = 25,
    status: str = "ACTIVE",
    severity: str = "HIGH",
    sla_breached: bool = False,
) -> MagicMock:
    alert = MagicMock()
    alert.id = uuid.uuid4()
    alert.encounter_id = uuid.uuid4()
    alert.alert_type = "HIGH_RISK_DRUG_CLASS"
    alert.severity = severity
    alert.status = status
    alert.drug_class = "ANTICOAGULANT"
    alert.drug_name = "Warfarin"
    alert.sla_breached = sla_breached
    alert.created_at = datetime.now(timezone.utc) - timedelta(hours=hours_old)
    return alert


@pytest.mark.asyncio
async def test_sla_breached_alert_is_tagged_and_escalated() -> None:
    """AC Scenario 3: alert 25h old → sla_breached=True; CHARGE_PHARMACIST_ESCALATION published."""
    alert = _make_alert(hours_old=25)
    mock_db = AsyncMock()
    mock_db.execute.return_value.scalars.return_value.all.return_value = [alert]

    with patch(
        "app.services.alert_sla_monitor.publish_message", new_callable=AsyncMock
    ) as mock_publish:
        monitor = AlertSLAMonitor(db=mock_db)
        result = await monitor.run()

    assert result["breached"] == 1
    assert alert.sla_breached is True
    mock_publish.assert_awaited_once()
    call_kwargs = mock_publish.call_args.kwargs
    assert call_kwargs["data"]["event_type"] == "CHARGE_PHARMACIST_ESCALATION"
    assert call_kwargs["attributes"]["priority"] == "IMMEDIATE"


@pytest.mark.asyncio
async def test_sla_monitor_is_idempotent() -> None:
    """Already-breached alerts (sla_breached=True) are excluded from the query."""
    mock_db = AsyncMock()
    # Query returns empty list because sla_breached=True alerts are filtered by the WHERE clause
    mock_db.execute.return_value.scalars.return_value.all.return_value = []

    with patch(
        "app.services.alert_sla_monitor.publish_message", new_callable=AsyncMock
    ) as mock_publish:
        monitor = AlertSLAMonitor(db=mock_db)
        result = await monitor.run()

    assert result["breached"] == 0
    mock_publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolved_alerts_not_escalated() -> None:
    """Resolved alerts must not be included in SLA breach detection."""
    mock_db = AsyncMock()
    mock_db.execute.return_value.scalars.return_value.all.return_value = []

    monitor = AlertSLAMonitor(db=mock_db)
    result = await monitor.run()
    assert result["checked"] == 0


@pytest.mark.asyncio
async def test_sla_monitor_continues_on_single_alert_failure() -> None:
    """A failure escalating one alert must not abort processing of remaining alerts."""
    alert_ok = _make_alert(hours_old=25)
    alert_fail = _make_alert(hours_old=26)
    mock_db = AsyncMock()
    mock_db.execute.return_value.scalars.return_value.all.return_value = [
        alert_fail,
        alert_ok,
    ]

    call_count = 0

    async def publish_side_effect(**kwargs):  # noqa: ANN202
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Pub/Sub transient error")

    with patch(
        "app.services.alert_sla_monitor.publish_message",
        side_effect=publish_side_effect,
    ):
        monitor = AlertSLAMonitor(db=mock_db)
        result = await monitor.run()

    assert result["skipped"] == 1
    assert result["breached"] == 1
```

---

## Validation

- [ ] All 13 parametrised drug-class tests pass
- [ ] `test_non_high_risk_drug_returns_no_match` passes
- [ ] `test_detection_is_case_insensitive` passes
- [ ] `test_multiple_high_risk_drugs_returns_multiple_matches` passes
- [ ] `test_pharmacist_can_resolve_active_alert` passes (HTTP 200)
- [ ] `test_nurse_cannot_resolve_alert` passes (HTTP 403)
- [ ] `test_resolve_unknown_alert_returns_404` passes (HTTP 404)
- [ ] `test_resolve_already_resolved_alert_returns_409` passes (HTTP 409)
- [ ] `test_sla_breached_alert_is_tagged_and_escalated` passes
- [ ] `test_sla_monitor_is_idempotent` passes
- [ ] `test_sla_monitor_continues_on_single_alert_failure` passes
- [ ] `pytest --tb=short backend/tests/unit/` exits 0 in CI

---

## Files Changed

| Action | Path |
|--------|------|
| Create | `backend/tests/unit/test_high_risk_drug_class_detector.py` |
| Create | `backend/tests/unit/test_alert_resolve_endpoint.py` |
| Create | `backend/tests/unit/test_alert_sla_monitor.py` |
