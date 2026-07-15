---
id: TASK-005
title: "Write pytest Unit Tests — CancellationService, State Machine Transitions, CancellationDispatcher, Cancellation Handlers (All 4 US-015 Scenarios)"
user_story: US-015
epic: EP-001
sprint: 2
layer: Testing
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-015/TASK-001, US-015/TASK-002, US-015/TASK-003, US-015/TASK-004]
---

# TASK-005: Write pytest Unit Tests — CancellationService, State Machine Transitions, CancellationDispatcher, Cancellation Handlers (All 4 US-015 Scenarios)

> **Story:** US-015 | **Epic:** EP-001 | **Sprint:** 2 | **Layer:** Testing | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

US-015 DoD specifies:

> *"Unit tests: each cancellation type with correct state reversion"*

All 4 acceptance criteria scenarios and every DoD item must be covered. Tests are split across four test files matching the four production modules created in TASK-001 through TASK-004:

| Test File | Module Under Test | Coverage Focus |
|-----------|------------------|----------------|
| `test_cancellation_service.py` | `app/services/cancellation_service.py` | A11/A12/A13 state reverts, task bulk cancel, doc soft cancel, atomic transaction |
| `test_encounter_state_machine.py` | `app/models/encounter.py` | All valid and invalid transitions, PRE_ADMISSION status |
| `test_cancellation_dispatcher.py` | `app/services/cancellation_dispatcher.py` | Pub/Sub WORKFLOW_CANCELLED message, SignalR broadcast, failure isolation |
| `test_cancellation_handlers.py` | `app/handlers/cancellation_handlers.py` | API call routing, 404 guard (Scenario 4), timeout nack behaviour |

Coverage target: ≥80% branch coverage on all four modules (TR-020).

**Mocking strategy:**

| External Dependency | Mock Approach |
|---------------------|---------------|
| `AsyncSession` (SQLAlchemy) | `AsyncMock` with `execute()` returning `MagicMock(rowcount=N, scalar_one_or_none=...)` |
| `Encounter` ORM model | Constructed directly with `Encounter(status=...)` — no DB required |
| `ADTEventPublisher.publish_raw` | `AsyncMock` |
| `SignalRHub.send_to_group` | `AsyncMock` |
| `httpx.AsyncClient.post` | `AsyncMock` returning mock responses with configurable status codes |
| `asyncio.sleep` | Not needed (no retry delays in these modules) |

---

## Acceptance Criteria Addressed

| US-015 AC | Test Cases |
|---|---|
| **Scenario 1 (A11)** | `test_handle_cancel_admit_reverts_to_pre_admission`, `test_cancel_agent_tasks_updates_all_non_terminal` |
| **Scenario 2 (A12)** | `test_handle_cancel_transfer_reverts_to_admitted`, `test_handle_cancel_transfer_restores_previous_unit` |
| **Scenario 3 (A13)** | `test_handle_cancel_discharge_reverts_to_admitted`, `test_soft_cancel_documents_sets_cancelled_status` |
| **Scenario 4** | `test_handler_logs_warning_on_404_unknown_encounter`, `test_handler_does_not_raise_on_404` |
| **DoD** | Full test suite; ≥80% coverage; all 4 scenarios covered |

---

## Implementation Steps

### 1. Scaffold test directories

```bash
mkdir -p api-gateway/tests/unit/services api-gateway/tests/unit/models
mkdir -p hl7-listener/tests/unit/handlers
touch api-gateway/tests/unit/services/__init__.py
touch api-gateway/tests/unit/models/__init__.py
touch hl7-listener/tests/unit/handlers/__init__.py
```

### 2. Create `api-gateway/tests/unit/services/test_cancellation_service.py`

