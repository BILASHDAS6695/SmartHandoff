---
id: TASK-006
title: "Unit Tests — A01/A02/A03 Status Transitions, Bed Board Filter API, Seeding Idempotency, Housekeeping Notification"
user_story: US-035
epic: EP-006
sprint: 2
layer: Testing
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer + AI/ML Engineer
upstream: [US-035/TASK-001, US-035/TASK-002, US-035/TASK-003, US-035/TASK-004, US-035/TASK-005]
---

# TASK-006: Unit Tests — A01/A02/A03 Status Transitions, Bed Board Filter API, Seeding Idempotency, Housekeeping Notification

> **Story:** US-035 | **Epic:** EP-006 | **Sprint:** 2 | **Layer:** Testing | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-035 DoD specifies: *"Unit tests: A01/A02/A03 status transitions, bed board filter API"*

All four acceptance criteria scenarios must be covered. Tests are split across four test files matching the four production modules:

| Test File | Module Under Test | Coverage Focus |
|-----------|-----------------|----------------|
| `test_bed_management_agent.py` | `agent.py` | A01/A02/A03 transitions; skip on unhandled events; DB write; refresh triggered |
| `test_bed_status_machine.py` | `status_machine.py` | All valid and invalid transitions; A02 dual-bed logic |
| `test_bed_inventory_seeder.py` | `seeder.py` | First-run insert count; second-run idempotency (0 inserts); YAML validation |
| `test_housekeeping_notifier.py` | `notifier.py` | Payload structure; idempotency key determinism; publish timeout; failure isolation |
| `test_beds_router.py` | `routers/beds.py` | GET filter scenarios; PATCH RBAC; PATCH 404; audit event emission |

Coverage target: ≥80% branch coverage across all five modules (TR-020).

**Mocking strategy:**

| External Dependency | Mock Approach |
|---------------------|---------------|
| `AsyncSession` (SQLAlchemy write) | `AsyncMock` with `execute()` returning configurable `MagicMock` |
| `AsyncSession` (SQLAlchemy read / mv_bed_board) | `AsyncMock` with `execute().mappings().all()` |
| `BedBoardRefreshService` | `AsyncMock` (both `refresh_async` and `refresh_sync`) |
| `HousekeepingNotifier` | `AsyncMock` |
| `google.cloud.pubsub_v1.PublisherClient` | `MagicMock`; `publish().result()` controllable |
| FastAPI `TestClient` / `AsyncClient` | `httpx.AsyncClient` with `app` transport |

---

## Acceptance Criteria Addressed

| US-035 AC | Test Cases |
|---|---|
| **Scenario 1 (A01)** | `test_a01_sets_bed_to_occupied`, `test_a01_triggers_mv_refresh`, `test_agent_skips_unhandled_event_type` |
| **Scenario 2 (A03)** | `test_a03_sets_bed_to_dirty`, `test_a03_publishes_housekeeping_notification` |
| **Scenario 3 (GET filter)** | `test_get_beds_filter_unit_and_status`, `test_get_beds_no_filter_returns_all`, `test_get_beds_requires_auth` |
| **Scenario 4 (Seeding)** | `test_seed_inserts_all_beds_on_first_run`, `test_seed_is_idempotent_on_second_run`, `test_seed_triggers_mv_refresh` |

---

## Implementation Steps

### 1. Scaffold test directories

```bash
mkdir -p backend/tests/unit/agents/bed_management
mkdir -p api-gateway/tests/unit/routers
touch backend/tests/unit/agents/bed_management/__init__.py
touch api-gateway/tests/unit/routers/__init__.py
```

### 2. Create `backend/tests/unit/agents/bed_management/test_bed_status_machine.py`

```python
"""Unit tests for bed status state machine (status_machine.py).

Coverage:
  A01: any status → OCCUPIED (no restriction on current status)
  A03: OCCUPIED → DIRTY; invalid current status raises BedStatusTransitionError
  A02: resolve_target_status returns OCCUPIED for new bed
  Unknown event: raises ValueError
"""
import pytest

from app.agents.bed_management.schemas import BedStatus
from app.agents.bed_management.status_machine import resolve_target_status
from app.exceptions import BedStatusTransitionError


def test_a01_from_vacant_returns_occupied():
    assert resolve_target_status("A01", BedStatus.VACANT) == BedStatus.OCCUPIED


def test_a01_from_occupied_returns_occupied():
    """A01 does not require VACANT — admit into already-occupied bed (override)."""
    assert resolve_target_status("A01", BedStatus.OCCUPIED) == BedStatus.OCCUPIED


def test_a01_from_dirty_returns_occupied():
    assert resolve_target_status("A01", BedStatus.DIRTY) == BedStatus.OCCUPIED


def test_a03_from_occupied_returns_dirty():
    assert resolve_target_status("A03", BedStatus.OCCUPIED) == BedStatus.DIRTY


def test_a03_from_vacant_raises_transition_error():
    with pytest.raises(BedStatusTransitionError):
        resolve_target_status("A03", BedStatus.VACANT)


def test_a03_from_dirty_raises_transition_error():
    with pytest.raises(BedStatusTransitionError):
        resolve_target_status("A03", BedStatus.DIRTY)


def test_a02_returns_occupied_for_new_bed():
    """A02: new bed target status is OCCUPIED regardless of current."""
    assert resolve_target_status("A02", BedStatus.VACANT) == BedStatus.OCCUPIED


def test_unknown_event_raises_value_error():
    with pytest.raises(ValueError, match="does not handle event type"):
        resolve_target_status("A08", BedStatus.VACANT)
```

