---
id: TASK-008
title: "Unit Tests — Drug Interaction Checker: HIGH Path, Cache Hit, OpenFDA Fallback, Offline Degradation"
user_story: US-031
epic: EP-005
sprint: 2
layer: Testing
estimate: 4h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-031/TASK-001, US-031/TASK-002, US-031/TASK-003, US-031/TASK-004, US-031/TASK-005]
---

# TASK-008: Unit Tests — Drug Interaction Checker: HIGH Path, Cache Hit, OpenFDA Fallback, Offline Degradation

> **Story:** US-031 | **Epic:** EP-005 | **Sprint:** 2 | **Layer:** Testing | **Est:** 4 h  
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-031 Definition of Done explicitly mandates unit tests for four paths:
1. **HIGH interaction path** — Warfarin + Aspirin resolved as `severity=HIGH` from RxNav
2. **Cache hit** — RxNav is never called on the second lookup
3. **OpenFDA fallback** — RxNav 503 → OpenFDA queried; `source=OPENFDA`
4. **Offline degradation** — Both APIs fail → `interaction_check_status=INCOMPLETE`

Additionally, tests cover the alert endpoint RBAC, Pub/Sub priority selection, and severity mapping.

**Design references:**
- US-031 AC Scenarios 1–4
- design.md §4.1 — pytest + pytest-asyncio test stack

---

## Acceptance Criteria Addressed

All four AC scenarios validated via unit tests.

---

## Implementation Steps

### 1. Create `backend/tests/agents/medication_reconciliation/test_drug_interaction_checker.py`