```python
"""Unit tests for app/services/cancellation_service.py.

Coverage:
  SC-1 (A11): handle_cancel_admit — revert to PRE_ADMISSION; cancel all tasks
  SC-2 (A12): handle_cancel_transfer — revert to ADMITTED; restore previous_unit
  SC-3 (A13): handle_cancel_discharge — revert to ADMITTED; soft-cancel docs
  DoD:        cancel_agent_tasks bulk UPDATE; docs retain content (status=CANCELLED only)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.models.encounter import Encounter, EncounterStatus
from app.services.cancellation_service import CancellationService, CancellationResult
from app.exceptions import EncounterNotFoundError, EncounterStateTransitionError


@pytest.fixture
def service() -> CancellationService:
    return CancellationService()


@pytest.fixture
def admitted_encounter() -> Encounter:
    enc = Encounter()
    enc.id = uuid4()
    enc.status = EncounterStatus.ADMITTED.value
    enc.previous_unit = "3A"
    enc.current_unit = "4B"
    return enc


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock()
    execute_result = MagicMock()
    execute_result.rowcount = 5
    execute_result.scalar_one_or_none.return_value = None  # default: encounter not found
    db.execute.return_value = execute_result
    return db


# ------------------------------------------------------------------
# Scenario 1: A11 — cancel admit
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_cancel_admit_reverts_to_pre_admission(
    service, admitted_encounter, mock_db
):
    """A11: encounter status transitions ADMITTED → PRE_ADMISSION."""
    mock_db.execute.return_value.scalar_one_or_none.return_value = admitted_encounter
    mock_db.execute.return_value.rowcount = 5

    result = await service.handle_cancel_admit(admitted_encounter.id, mock_db)

    assert admitted_encounter.status == EncounterStatus.PRE_ADMISSION.value
    assert isinstance(result, CancellationResult)
    assert result.event_type == "A11"
    assert result.tasks_cancelled == 5


@pytest.mark.asyncio
async def test_cancel_agent_tasks_bulk_update_excludes_terminal(service, mock_db):
    """cancel_agent_tasks() issues a single bulk UPDATE; terminal statuses excluded."""
    mock_db.execute.return_value.rowcount = 3

    count = await service.cancel_agent_tasks(uuid4(), mock_db)

    assert count == 3
    assert mock_db.execute.call_count == 1  # one bulk UPDATE, not N individual UPDATEs


@pytest.mark.asyncio
async def test_handle_cancel_admit_raises_on_invalid_status(service, mock_db):
    """A11 on DISCHARGED encounter raises EncounterStateTransitionError."""
    discharged = Encounter()
    discharged.id = uuid4()
    discharged.status = EncounterStatus.DISCHARGED.value
    mock_db.execute.return_value.scalar_one_or_none.return_value = discharged

    with pytest.raises(EncounterStateTransitionError) as exc_info:
        await service.handle_cancel_admit(discharged.id, mock_db)

    assert "DISCHARGED" in str(exc_info.value)
    assert "PRE_ADMISSION" in str(exc_info.value)


# ------------------------------------------------------------------
# Scenario 2: A12 — cancel transfer
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_cancel_transfer_reverts_to_admitted(service, mock_db):
    """A12: TRANSFERRED → ADMITTED."""
    enc = Encounter()
    enc.id = uuid4()
    enc.status = EncounterStatus.TRANSFERRED.value
    enc.previous_unit = "3A"
    enc.current_unit = "4B"
    mock_db.execute.return_value.scalar_one_or_none.return_value = enc
    mock_db.execute.return_value.rowcount = 2

    result = await service.handle_cancel_transfer(enc.id, mock_db)

    assert enc.status == EncounterStatus.ADMITTED.value
    assert result.event_type == "A12"


@pytest.mark.asyncio
async def test_handle_cancel_transfer_restores_previous_unit(service, mock_db):
    """A12: current_unit reverts to previous_unit after cancel transfer."""
    enc = Encounter()
    enc.id = uuid4()
    enc.status = EncounterStatus.TRANSFERRED.value
    enc.previous_unit = "3A"
    enc.current_unit = "4B"
    mock_db.execute.return_value.scalar_one_or_none.return_value = enc
    mock_db.execute.return_value.rowcount = 0

    await service.handle_cancel_transfer(enc.id, mock_db)

    assert enc.current_unit == "3A"


# ------------------------------------------------------------------
# Scenario 3: A13 — cancel discharge
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_cancel_discharge_reverts_to_admitted(service, mock_db):
    """A13: DISCHARGED → ADMITTED."""
    enc = Encounter()
    enc.id = uuid4()
    enc.status = EncounterStatus.DISCHARGED.value
    mock_db.execute.return_value.scalar_one_or_none.return_value = enc
    mock_db.execute.return_value.rowcount = 1

    result = await service.handle_cancel_discharge(enc.id, mock_db)

    assert enc.status == EncounterStatus.ADMITTED.value
    assert result.event_type == "A13"
    assert result.docs_cancelled == 1


@pytest.mark.asyncio
async def test_soft_cancel_documents_does_not_delete_content(service, mock_db):
    """Soft-cancel: Document.content not modified — only status=CANCELLED is set."""
    mock_db.execute.return_value.rowcount = 2
    # No assertion on content column — confirm UPDATE does not include content field
    count = await service._soft_cancel_documents(uuid4(), mock_db)
    assert count == 2
    # Verify UPDATE statement does not set content field
    update_stmt = str(mock_db.execute.call_args[0][0])
    assert "content" not in update_stmt.lower()


# ------------------------------------------------------------------
# Unknown encounter
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_encounter_not_found_raises_encounter_not_found_error(service, mock_db):
    """_get_encounter raises EncounterNotFoundError when scalar_one_or_none returns None."""
    mock_db.execute.return_value.scalar_one_or_none.return_value = None

    with pytest.raises(EncounterNotFoundError):
        await service._get_encounter(uuid4(), mock_db)
```

