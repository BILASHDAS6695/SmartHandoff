---
id: TASK-006
title: "Implement Encounter State Machine as SQLAlchemy ORM Event Listener"
user_story: US-006
epic: EP-DATA
sprint: 1
layer: Backend
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [TASK-004]
---

# TASK-006: Implement Encounter State Machine as SQLAlchemy ORM Event Listener

> **Story:** US-006 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Backend | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

**Acceptance Criterion 2** of US-006 explicitly requires that the encounter state machine be enforced **at the ORM layer** before any DB write occurs:

> *"When an application attempts to set `status=ADMITTED` via the ORM (not a valid A13 cancel scenario), Then a `EncounterStateTransitionError` (409) is raised before any DB write occurs; the encounter status remains `DISCHARGED`."*

Using a SQLAlchemy `@event.listens_for(Encounter.status, "set")` event listener achieves this: the validator intercepts every `encounter.status = <new_value>` assignment and raises before the session is flushed, preventing the invalid state from reaching the database.

Design doc (design.md) defines the allowed transitions:
- `ADMITTED → TRANSFERRED`
- `ADMITTED → DISCHARGED`
- `TRANSFERRED → DISCHARGED`
- `DISCHARGED → ADMITTED` *(only on A13 cancel-discharge event — signaled by a context flag)*

Any other transition raises `EncounterStateTransitionError` with HTTP 409.

The `REGISTERED → ADMITTED` transition (first admission) is implicitly allowed as the initial transition from the non-terminal starting state.

---

## Acceptance Criteria Addressed

| US-006 AC | Requirement |
|---|---|
| **Scenario 2** | `DISCHARGED → ADMITTED` (non-A13) must raise `EncounterStateTransitionError` before any DB write |
| **DoD** | Encounter state machine implemented as an ORM event listener validating allowed transitions |

---

## Implementation Steps

### 1. Define `EncounterStateTransitionError` in `backend/app/exceptions.py`

```python
"""Application-level exception hierarchy.

Exceptions here are caught by FastAPI exception handlers and converted
to structured HTTP responses. No PHI is included in exception messages.
"""
from __future__ import annotations

from fastapi import HTTPException, status


class EncounterStateTransitionError(HTTPException):
    """Raised when an invalid encounter status transition is attempted.

    Returns HTTP 409 Conflict.
    No encounter data (patient ID, MRN) is included in the detail message
    to prevent PHI leakage in error responses (OWASP A01).
    """

    def __init__(
        self,
        from_status: str,
        to_status: str,
        *,
        encounter_id: str | None = None,
    ) -> None:
        detail = (
            f"Invalid encounter status transition: "
            f"'{from_status}' → '{to_status}'. "
            "Transition is not permitted by the clinical workflow rules."
        )
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        )
        self.from_status = from_status
        self.to_status = to_status
        self.encounter_id = encounter_id  # Used for logging only, not exposed in response
```

### 2. Author `backend/app/models/encounter_statemachine.py`

This module registers the SQLAlchemy event listener. It is imported once at application startup (via `app/models/__init__.py`) to activate the listener.

```python
"""Encounter status state machine — SQLAlchemy ORM event listener.

DR-023: Encounter status transitions are restricted to clinically valid paths.
The event listener fires on every `encounter.status = <value>` assignment,
BEFORE the session is flushed or committed, preventing invalid states from
reaching the database.

Allowed transitions:
    REGISTERED  → ADMITTED      (A01: initial admission)
    ADMITTED    → TRANSFERRED   (A02: transfer to another unit)
    ADMITTED    → DISCHARGED    (A03: discharge)
    TRANSFERRED → DISCHARGED    (A03: discharge from transferred unit)
    DISCHARGED  → ADMITTED      (A13: cancel discharge — explicit flag required)

All other transitions raise EncounterStateTransitionError (HTTP 409).
"""
from __future__ import annotations

from sqlalchemy import event

from app.exceptions import EncounterStateTransitionError
from app.models.encounter import Encounter, EncounterStatus

# ---------------------------------------------------------------------------
# State machine transition table
# ---------------------------------------------------------------------------
# Maps (from_status, to_status) → whether the transition is unconditionally
# allowed. Transitions marked as None require a context flag (see below).
# ---------------------------------------------------------------------------
_ALLOWED_TRANSITIONS: dict[tuple[str, str], bool] = {
    # Standard clinical workflow (unconditional)
    (EncounterStatus.REGISTERED.value, EncounterStatus.ADMITTED.value): True,
    (EncounterStatus.ADMITTED.value, EncounterStatus.TRANSFERRED.value): True,
    (EncounterStatus.ADMITTED.value, EncounterStatus.DISCHARGED.value): True,
    (EncounterStatus.TRANSFERRED.value, EncounterStatus.DISCHARGED.value): True,
    # A13 Cancel Discharge — requires the caller to set a context flag on the
    # session to signal this is an intentional reversal (not a coding error).
    (EncounterStatus.DISCHARGED.value, EncounterStatus.ADMITTED.value): None,
}

# Session-level flag name used to authorise DISCHARGED → ADMITTED transitions.
# Usage: session.info["allow_a13_cancel_discharge"] = encounter_id
_A13_FLAG = "allow_a13_cancel_discharge"


@event.listens_for(Encounter.status, "set")
def validate_encounter_status_transition(
    target: Encounter,
    value: str,
    oldvalue: str,
    initiator,  # noqa: ANN001 — SQLAlchemy event parameter
) -> str:
    """Validate encounter status transitions before ORM sets the attribute.

    Raises:
        EncounterStateTransitionError: If the transition is not permitted.

    Returns:
        The new status value (passed through if valid).
    """
    # Allow initial INSERT (oldvalue is a SQLAlchemy symbol, not a string)
    # SQLAlchemy uses `NEVER_SET` and `NO_VALUE` symbols for uninitialised attrs.
    if not isinstance(oldvalue, str):
        return value

    # No-op: same status (e.g., repeated flush)
    if oldvalue == value:
        return value

    transition = (oldvalue, value)
    allowed = _ALLOWED_TRANSITIONS.get(transition)

    if allowed is True:
        # Unconditionally allowed transition
        return value

    if allowed is None:
        # DISCHARGED → ADMITTED: requires explicit A13 cancel flag on session
        # Access the session via the instance state
        session = _get_session(target)
        if session is not None and session.info.get(_A13_FLAG) == str(target.id):
            # Valid A13 cancel — clear the flag after use to prevent reuse
            session.info.pop(_A13_FLAG, None)
            return value
        # A13 flag absent — this is an invalid transition
        raise EncounterStateTransitionError(
            from_status=oldvalue,
            to_status=value,
            encounter_id=str(target.id) if target.id else None,
        )

    # Transition not in allowed map — reject
    raise EncounterStateTransitionError(
        from_status=oldvalue,
        to_status=value,
        encounter_id=str(target.id) if target.id else None,
    )


def _get_session(instance: Encounter):
    """Retrieve the SQLAlchemy session associated with an ORM instance.

    Returns None if the instance is detached (no session bound).
    """
    from sqlalchemy.orm import object_session
    return object_session(instance)
```

