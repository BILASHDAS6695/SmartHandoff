---
id: TASK-002
title: "Extend `api-gateway/app/models/encounter.py` — Add Cancellation Transitions to Encounter State Machine (PRE_ADMISSION status, A11/A12/A13 revert paths)"
user_story: US-015
epic: EP-001
sprint: 2
layer: Backend
estimate: 2h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-006/TASK-001]
---

# TASK-002: Extend `api-gateway/app/models/encounter.py` — Add Cancellation Transitions to Encounter State Machine (PRE_ADMISSION status, A11/A12/A13 revert paths)

> **Story:** US-015 | **Epic:** EP-001 | **Sprint:** 2 | **Layer:** Backend | **Est:** 2 h
> **Status:** Done | **Date:** 2026-07-22

---

## Context

US-006 defined the initial encounter state machine with the following transitions:

```
REGISTERED → ADMITTED → TRANSFERRED → DISCHARGED
                      ↘ DISCHARGED
```

US-015 extends this machine with three cancellation revert paths:

```
ADMITTED    → PRE_ADMISSION   (A11 — cancel admit)
TRANSFERRED → ADMITTED        (A12 — cancel transfer)
DISCHARGED  → ADMITTED        (A13 — cancel discharge, allows re-admit)
```

US-015 Acceptance Criteria Scenario 1 explicitly states the A11 target is `PRE_ADMISSION`:

> *"the encounter status reverts to `PRE_ADMISSION`"*

And US-006 Technical Notes note `DISCHARGED→ADMITTED` for A13: *"only on A13 cancel."*

This task also adds the `previous_unit` column to `Encounter`, required by A12 handling in TASK-001:

> US-015 Scenario 2: *"the encounter's `current_unit` reverts to `3A`"* — only possible if the pre-transfer unit was persisted.

**State machine representation (complete after this task):**

```
                    ┌──────────────────┐
                    │   PRE_ADMISSION  │◄──── A11 (cancel admit)
                    └────────┬─────────┘
                             │ A01 (Admit)
                             ▼
                        ┌─────────┐
                        │ ADMITTED │◄──── A12 (cancel transfer)
                        └────┬────┘◄──── A13 (cancel discharge)
                             │
              ┌──────────────┤
              │ A02 (Transfer)│ A03 (Discharge)
              ▼               ▼
        ┌────────────┐  ┌────────────┐
        │ TRANSFERRED│  │ DISCHARGED │
        └────────────┘  └────────────┘
```

Design decisions:

| Decision | Rationale |
|----------|-----------|
| `PRE_ADMISSION` as its own status (not `REGISTERED`) | A11 cancels an already-processed admit; the encounter record exists and should not revert to `REGISTERED` (which implies no PID segment was processed). `PRE_ADMISSION` signals "admit was cancelled, encounter is on hold." |
| `previous_unit` column (nullable UUID FK to bed/unit) | Required for A12 revert; populated on every A02 transfer event (new column, backward-compatible — nullable) |
| `transition_to()` method on ORM model | Centralises state machine logic; prevents service layer from directly assigning `encounter.status` without validation (DR-023) |
| Allowed transitions as a `frozenset` of `(from, to)` tuples | O(1) lookup; easy to extend; single source of truth for all permitted transitions |
| `EncounterStateTransitionError` on invalid transition | Maps to 409 Conflict at the API layer; never silently ignored |

Design refs: DR-023, FR-006, US-006, US-015 SC-1 to SC-3.

---

## Acceptance Criteria Addressed

| US-015 AC | Requirement |
|---|---|
| **Scenario 1 (A11)** | `encounter.transition_to(EncounterStatus.PRE_ADMISSION)` succeeds when current status is `ADMITTED`; raises if status is anything else |
| **Scenario 2 (A12)** | `encounter.transition_to(EncounterStatus.ADMITTED)` succeeds when current status is `TRANSFERRED`; `encounter.previous_unit` column exists for revert |
| **Scenario 3 (A13)** | `encounter.transition_to(EncounterStatus.ADMITTED)` succeeds when current status is `DISCHARGED` |
| **Scenario 2 (DoD)** | State machine extended to allow specified cancellation transitions; `EncounterStateTransitionError` raised on invalid transitions |

---

## Implementation Steps

### 1. Add `PRE_ADMISSION` to `EncounterStatus` enum

Locate `api-gateway/app/models/encounter.py` (created in US-006). Extend `EncounterStatus`:

```python
import enum


class EncounterStatus(str, enum.Enum):
    """Encounter lifecycle statuses.

    Valid transitions:
        REGISTERED     → ADMITTED          (A01)
        PRE_ADMISSION  → ADMITTED          (A01 re-admit after A11 cancel)
        ADMITTED       → TRANSFERRED       (A02)
        ADMITTED       → DISCHARGED        (A03)
        ADMITTED       → PRE_ADMISSION     (A11 cancel admit)      ← NEW
        TRANSFERRED    → DISCHARGED        (A03)
        TRANSFERRED    → ADMITTED          (A12 cancel transfer)   ← NEW
        DISCHARGED     → ADMITTED          (A13 cancel discharge)  ← NEW
    """
    REGISTERED    = "REGISTERED"
    PRE_ADMISSION = "PRE_ADMISSION"   # ← NEW: target of A11 cancel
    ADMITTED      = "ADMITTED"
    TRANSFERRED   = "TRANSFERRED"
    DISCHARGED    = "DISCHARGED"
```