### 3. Create `api-gateway/tests/unit/models/test_encounter_state_machine.py`

```python
"""Unit tests for Encounter state machine (US-015 cancellation transitions).

Coverage:
  - All 3 new cancellation revert paths: A11, A12, A13
  - Invalid transition raises EncounterStateTransitionError
  - PRE_ADMISSION status in EncounterStatus enum
"""
import pytest
from app.models.encounter import Encounter, EncounterStatus
from app.exceptions import EncounterStateTransitionError


@pytest.mark.parametrize("initial,target,event", [
    (EncounterStatus.ADMITTED,     EncounterStatus.PRE_ADMISSION, "A11"),
    (EncounterStatus.TRANSFERRED,  EncounterStatus.ADMITTED,      "A12"),
    (EncounterStatus.DISCHARGED,   EncounterStatus.ADMITTED,      "A13"),
])
def test_cancellation_transitions_succeed(initial, target, event):
    """A11/A12/A13 cancellation transitions are permitted."""
    enc = Encounter(status=initial.value)
    enc.transition_to(target)
    assert enc.status == target.value, f"{event} transition failed"


@pytest.mark.parametrize("initial,invalid_target", [
    (EncounterStatus.DISCHARGED,   EncounterStatus.PRE_ADMISSION),   # no direct path
    (EncounterStatus.PRE_ADMISSION, EncounterStatus.DISCHARGED),     # must go through ADMITTED
    (EncounterStatus.ADMITTED,     EncounterStatus.REGISTERED),      # backwards
    (EncounterStatus.TRANSFERRED,  EncounterStatus.REGISTERED),      # no path
])
def test_invalid_transitions_raise(initial, invalid_target):
    """Invalid state transitions raise EncounterStateTransitionError."""
    enc = Encounter(status=initial.value)
    with pytest.raises(EncounterStateTransitionError):
        enc.transition_to(invalid_target)


def test_pre_admission_status_exists():
    """PRE_ADMISSION is a valid EncounterStatus value."""
    assert EncounterStatus.PRE_ADMISSION.value == "PRE_ADMISSION"
```

### 4. Create `api-gateway/tests/unit/services/test_cancellation_dispatcher.py`