```python
"""Unit tests for DrugInteractionChecker — US-031 AC Scenarios 1–4.

Test matrix:
    - HIGH interaction path (Warfarin + Aspirin from RxNav)
    - Cache hit path (RxNav not called on second lookup)
    - OpenFDA fallback (RxNav HTTP 503)
    - Offline degradation (both APIs fail)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.medication_reconciliation.drug_interaction.cache import (
    DrugInteractionCache,
)
from app.agents.medication_reconciliation.drug_interaction.checker import (
    DischargedMedication,
    DrugInteractionChecker,
)
from app.agents.medication_reconciliation.drug_interaction.rxnav_client import (
    RxNavUnavailableError,
)
from app.agents.medication_reconciliation.drug_interaction.openfda_client import (
    OpenFDAUnavailableError,
)

WARFARIN = DischargedMedication(rxcui="11289", drug_name="Warfarin")
ASPIRIN = DischargedMedication(rxcui="1191", drug_name="Aspirin")
METFORMIN = DischargedMedication(rxcui="6809", drug_name="Metformin")

_RXNAV_HIGH_INTERACTION = {
    "rxcui1": "11289",
    "rxcui2": "1191",
    "drug1": "Warfarin",
    "drug2": "Aspirin",
    "severity": "HIGH",
    "description": "Concurrent use increases bleeding risk.",
    "source": "RXNAV",
}


@pytest.fixture
def mock_cache() -> AsyncMock:
    cache = AsyncMock(spec=DrugInteractionCache)
    cache.get.return_value = None  # default: cache miss
    return cache


@pytest.fixture
def mock_rxnav() -> AsyncMock:
    rxnav = AsyncMock()
    rxnav.get_interactions.return_value = [_RXNAV_HIGH_INTERACTION]
    return rxnav


@pytest.fixture
def mock_openfda() -> AsyncMock:
    openfda = AsyncMock()
    openfda.get_interactions.return_value = [
        {
            "drug1": "Warfarin",
            "drug2": None,
            "description": "May interact with antiplatelet agents.",
            "severity": "UNKNOWN",
            "source": "OPENFDA",
        }
    ]
    return openfda


# ---------------------------------------------------------------------------
# Scenario 1: HIGH interaction — Warfarin + Aspirin → RxNav → severity=HIGH
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_high_severity_interaction_returned_from_rxnav(
    mock_cache: AsyncMock,
    mock_rxnav: AsyncMock,
    mock_openfda: AsyncMock,
) -> None:
    """AC Scenario 1 — RxNav returns HIGH severity for Warfarin + Aspirin."""
    checker = DrugInteractionChecker(
        cache=mock_cache, rxnav_client=mock_rxnav, openfda_client=mock_openfda
    )

    result = await checker.check([WARFARIN, ASPIRIN])

    assert result.interaction_check_status == "COMPLETE"
    assert len(result.interactions) == 1
    interaction = result.interactions[0]
    assert interaction["severity"] == "HIGH"
    assert interaction["source"] == "RXNAV"
    assert set(interaction[k] for k in ["drug1", "drug2"]) == {"Warfarin", "Aspirin"}
    mock_rxnav.get_interactions.assert_called_once()


# ---------------------------------------------------------------------------
# Scenario 2: Cache hit — RxNav NOT called on second lookup
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cache_hit_suppresses_rxnav_call(
    mock_cache: AsyncMock,
    mock_rxnav: AsyncMock,
    mock_openfda: AsyncMock,
) -> None:
    """AC Scenario 2 — Cache hit: RxNav API must not be called."""
    mock_cache.get.return_value = {"interactions": [_RXNAV_HIGH_INTERACTION]}

    checker = DrugInteractionChecker(
        cache=mock_cache, rxnav_client=mock_rxnav, openfda_client=mock_openfda
    )

    result = await checker.check([WARFARIN, ASPIRIN])

    assert result.interaction_check_status == "COMPLETE"
    assert len(result.interactions) == 1
    mock_rxnav.get_interactions.assert_not_called()


# ---------------------------------------------------------------------------
# Scenario 3: OpenFDA fallback — RxNav HTTP 503 → OpenFDA → source=OPENFDA
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_openfda_fallback_on_rxnav_503(
    mock_cache: AsyncMock,
    mock_rxnav: AsyncMock,
    mock_openfda: AsyncMock,
) -> None:
    """AC Scenario 3 — RxNav 503 triggers OpenFDA fallback; source=OPENFDA."""
    mock_rxnav.get_interactions.side_effect = RxNavUnavailableError(status_code=503)

    checker = DrugInteractionChecker(
        cache=mock_cache, rxnav_client=mock_rxnav, openfda_client=mock_openfda
    )

    result = await checker.check([WARFARIN, ASPIRIN])

    assert result.interaction_check_status == "COMPLETE"
    mock_openfda.get_interactions.assert_called()
    sources = {i["source"] for i in result.interactions}
    assert sources == {"OPENFDA"}


# ---------------------------------------------------------------------------
# Scenario 4: Offline degradation — both APIs fail → INCOMPLETE
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_offline_degradation_when_both_apis_unavailable(
    mock_cache: AsyncMock,
    mock_rxnav: AsyncMock,
    mock_openfda: AsyncMock,
) -> None:
    """AC Scenario 4 — Both RxNav and OpenFDA fail → INCOMPLETE status."""
    mock_rxnav.get_interactions.side_effect = RxNavUnavailableError(status_code=503)
    mock_openfda.get_interactions.side_effect = OpenFDAUnavailableError(status_code=500)

    checker = DrugInteractionChecker(
        cache=mock_cache, rxnav_client=mock_rxnav, openfda_client=mock_openfda
    )

    result = await checker.check([WARFARIN, ASPIRIN])

    assert result.interaction_check_status == "INCOMPLETE"
    assert result.degradation_notice is not None
    assert "manual review" in result.degradation_notice.lower()
```

### 2. Create `backend/tests/agents/medication_reconciliation/test_rxnav_severity_mapping.py`

```python
"""Unit tests for RxNav severity string → InteractionSeverity mapping."""
from __future__ import annotations

import pytest

from app.agents.medication_reconciliation.drug_interaction.rxnav_client import (
    InteractionSeverity,
    _map_severity,
)


@pytest.mark.parametrize(
    "rxnav_label, expected",
    [
        ("major", InteractionSeverity.HIGH),
        ("Major", InteractionSeverity.HIGH),
        ("MAJOR", InteractionSeverity.HIGH),
        ("contraindicated", InteractionSeverity.HIGH),
        ("Contraindicated", InteractionSeverity.HIGH),
        ("moderate", InteractionSeverity.MEDIUM),
        ("Moderate", InteractionSeverity.MEDIUM),
        ("minor", InteractionSeverity.LOW),
        ("Minor", InteractionSeverity.LOW),
        ("unknown_label", InteractionSeverity.LOW),
    ],
)
def test_severity_mapping(rxnav_label: str, expected: InteractionSeverity) -> None:
    assert _map_severity(rxnav_label) == expected
```