### 2. Define `_ALLOWED_TRANSITIONS` set

```python
# Complete set of permitted (from_status, to_status) transitions.
# Any pair NOT listed here raises EncounterStateTransitionError.
_ALLOWED_TRANSITIONS: frozenset[tuple[EncounterStatus, EncounterStatus]] = frozenset(
    {
        # Forward path
        (EncounterStatus.REGISTERED,    EncounterStatus.ADMITTED),
        (EncounterStatus.PRE_ADMISSION, EncounterStatus.ADMITTED),   # re-admit after A11
        (EncounterStatus.ADMITTED,      EncounterStatus.TRANSFERRED),
        (EncounterStatus.ADMITTED,      EncounterStatus.DISCHARGED),
        (EncounterStatus.TRANSFERRED,   EncounterStatus.DISCHARGED),
        # Cancellation revert paths (US-015)
        (EncounterStatus.ADMITTED,      EncounterStatus.PRE_ADMISSION),  # A11
        (EncounterStatus.TRANSFERRED,   EncounterStatus.ADMITTED),       # A12
        (EncounterStatus.DISCHARGED,    EncounterStatus.ADMITTED),       # A13
    }
)
```

### 3. Add `transition_to()` method to the `Encounter` ORM model

```python
from app.exceptions import EncounterStateTransitionError

class Encounter(Base):
    __tablename__ = "encounter"

    # ... existing columns from US-006 ...

    # NEW column (US-015): records the unit before a transfer — enables A12 revert
    previous_unit: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="Unit occupied before last A02 transfer; used for A12 cancel-transfer revert",
    )

    def transition_to(self, target: EncounterStatus) -> None:
        """Attempt a state transition, raising on invalid target.

        Args:
            target: The new desired status.

        Raises:
            EncounterStateTransitionError: If the (current → target) pair is
                not in ``_ALLOWED_TRANSITIONS``.

        Example::

            encounter.transition_to(EncounterStatus.PRE_ADMISSION)  # A11
            # If encounter.status == ADMITTED, this succeeds.
            # If encounter.status == DISCHARGED, this raises 409.
        """
        current = EncounterStatus(self.status)
        if (current, target) not in _ALLOWED_TRANSITIONS:
            raise EncounterStateTransitionError(
                current=current.value,
                target=target.value,
            )
        self.status = target.value
```

### 4. Create Alembic migration for `previous_unit` column

```bash
cd api-gateway
alembic revision --autogenerate=false -m "add_previous_unit_to_encounter_us015"
```

In the generated migration file, hand-author:

```python
def upgrade() -> None:
    op.add_column(
        "encounter",
        sa.Column(
            "previous_unit",
            sa.String(50),
            nullable=True,
            comment="Unit before last A02 transfer; used for A12 cancel-transfer revert",
        ),
    )


def downgrade() -> None:
    op.drop_column("encounter", "previous_unit")
```

### 5. Update `previous_unit` on A02 transfer events

In the existing A02 handler (implemented in a prior story or to be extended), add:

```python
# Before updating current_unit:
encounter.previous_unit = encounter.current_unit
encounter.current_unit = new_unit
```

This ensures `previous_unit` is always populated before an A12 can occur.

### 6. Verify state machine transitions

```python
# Quick smoke test — run from api-gateway/ directory
python -c "
from app.models.encounter import Encounter, EncounterStatus, _ALLOWED_TRANSITIONS
from app.exceptions import EncounterStateTransitionError

# A11: ADMITTED → PRE_ADMISSION
e = Encounter(status=EncounterStatus.ADMITTED.value)
e.transition_to(EncounterStatus.PRE_ADMISSION)
assert e.status == 'PRE_ADMISSION', 'A11 revert failed'

# A12: TRANSFERRED → ADMITTED
e2 = Encounter(status=EncounterStatus.TRANSFERRED.value)
e2.transition_to(EncounterStatus.ADMITTED)
assert e2.status == 'ADMITTED', 'A12 revert failed'

# A13: DISCHARGED → ADMITTED
e3 = Encounter(status=EncounterStatus.DISCHARGED.value)
e3.transition_to(EncounterStatus.ADMITTED)
assert e3.status == 'ADMITTED', 'A13 revert failed'

# Invalid: DISCHARGED → PRE_ADMISSION (must raise)
e4 = Encounter(status=EncounterStatus.DISCHARGED.value)
try:
    e4.transition_to(EncounterStatus.PRE_ADMISSION)
    assert False, 'Should have raised EncounterStateTransitionError'
except EncounterStateTransitionError:
    pass

print('State machine smoke test: PASSED')
"
```

---

## Definition of Done Checklist

- [ ] `EncounterStatus.PRE_ADMISSION` added to the enum
- [ ] `_ALLOWED_TRANSITIONS` includes all 3 cancellation revert paths
- [ ] `Encounter.transition_to()` raises `EncounterStateTransitionError` for invalid transitions
- [ ] `Encounter.previous_unit` nullable column added
- [ ] Alembic migration created for `previous_unit` column addition
- [ ] A02 handler updated to persist `previous_unit` before overwriting `current_unit`
- [ ] Smoke test passes for A11, A12, A13 transitions and invalid transition guard
