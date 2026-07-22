"""Unit tests for CancellationService (US-015 TASK-005).

Tests state transitions, agent task cancellation, document soft-cancel,
and error paths for A11, A12, and A13 cancellation events.

Uses MagicMock/AsyncMock to isolate the service from the database.
No PHI fields are asserted — only encounter_id, status strings, and counts.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.exceptions import EncounterNotFoundError, EncounterStateTransitionError
from app.models.encounter import EncounterStatus
from app.services.cancellation_service import (
    CancellationResult,
    CancellationService,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ENC_ID = uuid4()


def _make_encounter(status: EncounterStatus, unit: str = "ICU-1") -> MagicMock:
    """Return a mock Encounter with the given status."""
    enc = MagicMock()
    enc.id = ENC_ID
    enc.status = status.value
    enc.unit = unit
    enc.previous_unit = "WARD-3"

    def transition_to(target: EncounterStatus) -> None:
        enc.status = target.value

    enc.transition_to = MagicMock(side_effect=transition_to)
    return enc


def _make_db(encounter=None) -> AsyncMock:
    """Return a mock AsyncSession."""
    db = AsyncMock()
    db.info = {}
    result = AsyncMock()
    result.scalar_one_or_none = AsyncMock(return_value=encounter)
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.fixture()
def svc() -> CancellationService:
    return CancellationService()


@pytest.mark.asyncio
async def test_cancel_agent_tasks_issues_single_bulk_update(svc: CancellationService):
    """cancel_agent_tasks() must issue exactly 1 bulk UPDATE (not row-by-row)."""
    db = _make_db()
    # reset the mock to count only calls for this test
    db.execute.reset_mock()
    # Make rowcount accessible on the execute result
    result_mock = AsyncMock()
    result_mock.rowcount = 4
    db.execute = AsyncMock(return_value=result_mock)

    count = await svc.cancel_agent_tasks(ENC_ID, db)

    assert count == 4
    assert db.execute.call_count == 1  # must be a single bulk UPDATE, not N individual calls


# ---------------------------------------------------------------------------
# A11 — Cancel Admit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a11_transitions_to_pre_admission(svc: CancellationService):
    """A11 must transition encounter from ADMITTED to PRE_ADMISSION."""
    enc = _make_encounter(EncounterStatus.ADMITTED)
    db = _make_db(encounter=enc)

    with patch.object(svc, "cancel_agent_tasks", new=AsyncMock(return_value=3)), \
         patch.object(svc, "_soft_cancel_documents", new=AsyncMock(return_value=2)):
        result = await svc.handle_cancel_admit(ENC_ID, db)

    enc.transition_to.assert_called_once_with(EncounterStatus.PRE_ADMISSION)
    assert result.event_type == "A11"
    assert result.tasks_cancelled == 3
    assert result.docs_cancelled == 2


@pytest.mark.asyncio
async def test_a11_returns_cancellation_result(svc: CancellationService):
    """A11 result must carry correct encounter_id and event_type."""
    enc = _make_encounter(EncounterStatus.ADMITTED)
    db = _make_db(encounter=enc)

    with patch.object(svc, "cancel_agent_tasks", new=AsyncMock(return_value=0)), \
         patch.object(svc, "_soft_cancel_documents", new=AsyncMock(return_value=1)):
        result = await svc.handle_cancel_admit(ENC_ID, db)

    assert isinstance(result, CancellationResult)
    assert result.encounter_id == ENC_ID


@pytest.mark.asyncio
async def test_a11_raises_not_found_for_unknown_encounter(svc: CancellationService):
    """A11 must raise EncounterNotFoundError when encounter_id is unknown."""
    db = _make_db(encounter=None)

    with pytest.raises(EncounterNotFoundError):
        await svc.handle_cancel_admit(ENC_ID, db)


@pytest.mark.asyncio
async def test_a11_raises_state_transition_error_on_invalid_status(svc: CancellationService):
    """A11 on DISCHARGED encounter must raise EncounterStateTransitionError."""
    enc = _make_encounter(EncounterStatus.DISCHARGED)
    # Override transition_to to raise (simulating real state machine guard)
    enc.transition_to = MagicMock(
        side_effect=EncounterStateTransitionError(
            from_status=EncounterStatus.DISCHARGED.value,
            to_status=EncounterStatus.PRE_ADMISSION.value,
        )
    )
    db = _make_db(encounter=enc)

    with pytest.raises(EncounterStateTransitionError) as exc_info:
        await svc.handle_cancel_admit(ENC_ID, db)

    assert "DISCHARGED" in exc_info.value.detail
    assert "PRE_ADMISSION" in exc_info.value.detail


@pytest.mark.asyncio
async def test_soft_cancel_documents_does_not_modify_content(svc: CancellationService):
    """_soft_cancel_documents must set only status=CANCELLED; content column must not be touched."""
    db = _make_db()
    result_mock = AsyncMock()
    result_mock.rowcount = 2
    db.execute = AsyncMock(return_value=result_mock)

    count = await svc._soft_cancel_documents(ENC_ID, db)

    assert count == 2
    # Inspect the UPDATE statement text — 'content' must not appear
    stmt = db.execute.call_args[0][0]  # first positional arg to execute()
    stmt_str = str(stmt).lower()
    assert "content" not in stmt_str, (
        "_soft_cancel_documents must not modify the content column (DR-005)"
    )


# ---------------------------------------------------------------------------
# A12 — Cancel Transfer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a12_transitions_to_admitted(svc: CancellationService):
    """A12 must transition encounter from TRANSFERRED to ADMITTED."""
    enc = _make_encounter(EncounterStatus.TRANSFERRED)
    db = _make_db(encounter=enc)

    with patch.object(svc, "cancel_agent_tasks", new=AsyncMock(return_value=1)):
        result = await svc.handle_cancel_transfer(ENC_ID, db)

    enc.transition_to.assert_called_once_with(EncounterStatus.ADMITTED)
    assert result.event_type == "A12"
    assert result.docs_cancelled == 0


@pytest.mark.asyncio
async def test_a12_reverts_unit_to_previous_unit(svc: CancellationService):
    """A12 must restore encounter.unit to encounter.previous_unit."""
    enc = _make_encounter(EncounterStatus.TRANSFERRED, unit="NEURO-2")
    enc.previous_unit = "WARD-5"
    db = _make_db(encounter=enc)

    with patch.object(svc, "cancel_agent_tasks", new=AsyncMock(return_value=0)):
        await svc.handle_cancel_transfer(ENC_ID, db)

    assert enc.unit == "WARD-5"


@pytest.mark.asyncio
async def test_a12_raises_not_found_for_unknown_encounter(svc: CancellationService):
    """A12 must raise EncounterNotFoundError when encounter_id is unknown."""
    db = _make_db(encounter=None)

    with pytest.raises(EncounterNotFoundError):
        await svc.handle_cancel_transfer(ENC_ID, db)


# ---------------------------------------------------------------------------
# A13 — Cancel Discharge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a13_transitions_to_admitted(svc: CancellationService):
    """A13 must transition encounter from DISCHARGED to ADMITTED."""
    enc = _make_encounter(EncounterStatus.DISCHARGED)
    db = _make_db(encounter=enc)

    with patch.object(svc, "_soft_cancel_documents", new=AsyncMock(return_value=2)):
        result = await svc.handle_cancel_discharge(ENC_ID, db)

    enc.transition_to.assert_called_once_with(EncounterStatus.ADMITTED)
    assert result.event_type == "A13"


@pytest.mark.asyncio
async def test_a13_sets_session_flag_before_transition(svc: CancellationService):
    """A13 must set the A13 session flag so the state machine allows the transition."""
    enc = _make_encounter(EncounterStatus.DISCHARGED)
    db = _make_db(encounter=enc)

    with patch.object(svc, "_soft_cancel_documents", new=AsyncMock(return_value=0)):
        await svc.handle_cancel_discharge(ENC_ID, db)

    assert "allow_a13_cancel_discharge" in db.info


@pytest.mark.asyncio
async def test_a13_raises_not_found_for_unknown_encounter(svc: CancellationService):
    """A13 must raise EncounterNotFoundError when encounter_id is unknown."""
    db = _make_db(encounter=None)

    with pytest.raises(EncounterNotFoundError):
        await svc.handle_cancel_discharge(ENC_ID, db)