### 3. Create `backend/tests/agents/medication_reconciliation/test_cache_key.py`

```python
"""Unit tests for DrugInteractionCache key symmetry."""
from __future__ import annotations

from app.agents.medication_reconciliation.drug_interaction.cache import (
    _build_cache_key,
)


def test_cache_key_is_order_independent() -> None:
    """Reversed CUI pair must produce identical key."""
    assert _build_cache_key("11289", "1191") == _build_cache_key("1191", "11289")


def test_cache_key_format() -> None:
    key = _build_cache_key("11289", "1191")
    assert key.startswith("drug-interaction:")
    parts = key.split(":")
    assert len(parts) == 3
    assert parts[1] < parts[2]  # sorted ascending
```

### 4. Create `backend/tests/routers/test_pharmacist_alert_endpoint.py`

```python
"""Unit tests for POST /api/v1/encounters/{id}/alerts endpoint — US-031."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_high_severity_alert_publishes_immediate_priority() -> None:
    """HIGH severity alert → Pub/Sub message with priority=IMMEDIATE."""
    encounter_id = uuid.uuid4()

    with patch(
        "app.routers.encounters.alerts.get_pubsub_client"
    ) as mock_pubsub_dep:
        mock_pubsub = AsyncMock()
        mock_pubsub_dep.return_value = mock_pubsub

        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/encounters/{encounter_id}/alerts",
                json={
                    "severity": "HIGH",
                    "drug_pair": ["Warfarin", "Aspirin"],
                    "interaction_description": "Major bleeding risk.",
                    "source": "RXNAV",
                    "interaction_check_status": "COMPLETE",
                },
                headers={"Authorization": "Bearer <mock-pharmacist-jwt>"},
            )

    assert response.status_code == 201
    call_kwargs = mock_pubsub.publish.call_args.kwargs
    import json
    published = json.loads(call_kwargs["data"])
    assert published["priority"] == "IMMEDIATE"
    assert published["severity"] == "HIGH"


@pytest.mark.asyncio
async def test_incomplete_status_alert_uses_standard_priority() -> None:
    """INCOMPLETE status (MEDIUM severity) → Pub/Sub priority=STANDARD."""
    encounter_id = uuid.uuid4()

    with patch("app.routers.encounters.alerts.get_pubsub_client") as mock_pubsub_dep:
        mock_pubsub = AsyncMock()
        mock_pubsub_dep.return_value = mock_pubsub

        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/encounters/{encounter_id}/alerts",
                json={
                    "severity": "MEDIUM",
                    "interaction_description": "Interaction check unavailable — manual review required",
                    "source": "SYSTEM",
                    "interaction_check_status": "INCOMPLETE",
                },
                headers={"Authorization": "Bearer <mock-pharmacist-jwt>"},
            )

    assert response.status_code == 201
    published = json.loads(mock_pubsub.publish.call_args.kwargs["data"])
    assert published["priority"] == "STANDARD"
    assert published["interaction_check_status"] == "INCOMPLETE"
```

---

## File Checklist

| File | Action |
|------|--------|
| `backend/tests/agents/medication_reconciliation/test_drug_interaction_checker.py` | Create |
| `backend/tests/agents/medication_reconciliation/test_rxnav_severity_mapping.py` | Create |
| `backend/tests/agents/medication_reconciliation/test_cache_key.py` | Create |
| `backend/tests/routers/test_pharmacist_alert_endpoint.py` | Create |

---

## Validation

- [ ] All 4 AC scenario tests pass (`pytest -v`)
- [ ] Severity mapping parametrised test: 10 cases all pass
- [ ] Cache key symmetry test passes
- [ ] Alert endpoint: `HIGH` → `IMMEDIATE`, `MEDIUM` → `STANDARD`
- [ ] No real HTTP calls made during unit tests (all external clients mocked)
- [ ] Test coverage for `checker.py` ≥ 90%

---

## Definition of Done

- [ ] All test files created and passing
- [ ] CI pipeline green for this story
- [ ] No PHI in test fixtures (synthetic CUIs and drug names only)