### 3. Register the State Machine at Application Startup

Update `backend/app/models/__init__.py` to import the state machine module. The import itself triggers the `@event.listens_for` registration:

```python
from app.models.adt_event import AdtEvent
from app.models.agent_task import AgentTask
from app.models.app_user import AppUser
from app.models.audit_log import AuditLog
from app.models.bed import Bed
from app.models.chatbot_transcript import ChatbotTranscript
from app.models.document import Document
from app.models.encounter import Encounter, EncounterStatus, RiskTier
from app.models.medication import Medication
from app.models.patient import Patient

# Import state machine module to register the SQLAlchemy event listener.
# This import must occur after Encounter is defined.
import app.models.encounter_statemachine as _encounter_sm  # noqa: F401, E402

__all__ = [
    "AdtEvent",
    "AgentTask",
    "AppUser",
    "AuditLog",
    "Bed",
    "ChatbotTranscript",
    "Document",
    "Encounter",
    "EncounterStatus",
    "Medication",
    "Patient",
    "RiskTier",
]
```

### 4. Document the A13 Cancel Pattern for Callers

Add an inline usage comment to `encounter_statemachine.py` showing how the HL7 Listener should signal an A13 cancel event:

```python
# --- A13 Cancel Discharge Usage Pattern ---
# The HL7 Listener sets the session flag BEFORE updating encounter.status:
#
#   async with AsyncSessionLocal() as session:
#       encounter = await session.get(Encounter, encounter_id)
#       # Signal that this is a valid A13 cancel operation
#       session.info["allow_a13_cancel_discharge"] = str(encounter.id)
#       encounter.status = EncounterStatus.ADMITTED.value  # Now allowed
#       await session.commit()
#
# The flag is automatically cleared by the event listener after first use,
# preventing accidental reuse.
```

---

## Definition of Done

- [ ] `backend/app/exceptions.py` defines `EncounterStateTransitionError(HTTPException)` with HTTP 409 status code
- [ ] `backend/app/models/encounter_statemachine.py` registers `@event.listens_for(Encounter.status, "set")` listener
- [ ] `_ALLOWED_TRANSITIONS` map covers all 5 valid transitions (REGISTERED→ADMITTED, ADMITTED→TRANSFERRED, ADMITTED→DISCHARGED, TRANSFERRED→DISCHARGED, DISCHARGED→ADMITTED [A13 only])
- [ ] Non-string `oldvalue` (uninitialised attribute) bypassed without error (initial INSERT path)
- [ ] `DISCHARGED → ADMITTED` without A13 flag raises `EncounterStateTransitionError` (HTTP 409)
- [ ] `DISCHARGED → ADMITTED` with `session.info["allow_a13_cancel_discharge"] = str(encounter.id)` succeeds
- [ ] A13 session flag is consumed (cleared) after first successful use
- [ ] No PHI (patient ID, MRN, name) in exception `detail` message
- [ ] `backend/app/models/__init__.py` imports `encounter_statemachine` to register the listener at startup

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-004 | Preceding task | `Encounter`, `EncounterStatus` model and enum must be defined |

---

## Files Modified

| File | Action |
|---|---|
| `backend/app/exceptions.py` | Create |
| `backend/app/models/encounter_statemachine.py` | Create |
| `backend/app/models/__init__.py` | Update (import statemachine module) |