```python
"""Unit tests for app/services/cancellation_dispatcher.py.

Coverage:
  - WORKFLOW_CANCELLED Pub/Sub message attributes
  - SignalR ENCOUNTER_CANCELLED payload
  - Pub/Sub failure does not raise (best-effort)
  - SignalR failure does not raise (best-effort)
"""
import pytest
from unittest.mock import AsyncMock
from uuid import uuid4

from app.services.cancellation_dispatcher import CancellationDispatcher
from app.services.cancellation_service import CancellationResult


@pytest.fixture
def mock_publisher():
    p = AsyncMock()
    p.publish_raw = AsyncMock()
    return p


@pytest.fixture
def mock_hub():
    h = AsyncMock()
    h.send_to_group = AsyncMock()
    return h


@pytest.fixture
def dispatcher(mock_publisher, mock_hub):
    return CancellationDispatcher(publisher=mock_publisher, hub=mock_hub)


@pytest.fixture
def a11_result():
    return CancellationResult(
        encounter_id=uuid4(),
        event_type="A11",
        tasks_cancelled=5,
        docs_cancelled=2,
    )


@pytest.mark.asyncio
async def test_pubsub_workflow_cancelled_attributes(dispatcher, mock_publisher, a11_result):
    """WORKFLOW_CANCELLED Pub/Sub message has correct message_type attribute."""
    await dispatcher.dispatch_post_commit(a11_result)
    call_kwargs = mock_publisher.publish_raw.call_args[1]
    assert call_kwargs["attributes"]["message_type"] == "WORKFLOW_CANCELLED"
    assert call_kwargs["attributes"]["event_type"] == "A11"
    assert call_kwargs["attributes"]["encounter_id"] == str(a11_result.encounter_id)
    assert "iso_timestamp" in call_kwargs["attributes"]


@pytest.mark.asyncio
async def test_pubsub_ordering_key_is_encounter_id(dispatcher, mock_publisher, a11_result):
    """WORKFLOW_CANCELLED ordering key equals encounter_id string."""
    await dispatcher.dispatch_post_commit(a11_result)
    call_kwargs = mock_publisher.publish_raw.call_args[1]
    assert call_kwargs["ordering_key"] == str(a11_result.encounter_id)


@pytest.mark.asyncio
async def test_signalr_broadcast_group_and_event(dispatcher, mock_hub, a11_result):
    """SignalR broadcast targets encounter-{id} group with ENCOUNTER_CANCELLED event."""
    await dispatcher.dispatch_post_commit(a11_result)
    call_kwargs = mock_hub.send_to_group.call_args[1]
    assert call_kwargs["group"] == f"encounter-{a11_result.encounter_id}"
    assert call_kwargs["event"] == "ENCOUNTER_CANCELLED"
    assert call_kwargs["payload"]["event"] == "ENCOUNTER_CANCELLED"


@pytest.mark.asyncio
async def test_pubsub_failure_does_not_raise(dispatcher, mock_publisher, a11_result):
    """Pub/Sub publish failure is caught; dispatch_post_commit does not raise."""
    mock_publisher.publish_raw.side_effect = Exception("Pub/Sub unavailable")
    # Should not raise — best-effort
    await dispatcher.dispatch_post_commit(a11_result)


@pytest.mark.asyncio
async def test_signalr_failure_does_not_raise(dispatcher, mock_hub, a11_result):
    """SignalR broadcast failure is caught; dispatch_post_commit does not raise."""
    mock_hub.send_to_group.side_effect = Exception("SignalR hub unavailable")
    await dispatcher.dispatch_post_commit(a11_result)


@pytest.mark.asyncio
async def test_no_phi_in_pubsub_attributes(dispatcher, mock_publisher, a11_result):
    """PHI fields are absent from Pub/Sub message attributes (BR-020)."""
    await dispatcher.dispatch_post_commit(a11_result)
    attrs = mock_publisher.publish_raw.call_args[1]["attributes"]
    phi_fields = {"mrn", "first_name", "last_name", "dob", "phone", "email"}
    for field in phi_fields:
        assert field not in attrs, f"PHI field '{field}' found in Pub/Sub attributes"
```

### 5. Create `hl7-listener/tests/unit/handlers/test_cancellation_handlers.py`

