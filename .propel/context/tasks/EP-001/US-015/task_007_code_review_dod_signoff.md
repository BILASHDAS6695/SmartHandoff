---
id: TASK-007
title: "Code Review & DoD Sign-off — US-015 ADT Cancellation Event Handling"
user_story: US-015
epic: EP-001
sprint: 2
layer: Process
estimate: 1.5h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer + Security Engineer
upstream: [US-015/TASK-001, US-015/TASK-002, US-015/TASK-003, US-015/TASK-004, US-015/TASK-005, US-015/TASK-006]
---

# TASK-007: Code Review & DoD Sign-off — US-015 ADT Cancellation Event Handling

> **Story:** US-015 | **Epic:** EP-001 | **Sprint:** 2 | **Layer:** Process | **Est:** 1.5 h
> **Status:** Done | **Date:** 2026-07-22

---

## Context

This is the final task for US-015. It verifies that all implementation tasks (TASK-001 through TASK-006) are complete, all Definition of Done checklist items are satisfied, and a peer code review has been conducted.

A **Security Engineer review is mandatory** for this story due to three high-risk surfaces:

### 1. PHI containment in logs (HIPAA / BR-020)

Cancellation handlers process `ADTEvent` objects that contain encrypted PHI fields (first_name, last_name, DOB, MRN via SQLAlchemy TypeDecorator — ADR-007). Confirm that:

- **`CancellationService` logs** include only `encounter_id` (UUID), `event_type`, `tasks_cancelled`, `docs_cancelled`, and `new_status` — no patient identifiers.
- **`CancellationDispatcher` logs** include only `encounter_id`, `event_type`, `message_type`, and `group` — no patient identifiers.
- **`cancellation_handlers.py` logs** include only `encounter_id` (UUID) and `event_type` — the `unknown_encounter_id` warning log must also be a UUID, never a patient name or MRN.
- **Pub/Sub message attributes** (`WORKFLOW_CANCELLED`) contain only `message_type`, `event_type`, `encounter_id`, `iso_timestamp` — no PHI fields (BR-020).
- **SignalR `ENCOUNTER_CANCELLED` payload** contains only `event`, `encounter_id`, `event_type`, `reason` — no PHI.

### 2. Atomicity guarantee (patient safety / ADR-003)

An incomplete cancellation (encounter status reverted but tasks not cancelled, or vice versa) is a patient safety risk: agents could continue processing a cancelled encounter. Confirm that:

- `CancellationService.handle_cancel_admit/transfer/discharge()` executes encounter status update and `cancel_agent_tasks()` within a **single `async with session.begin()` block** in the API endpoint.
- No `await db.commit()` occurs inside `CancellationService` methods — the caller (endpoint) owns the commit.
- The API endpoint returns 409 on `EncounterStateTransitionError` — ensuring DB is rolled back and no partial state is written.

### 3. Race condition: agent mid-LLM call during cancellation (US-015 Technical Note)

> *"If an agent is mid-LLM call when A11 arrives, the agent must check a cancellation flag before persisting its output."*

US-015 TASK-001 through TASK-007 implement the **cancellation signal** (DB task status = CANCELLED, Pub/Sub `WORKFLOW_CANCELLED` event). The agent cancellation-flag check is an EP-003 responsibility. Confirm:

- `WORKFLOW_CANCELLED` Pub/Sub message is published with the correct `message_type` attribute so the coordinator agent (EP-003) can filter and react.
- The `tasks_cancelled` count in the API response and Pub/Sub body is accurate (returned from the bulk UPDATE rowcount).

---

## Pre-Review Validation Sequence

Run all checks before submitting for review:

```bash
# -----------------------------------------------------------------------
# 1. Syntax check — all new modules
# -----------------------------------------------------------------------
python -c "
import ast, pathlib
targets = [
    # api-gateway
    'api-gateway/app/services/cancellation_service.py',
    'api-gateway/app/services/cancellation_dispatcher.py',
    'api-gateway/app/models/encounter.py',
    # hl7-listener
    'hl7-listener/app/handlers/cancellation_handlers.py',
    'hl7-listener/app/handlers/__init__.py',
]
for p in targets:
    ast.parse(pathlib.Path(p).read_text())
    print(f'  {p}: OK')
print('Syntax check: PASSED')
"

# -----------------------------------------------------------------------
# 2. State machine smoke test
# -----------------------------------------------------------------------
cd api-gateway
python -c "
from app.models.encounter import Encounter, EncounterStatus
from app.exceptions import EncounterStateTransitionError

cases = [
    (EncounterStatus.ADMITTED,    EncounterStatus.PRE_ADMISSION, 'A11'),
    (EncounterStatus.TRANSFERRED, EncounterStatus.ADMITTED,      'A12'),
    (EncounterStatus.DISCHARGED,  EncounterStatus.ADMITTED,      'A13'),
]
for initial, target, event in cases:
    enc = Encounter(status=initial.value)
    enc.transition_to(target)
    assert enc.status == target.value, f'{event} transition failed'
    print(f'  {event}: {initial.value} → {target.value}: OK')

# Invalid transition guard
enc = Encounter(status=EncounterStatus.DISCHARGED.value)
try:
    enc.transition_to(EncounterStatus.PRE_ADMISSION)
    assert False, 'Expected EncounterStateTransitionError'
except EncounterStateTransitionError:
    print('  Invalid transition guard: OK')

print('State machine smoke test: PASSED')
"

# -----------------------------------------------------------------------
# 3. Handler registration smoke test
# -----------------------------------------------------------------------
cd ../hl7-listener
python -c "
from app.handlers.cancellation_handlers import register_cancellation_handlers
from app.parser.router import ADTRouter
from app.models.adt_event import EventType

router = ADTRouter()
register_cancellation_handlers(router=router)
for et in [EventType.CANCEL_ADMIT, EventType.CANCEL_TRANSFER, EventType.CANCEL_DISCHARGE]:
    assert et in router._handlers, f'Handler missing for {et}'
    print(f'  {et.value}: registered OK')
print('Handler registration: PASSED')
"

# -----------------------------------------------------------------------
# 4. Unit tests — api-gateway
# -----------------------------------------------------------------------
cd ../api-gateway
pytest tests/unit/services/test_cancellation_service.py \
       tests/unit/services/test_cancellation_dispatcher.py \
       tests/unit/models/test_encounter_state_machine.py \
       -v --tb=short --cov=app/services/cancellation_service \
          --cov=app/services/cancellation_dispatcher \
          --cov=app/models/encounter \
          --cov-fail-under=80

# -----------------------------------------------------------------------
# 5. Unit tests — hl7-listener
# -----------------------------------------------------------------------
cd ../hl7-listener
pytest tests/unit/handlers/test_cancellation_handlers.py \
       -v --tb=short --cov=app/handlers/cancellation_handlers \
          --cov-fail-under=80

# -----------------------------------------------------------------------
# 6. Integration tests — api-gateway
# -----------------------------------------------------------------------
cd ../api-gateway
pytest tests/integration/ -m integration -v --tb=short

# -----------------------------------------------------------------------
# 7. SAST check (bandit)
# -----------------------------------------------------------------------
cd ..
bandit -r api-gateway/app/services/cancellation_service.py \
           api-gateway/app/services/cancellation_dispatcher.py \
           hl7-listener/app/handlers/cancellation_handlers.py \
       -ll -ii  # report medium+ severity issues only
```