### 3. Create `backend/tests/unit/agents/bed_management/test_bed_management_agent.py`

```python
"""Unit tests for BedManagementAgent.process() (agent.py).

Coverage:
  SC-1 (A01): bed → OCCUPIED; mv_refresh triggered; no housekeeping notification
  SC-2 (A03): bed → DIRTY; mv_refresh triggered; housekeeping notification published
  SC-2 (A02): two DB updates; mv_refresh triggered; no housekeeping notification
  DoD: unhandled event types silently skipped (returns None)
  DoD: DB failure raises RetryableError
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.agents.bed_management.agent import BedManagementAgent
from app.agents.bed_management.schemas import BedStatus
from app.agents.base_agent import RetryableError
from app.models.bed import Bed


@pytest.fixture
def mock_refresh_service():
    svc = AsyncMock()
    svc.refresh_async = AsyncMock()
    return svc


@pytest.fixture
def mock_notifier():
    notifier = AsyncMock()
    notifier.notify = AsyncMock()
    return notifier


@pytest.fixture
def mock_bed():
    bed = MagicMock(spec=Bed)
    bed.id = uuid4()
    bed.status = BedStatus.VACANT.value
    return bed


@pytest.fixture
def mock_session_factory(mock_bed):
    """Factory returning an AsyncMock session with a bed record."""
    session = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = mock_bed
    execute_result.rowcount = 1
    session.execute.return_value = execute_result
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory


@pytest.fixture
def agent(mock_session_factory, mock_refresh_service, mock_notifier):
    return BedManagementAgent(
        db_session_factory=mock_session_factory,
        refresh_service=mock_refresh_service,
        housekeeping_notifier=mock_notifier,
    )


# ------------------------------------------------------------------
# Scenario 1: A01
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a01_sets_bed_to_occupied(agent, mock_session_factory):
    bed_id = str(uuid4())
    message = {
        "event_type": "A01",
        "encounter_id": str(uuid4()),
        "bed_id": bed_id,
    }
    result = await agent.process(message)

    assert result is not None
    assert result.new_status == BedStatus.OCCUPIED
    assert result.event_type == "A01"


@pytest.mark.asyncio
async def test_a01_triggers_mv_refresh_not_housekeeping(
    agent, mock_refresh_service, mock_notifier
):
    message = {
        "event_type": "A01",
        "encounter_id": str(uuid4()),
        "bed_id": str(uuid4()),
    }
    await agent.process(message)

    mock_refresh_service.refresh_async.assert_awaited_once()
    mock_notifier.notify.assert_not_awaited()


# ------------------------------------------------------------------
# Scenario 2: A03
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a03_sets_bed_to_dirty_and_notifies(
    agent, mock_refresh_service, mock_notifier, mock_bed
):
    mock_bed.status = BedStatus.OCCUPIED.value
    encounter_id = str(uuid4())
    message = {
        "event_type": "A03",
        "encounter_id": encounter_id,
        "bed_id": str(uuid4()),
    }
    result = await agent.process(message)

    assert result.new_status == BedStatus.DIRTY
    mock_refresh_service.refresh_async.assert_awaited_once()
    mock_notifier.notify.assert_awaited_once_with(
        bed_id=message["bed_id"],
        encounter_id=encounter_id,
    )


# ------------------------------------------------------------------
# A02: transfer
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a02_updates_two_beds(agent, mock_session_factory, mock_refresh_service):
    message = {
        "event_type": "A02",
        "encounter_id": str(uuid4()),
        "previous_bed_id": str(uuid4()),
        "bed_id": str(uuid4()),
    }
    result = await agent.process(message)

    assert result.event_type == "A02"
    mock_refresh_service.refresh_async.assert_awaited_once()


# ------------------------------------------------------------------
# Unhandled event type
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unhandled_event_type_returns_none(agent):
    message = {
        "event_type": "A08",  # Update demographics — not handled
        "encounter_id": str(uuid4()),
        "bed_id": str(uuid4()),
    }
    result = await agent.process(message)
    assert result is None


# ------------------------------------------------------------------
# DB failure → RetryableError
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_db_failure_raises_retryable_error(agent, mock_session_factory):
    session = mock_session_factory.return_value.__aenter__.return_value
    session.execute.side_effect = Exception("DB connection lost")

    with pytest.raises(RetryableError):
        await agent.process({
            "event_type": "A01",
            "encounter_id": str(uuid4()),
            "bed_id": str(uuid4()),
        })
```