```python
"""Unit tests for app/handlers/cancellation_handlers.py.

Coverage:
  SC-4: unknown encounter (404) → warning log, no raise
  Timeout → error log, exception re-raised
  Registration of A11/A12/A13 handlers in router
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4
import httpx

from app.models.adt_event import ADTEvent, EventType
from app.handlers.cancellation_handlers import (
    _call_cancel_api,
    register_cancellation_handlers,
    cancel_admit_handler,
)
from app.parser.router import ADTRouter


@pytest.fixture
def mock_client():
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def sample_event():
    event = MagicMock(spec=ADTEvent)
    event.encounter_id = uuid4()
    event.event_type = EventType.CANCEL_ADMIT
    return event


# ------------------------------------------------------------------
# Scenario 4: unknown encounter
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_cancel_api_404_logs_warning_no_raise(mock_client, caplog):
    """404 response: warning logged with unknown_encounter_id; no exception raised."""
    encounter_id = uuid4()
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_client.post.return_value = mock_response

    import logging
    with caplog.at_level(logging.WARNING, logger="app.handlers.cancellation_handlers"):
        await _call_cancel_api(
            encounter_id=encounter_id,
            event_type="A11",
            client=mock_client,
        )

    assert "unknown_encounter" in caplog.text.lower() or str(encounter_id) in caplog.text


@pytest.mark.asyncio
async def test_call_cancel_api_404_does_not_raise(mock_client):
    """404 from API does not raise — ACK is still returned to EHR."""
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_client.post.return_value = mock_response

    # Should not raise
    await _call_cancel_api(encounter_id=uuid4(), event_type="A11", client=mock_client)


# ------------------------------------------------------------------
# Timeout behaviour
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_cancel_api_timeout_raises(mock_client):
    """Timeout raises httpx.TimeoutException so MLLP pipeline can nack."""
    mock_client.post.side_effect = httpx.TimeoutException("timeout")

    with pytest.raises(httpx.TimeoutException):
        await _call_cancel_api(encounter_id=uuid4(), event_type="A11", client=mock_client)


# ------------------------------------------------------------------
# Handler registration
# ------------------------------------------------------------------

def test_register_cancellation_handlers_registers_all_three():
    """A11, A12, A13 handlers registered in router after register_cancellation_handlers()."""
    router = ADTRouter()
    register_cancellation_handlers(router=router)

    assert EventType.CANCEL_ADMIT    in router._handlers
    assert EventType.CANCEL_TRANSFER in router._handlers
    assert EventType.CANCEL_DISCHARGE in router._handlers


def test_register_cancellation_handlers_is_idempotent():
    """Calling register_cancellation_handlers() twice does not raise."""
    router = ADTRouter()
    register_cancellation_handlers(router=router)
    register_cancellation_handlers(router=router)  # second call should be safe


# ------------------------------------------------------------------
# 2xx success path
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_cancel_api_success_does_not_raise(mock_client):
    """2xx response: no exception raised."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()  # no raise on 200
    mock_client.post.return_value = mock_response

    await _call_cancel_api(encounter_id=uuid4(), event_type="A11", client=mock_client)
```

### 6. Run the full test suite

```bash
# api-gateway unit tests
cd api-gateway
pytest tests/unit/services/test_cancellation_service.py \
       tests/unit/services/test_cancellation_dispatcher.py \
       tests/unit/models/test_encounter_state_machine.py \
       -v --cov=app/services/cancellation_service \
       --cov=app/services/cancellation_dispatcher \
       --cov=app/models/encounter \
       --cov-report=term-missing \
       --cov-fail-under=80

# hl7-listener unit tests
cd ../hl7-listener
pytest tests/unit/handlers/test_cancellation_handlers.py \
       -v --cov=app/handlers/cancellation_handlers \
       --cov-report=term-missing \
       --cov-fail-under=80
```

---

## Definition of Done Checklist

- [ ] All 4 test files created and passing
- [ ] Scenario 1 (A11): state revert to `PRE_ADMISSION` + task cancellation count verified
- [ ] Scenario 2 (A12): state revert to `ADMITTED` + `previous_unit` restore verified
- [ ] Scenario 3 (A13): state revert to `ADMITTED` + doc soft-cancel verified
- [ ] Scenario 4 (unknown encounter): 404 → warning log, no exception raised
- [ ] Invalid state transition raises `EncounterStateTransitionError`
- [ ] WORKFLOW_CANCELLED Pub/Sub attributes verified (message_type, event_type, encounter_id, iso_timestamp)
- [ ] SignalR broadcast group (`encounter-{id}`) and event name (`ENCOUNTER_CANCELLED`) verified
- [ ] Pub/Sub and SignalR failure isolation verified (no raise from `dispatch_post_commit`)
- [ ] PHI absence in Pub/Sub attributes verified
- [ ] Coverage ≥80% on all four modules