---

## Code Review Checklist

### Security (Security Engineer sign-off required)

- [ ] **PHI-free logs:** `CancellationService`, `CancellationDispatcher`, `cancellation_handlers` logs contain NO patient name, MRN, DOB, or phone — only encounter UUIDs and event type strings
- [ ] **PHI-free Pub/Sub attributes:** `WORKFLOW_CANCELLED` message attributes contain only `message_type`, `event_type`, `encounter_id`, `iso_timestamp`
- [ ] **PHI-free SignalR payload:** `ENCOUNTER_CANCELLED` payload contains only `event`, `encounter_id`, `event_type`, `reason`
- [ ] **Atomic transaction:** encounter status update and task cancellations are within a single `async with session.begin()` block in the API endpoint
- [ ] **No plaintext encounter content in logs:** document content column is never read or logged during cancellation

### Correctness

- [ ] `cancel_agent_tasks()` uses a bulk `UPDATE ... WHERE status NOT IN (terminal_statuses)` — not row-by-row fetching
- [ ] `cancel_agent_tasks()` returns the correct `rowcount` (not hardcoded)
- [ ] `_soft_cancel_documents()` sets `status=CANCELLED` only — does NOT modify `content` column
- [ ] `transition_to()` raises `EncounterStateTransitionError` for invalid transitions — including `DISCHARGED→PRE_ADMISSION` (no direct path)
- [ ] A12 handler restores `current_unit = previous_unit` on the encounter record
- [ ] `CancellationDispatcher.dispatch_post_commit()` is called AFTER `await session.commit()` — never inside the transaction
- [ ] `asyncio.gather(return_exceptions=True)` used — Pub/Sub failure does not prevent SignalR from running

### Resilience

- [ ] HTTP 404 from api-gateway cancellation endpoint → warning log + normal return (no MLLP NACK) — Scenario 4
- [ ] HTTP timeout from api-gateway → error log + exception re-raised (triggers MLLP NACK + Pub/Sub retry)
- [ ] Pub/Sub `WORKFLOW_CANCELLED` publish failure is logged at ERROR but does not raise from `dispatch_post_commit()`
- [ ] SignalR `ENCOUNTER_CANCELLED` broadcast failure is logged at ERROR but does not raise from `dispatch_post_commit()`

### Test Quality

- [ ] Unit tests cover all 4 scenarios (A11, A12, A13, unknown encounter)
- [ ] Integration test verifies DB state post-commit (not just API response)
- [ ] Integration test confirms `document.content` unchanged after A13 soft-cancel
- [ ] Coverage ≥80% on all new modules

---

## US-015 Definition of Done — Final Sign-off

| DoD Item | Task | Status |
|---|---|---|
| Cancellation event handlers for A11, A12, A13 registered in event routing map | TASK-004 | ☐ |
| `cancel_agent_tasks()` updates all non-terminal AgentTask records to CANCELLED | TASK-001 | ☐ |
| Encounter state machine: ADMITTED→PRE_ADMISSION (A11), TRANSFERRED→ADMITTED (A12), DISCHARGED→ADMITTED (A13) | TASK-002 | ☐ |
| SignalR notification published on cancellation (`{event: ENCOUNTER_CANCELLED, encounter_id, reason}`) | TASK-003 | ☐ |
| Cancelled documents retain content with status=CANCELLED — no hard delete | TASK-001 | ☐ |
| Unit tests: each cancellation type with correct state reversion | TASK-005 | ☐ |
| Integration test: A01 → 5 tasks → A11 → all tasks CANCELLED | TASK-006 | ☐ |
| Code reviewed and approved | TASK-007 | ☐ |

**All items must be checked before this story is moved to DONE.**

---

## Reviewer Sign-off

| Role | Name | Date | Signature |
|---|---|---|---|
| Backend Engineer (author) | | | |
| Peer Backend Engineer | | | |
| Security Engineer | | | |