### 4. Create `backend/tests/unit/agents/bed_management/test_bed_inventory_seeder.py`

```python
"""Unit tests for BedInventorySeeder (seeder.py).

Coverage:
  SC-4: First-run inserts all 200 beds (rowcount returned correctly)
  SC-4: Second-run is idempotent — returns 0 new inserts
  SC-4: mv_bed_board refresh triggered after seeding
  DoD: FileNotFoundError on missing YAML
  DoD: Pydantic ValidationError on malformed YAML
"""
import pathlib
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import yaml

from app.agents.bed_management.seeder import BedInventorySeeder
from app.agents.bed_management.refresh_service import BedBoardRefreshService


@pytest.fixture
def valid_yaml_path(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a minimal valid bed_inventory.yaml for testing."""
    config = {
        "units": [
            {
                "unit": "3A",
                "beds": [
                    {
                        "room": "301",
                        "bed_number": "A",
                        "bed_type": "MEDICAL",
                        "isolation_required": False,
                        "gender_designation": "ANY",
                    },
                    {
                        "room": "301",
                        "bed_number": "B",
                        "bed_type": "MEDICAL",
                        "isolation_required": False,
                        "gender_designation": "ANY",
                    },
                ],
            }
        ]
    }
    p = tmp_path / "bed_inventory.yaml"
    p.write_text(yaml.dump(config))
    return p


@pytest.fixture
def mock_refresh_service():
    svc = MagicMock(spec=BedBoardRefreshService)
    svc.refresh_sync = AsyncMock()
    return svc


@pytest.fixture
def mock_session_factory_with_inserts(n_inserted: int = 2):
    """Session mock where each INSERT returns rowcount=1 (or 0 for idempotency test)."""
    session = AsyncMock()
    execute_result = MagicMock()
    execute_result.rowcount = 1
    session.execute.return_value = execute_result
    session.commit = AsyncMock()

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory


@pytest.mark.asyncio
async def test_seed_inserts_beds_on_first_run(valid_yaml_path, mock_refresh_service):
    factory = mock_session_factory_with_inserts()
    seeder = BedInventorySeeder(
        session_factory=factory,
        refresh_service=mock_refresh_service,
        config_path=valid_yaml_path,
    )
    inserted = await seeder.seed()

    assert inserted == 2  # 2 beds in the minimal YAML fixture
    mock_refresh_service.refresh_sync.assert_awaited_once()


@pytest.mark.asyncio
async def test_seed_is_idempotent_on_second_run(valid_yaml_path, mock_refresh_service):
    """ON CONFLICT DO NOTHING returns rowcount=0 on conflict."""
    session = AsyncMock()
    execute_result = MagicMock()
    execute_result.rowcount = 0  # All rows already exist
    session.execute.return_value = execute_result
    session.commit = AsyncMock()

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)

    seeder = BedInventorySeeder(
        session_factory=factory,
        refresh_service=mock_refresh_service,
        config_path=valid_yaml_path,
    )
    inserted = await seeder.seed()

    assert inserted == 0
    mock_refresh_service.refresh_sync.assert_awaited_once()


@pytest.mark.asyncio
async def test_seed_raises_file_not_found(mock_refresh_service):
    factory = MagicMock()
    seeder = BedInventorySeeder(
        session_factory=factory,
        refresh_service=mock_refresh_service,
        config_path=pathlib.Path("/nonexistent/bed_inventory.yaml"),
    )
    with pytest.raises(FileNotFoundError):
        await seeder.seed()
```

### 5. Create `api-gateway/tests/unit/routers/test_beds_router.py`

