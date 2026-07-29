"""Unit tests for TranscriptPersistenceService (US-046 TASK-004).

Covers:
    - test_persist_exchange_creates_two_rows
        Two ORM rows (PATIENT + ASSISTANT) are added per call.
    - test_persist_exchange_urgency_flag_set_on_patient_row
        Patient row has urgency_flag=True when urgency_flag=True is passed.
    - test_persist_exchange_assistant_row_flags_always_false
        Assistant row always has urgency_flag=False and escalated=False.
    - test_persist_exchange_escalated_flag_propagated
        Patient row has escalated=True when escalated=True is passed.
    - test_persist_exchange_db_error_does_not_raise
        DB commit raises → exception is swallowed; rollback called; no re-raise.
    - test_encrypted_string_bind_param_is_not_plaintext
        EncryptedString.process_bind_param() output != plaintext input.

US-046 AC Scenario 1:  test_persist_exchange_creates_two_rows confirms 2 rows per exchange
US-046 AC Scenario 2:  urgency/escalated flags tested
US-046 AC Scenario 3:  test_encrypted_string_bind_param_is_not_plaintext confirms ciphertext ≠ plaintext
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.agents.patient_comm.chatbot.transcript_service import (
    TranscriptPersistenceService,
)
from backend.app.db.encryption import EncryptedString
from backend.app.models.chatbot_transcript import MessageRole


@pytest.fixture
def mock_db() -> AsyncMock:
    """Provide a mock AsyncSession."""
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_persist_exchange_creates_two_rows(mock_db: AsyncMock) -> None:
    """Two rows are added to the session and commit is called once."""
    svc = TranscriptPersistenceService(mock_db)

    await svc.persist_exchange(
        encounter_id=uuid.uuid4(),
        patient_message="I feel dizzy",
        assistant_reply="Please rest and stay hydrated.",
        exchange_timestamp=datetime.now(tz=timezone.utc),
    )

    assert (
        mock_db.add.call_count == 2
    ), "Expected exactly 2 rows (PATIENT + ASSISTANT)"
    assert mock_db.commit.call_count == 1


@pytest.mark.asyncio
async def test_persist_exchange_urgency_flag_set_on_patient_row(
    mock_db: AsyncMock,
) -> None:
    """Patient row receives urgency_flag=True when passed True."""
    svc = TranscriptPersistenceService(mock_db)
    added_rows: list = []
    mock_db.add.side_effect = added_rows.append

    await svc.persist_exchange(
        encounter_id=uuid.uuid4(),
        patient_message="I have severe chest pain",
        assistant_reply="Please call emergency services immediately.",
        exchange_timestamp=datetime.now(tz=timezone.utc),
        urgency_flag=True,
        escalated=True,
    )

    patient_row = next(r for r in added_rows if r.role == MessageRole.PATIENT)
    assert patient_row.urgency_flag is True


@pytest.mark.asyncio
async def test_persist_exchange_assistant_row_flags_always_false(
    mock_db: AsyncMock,
) -> None:
    """Assistant row always has urgency_flag=False and escalated=False."""
    svc = TranscriptPersistenceService(mock_db)
    added_rows: list = []
    mock_db.add.side_effect = added_rows.append

    await svc.persist_exchange(
        encounter_id=uuid.uuid4(),
        patient_message="I have severe chest pain",
        assistant_reply="Please call emergency services immediately.",
        exchange_timestamp=datetime.now(tz=timezone.utc),
        urgency_flag=True,
        escalated=True,
    )

    assistant_row = next(r for r in added_rows if r.role == MessageRole.ASSISTANT)
    assert (
        assistant_row.urgency_flag is False
    ), "Assistant row must always have urgency_flag=False"
    assert (
        assistant_row.escalated is False
    ), "Assistant row must always have escalated=False"


@pytest.mark.asyncio
async def test_persist_exchange_escalated_flag_propagated(
    mock_db: AsyncMock,
) -> None:
    """Patient row receives escalated=True when escalated=True is passed."""
    svc = TranscriptPersistenceService(mock_db)
    added_rows: list = []
    mock_db.add.side_effect = added_rows.append

    await svc.persist_exchange(
        encounter_id=uuid.uuid4(),
        patient_message="difficulty breathing",
        assistant_reply="Escalating to care team.",
        exchange_timestamp=datetime.now(tz=timezone.utc),
        urgency_flag=True,
        escalated=True,
    )

    patient_row = next(r for r in added_rows if r.role == MessageRole.PATIENT)
    assert patient_row.escalated is True


@pytest.mark.asyncio
async def test_persist_exchange_db_error_does_not_raise(
    mock_db: AsyncMock,
) -> None:
    """DB commit error is swallowed; rollback is called; no exception propagates."""
    mock_db.commit.side_effect = Exception("DB connection lost")
    svc = TranscriptPersistenceService(mock_db)

    # Must not raise — fire-and-forget contract
    await svc.persist_exchange(
        encounter_id=uuid.uuid4(),
        patient_message="hello",
        assistant_reply="hi",
        exchange_timestamp=datetime.now(tz=timezone.utc),
    )

    mock_db.rollback.assert_called_once()


def test_encrypted_string_bind_param_is_not_plaintext() -> None:
    """EncryptedString TypeDecorator output is ciphertext, not plaintext.

    Verifies US-046 AC Scenario 3: a direct call to process_bind_param
    produces a base64url-encoded AES-256-GCM ciphertext, not the original string.
    """
    enc = EncryptedString()
    plaintext = "chest pain"
    ciphertext = enc.process_bind_param(plaintext, dialect=None)

    assert ciphertext is not None
    assert (
        ciphertext != plaintext
    ), "process_bind_param must return ciphertext, not plaintext"
    # AES-256-GCM ciphertext is base64url-encoded; length > len(plaintext)
    assert len(ciphertext) > len(plaintext)


@pytest.mark.asyncio
async def test_persist_exchange_urgent_scenario_both_flags_true(
    mock_db: AsyncMock,
) -> None:
    """Urgent patient message persisted with urgency_flag=True and escalated=True.

    Verifies US-046 AC Scenario 2: when a patient message is urgent and triggers
    escalation, both the urgency_flag and escalated fields are set to True on
    the patient message row.
    """
    svc = TranscriptPersistenceService(mock_db)
    added_rows: list = []
    mock_db.add.side_effect = added_rows.append

    await svc.persist_exchange(
        encounter_id=uuid.uuid4(),
        patient_message="I am having severe chest pain and difficulty breathing",
        assistant_reply="Please call 911 immediately. Emergency services have been notified.",
        exchange_timestamp=datetime.now(tz=timezone.utc),
        urgency_flag=True,  # Marked urgent by detector
        escalated=True,     # Escalation alert published
    )

    # Verify patient row has both flags set
    patient_row = next(r for r in added_rows if r.role == MessageRole.PATIENT)
    assert patient_row.urgency_flag is True
    assert patient_row.escalated is True

    # Verify assistant row has both flags false
    assistant_row = next(r for r in added_rows if r.role == MessageRole.ASSISTANT)
    assert assistant_row.urgency_flag is False
    assert assistant_row.escalated is False

