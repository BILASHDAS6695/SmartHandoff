"""Unit tests for encounter state machine — A11, A12, A13 + invalid transitions (US-015 TASK-005)."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from app.models.encounter import EncounterStatus
from app.models.encounter_statemachine import _ALLOWED_TRANSITIONS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _key(from_: EncounterStatus, to: EncounterStatus):
    return (from_.value, to.value)


# ---------------------------------------------------------------------------
# Allowed transitions (US-015 additions)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("from_status,to_status", [
    (EncounterStatus.ADMITTED, EncounterStatus.PRE_ADMISSION),   # A11
    (EncounterStatus.TRANSFERRED, EncounterStatus.ADMITTED),      # A12
    (EncounterStatus.PRE_ADMISSION, EncounterStatus.ADMITTED),    # re-admit after A11
])
def test_us015_transitions_allowed(from_status, to_status):
    """US-015 A11/A12 transitions and re-admit path must be registered."""
    key = _key(from_status, to_status)
    assert key in _ALLOWED_TRANSITIONS, (
        f"Expected transition {key} to be registered in _ALLOWED_TRANSITIONS"
    )


def test_a13_transition_registered():
    """A13 DISCHARGED → ADMITTED transition must be registered (requires session flag)."""
    key = _key(EncounterStatus.DISCHARGED, EncounterStatus.ADMITTED)
    assert key in _ALLOWED_TRANSITIONS


# ---------------------------------------------------------------------------
# Invalid / not registered transitions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("from_status,to_status", [
    # PRE_ADMISSION has no direct path to DISCHARGED (must re-admit first)
    (EncounterStatus.PRE_ADMISSION, EncounterStatus.DISCHARGED),
    # DISCHARGED → TRANSFERRED is never valid
    (EncounterStatus.DISCHARGED, EncounterStatus.TRANSFERRED),
    # ADMITTED → REGISTERED is a backwards transition (never valid)
    (EncounterStatus.ADMITTED, EncounterStatus.REGISTERED),
    # TRANSFERRED → REGISTERED is never valid
    (EncounterStatus.TRANSFERRED, EncounterStatus.REGISTERED),
])
def test_invalid_transitions_not_registered(from_status, to_status):
    """Illegal state machine paths must NOT appear in _ALLOWED_TRANSITIONS."""
    key = _key(from_status, to_status)
    # Either not in dict at all, or mapping is falsy — both represent blocked transitions
    entry = _ALLOWED_TRANSITIONS.get(key)
    assert entry is False or key not in _ALLOWED_TRANSITIONS, (
        f"Unexpected allowed transition: {key}"
    )


def test_pre_admission_enum_value():
    """PRE_ADMISSION enum value must be the string 'PRE_ADMISSION' (TASK-005 DoD)."""
    assert EncounterStatus.PRE_ADMISSION.value == "PRE_ADMISSION"


def test_admitted_to_discharged_is_valid_a03():
    """ADMITTED → DISCHARGED is a valid A03 transition and must be registered."""
    key = _key(EncounterStatus.ADMITTED, EncounterStatus.DISCHARGED)
    assert key in _ALLOWED_TRANSITIONS