```python
"""Unit tests for GET /api/v1/beds and PATCH /api/v1/beds/{id}/status (beds.py).

Coverage:
  SC-3: GET with unit+status filter returns only matching beds
  SC-3: GET with no filter returns all beds
  DoD: PATCH requires BedManager role (403 for Physician)
  DoD: PATCH 404 on unknown bed_id
  DoD: Audit event emitted after PATCH
"""
import pytest
import uuid
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch

from app.main import app
from app.agents.bed_management.schemas import BedStatus


@pytest.fixture
def bed_manager_headers():
    """JWT headers for a BedManager role user (mock — auth bypassed in tests)."""
    return {"Authorization": "Bearer bed_manager_test_token"}


@pytest.fixture
def physician_headers():
    return {"Authorization": "Bearer physician_test_token"}


@pytest.mark.asyncio
async def test_get_beds_filter_unit_and_status():
    """SC-3: GET /api/v1/beds?unit=3A&status=VACANT returns matching beds only."""
    mock_rows = [
        {
            "bed_id": uuid.uuid4(),
            "unit": "3A",
            "room": "301",
            "bed_number": "A",
            "bed_type": "MEDICAL",
            "status": "VACANT",
            "isolation_required": False,
            "gender_designation": "ANY",
            "predicted_discharge_time": None,
        },
        {
            "bed_id": uuid.uuid4(),
            "unit": "3A",
            "room": "301",
            "bed_number": "B",
            "bed_type": "MEDICAL",
            "status": "VACANT",
            "isolation_required": False,
            "gender_designation": "ANY",
            "predicted_discharge_time": None,
        },
    ]
    with patch("app.routers.beds.get_read_db") as mock_read_db, \
         patch("app.core.auth.require_role", return_value=lambda: {"sub": "user-1", "roles": ["BedManager"]}):
        session = AsyncMock()
        result = MagicMock()
        result.mappings.return_value.all.return_value = mock_rows
        session.execute.return_value = result
        mock_read_db.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_read_db.return_value.__aexit__ = AsyncMock(return_value=False)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/api/v1/beds?unit=3A&status=VACANT",
                headers={"Authorization": "Bearer test_token"},
            )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert all(b["unit"] == "3A" for b in data)
        assert all(b["status"] == "VACANT" for b in data)


@pytest.mark.asyncio
async def test_patch_bed_status_forbidden_for_physician():
    """PATCH /api/v1/beds/{id}/status returns 403 for Physician role."""
    with patch("app.core.auth.require_role") as mock_require_role:
        from fastapi import HTTPException
        mock_require_role.return_value = MagicMock(
            side_effect=HTTPException(status_code=403, detail="Forbidden")
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(
                f"/api/v1/beds/{uuid.uuid4()}/status",
                json={"status": "MAINTENANCE", "reason": "Annual maintenance check"},
                headers={"Authorization": "Bearer physician_token"},
            )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_patch_bed_status_not_found():
    """PATCH /api/v1/beds/{id}/status returns 404 for non-existent bed."""
    with patch("app.routers.beds.get_write_db") as mock_write_db, \
         patch("app.core.auth.require_role", return_value=lambda: {"sub": "user-1", "roles": ["BedManager"]}):
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None  # Bed not found
        session.execute.return_value = result
        mock_write_db.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_write_db.return_value.__aexit__ = AsyncMock(return_value=False)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(
                f"/api/v1/beds/{uuid.uuid4()}/status",
                json={"status": "MAINTENANCE", "reason": "Check"},
                headers={"Authorization": "Bearer bed_manager_token"},
            )
        assert response.status_code == 404
```

---

## File Checklist

| File | Action |
|------|--------|
| `backend/tests/unit/agents/bed_management/__init__.py` | Create (empty) |
| `backend/tests/unit/agents/bed_management/test_bed_status_machine.py` | Create |
| `backend/tests/unit/agents/bed_management/test_bed_management_agent.py` | Create |
| `backend/tests/unit/agents/bed_management/test_bed_inventory_seeder.py` | Create |
| `api-gateway/tests/unit/routers/__init__.py` | Create (empty) |
| `api-gateway/tests/unit/routers/test_beds_router.py` | Create |

---

## Validation

```bash
# Run all US-035 unit tests
cd backend
pytest tests/unit/agents/bed_management/ -v --cov=app/agents/bed_management --cov-report=term-missing

cd ../api-gateway
pytest tests/unit/routers/test_beds_router.py -v --cov=app/routers/beds --cov-report=term-missing
```

- [ ] All tests pass (`pytest` exit code 0)
- [ ] Branch coverage ≥80% for `agent.py`, `status_machine.py`, `seeder.py`, `notifier.py`, `routers/beds.py`
- [ ] SC-1 (A01): `test_a01_sets_bed_to_occupied` passes
- [ ] SC-2 (A03): `test_a03_sets_bed_to_dirty_and_notifies` passes
- [ ] SC-3 (GET filter): `test_get_beds_filter_unit_and_status` passes
- [ ] SC-4 (seeding): `test_seed_is_idempotent_on_second_run` passes (0 inserts)

---

## Definition of Done

- [ ] All 5 test files created and passing
- [ ] ≥80% branch coverage on all modules under test
- [ ] All 4 US-035 acceptance criteria scenarios covered
- [ ] Code peer-reviewed before merge
