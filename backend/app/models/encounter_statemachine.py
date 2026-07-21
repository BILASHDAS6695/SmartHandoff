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

--- A13 Cancel Discharge Usage Pattern ---
The HL7 Listener sets the session flag BEFORE updating encounter.status:

    async with AsyncSessionLocal() as session:
        encounter = await session.get(Encounter, encounter_id)
        # Signal that this is a valid A13 cancel operation
        session.info["allow_a13_cancel_discharge"] = str(encounter.id)
        encounter.status = EncounterStatus.ADMITTED.value  # Now allowed
        await session.commit()

The flag is automatically cleared by the event listener after first use,
preventing accidental reuse.
"""
from __future__ import annotations

from sqlalchemy import event

from app.exceptions import EncounterStateTransitionError
from app.models.encounter import Encounter, EncounterStatus

# ---------------------------------------------------------------------------
# State machine transition table
# ---------------------------------------------------------------------------
# Maps (from_status, to_status) → whether the transition is unconditionally
# allowed. Transitions mapped to None require a context flag (see below).
# ---------------------------------------------------------------------------
_ALLOWED_TRANSITIONS: dict[tuple[str, str], bool | None] = {
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
# Usage: session.info["allow_a13_cancel_discharge"] = str(encounter_id)
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
