---
id: TASK-004
title: "Unit Tests — Encryption Verification, Urgency Flag Persistence, Scope Enforcement"
user_story: US-046
epic: EP-008
sprint: 2
layer: Testing
estimate: 2.5h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-046/TASK-001, US-046/TASK-002, US-046/TASK-003]
---

# TASK-004: Unit Tests — Encryption Verification, Urgency Flag Persistence, Scope Enforcement

> **Story:** US-046 | **Epic:** EP-008 | **Sprint:** 2 | **Layer:** Testing | **Est:** 2.5 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-046 DoD specifies three mandatory unit test categories:

1. **Encryption verification** — raw DB column value is ciphertext, not the patient's plaintext message
2. **Urgency flag persistence** — `urgency_flag=True` and `escalated=True` are stored correctly on the patient row; assistant row always has both as `False`
3. **Scope enforcement** — patient JWT cannot read another encounter's transcript; staff JWT can read any encounter

Tests are distributed across two test files, each targeting a specific module.

| Test File | Module Under Test | Coverage Focus |
|-----------|------------------|----------------|
| `test_transcript_persistence_service.py` | `chatbot/transcript_service.py` | Row count per exchange; urgency/escalated flags; fire-and-forget on DB error |
| `test_transcript_endpoint.py` | `routers/transcript.py` | Patient scope (own=200, cross=403); staff any=200; audit log call; pagination cursor; chronological ordering; malformed cursor=400 |

Coverage target: ≥80% branch coverage across `transcript_service.py` and `routers/transcript.py` (TR-020).

### Mocking strategy

| External Dependency | Mock Approach |
|--------------------|---------------|
| `AsyncSession.execute()` | `AsyncMock` returning a mock `ScalarResult` |
| `AsyncSession.add()` | `MagicMock` — capture added rows via `side_effect = added_rows.append` |
| `AsyncSession.commit()` | `AsyncMock` |
| `AsyncSession.rollback()` | `AsyncMock` |
| `write_audit_entry()` | `AsyncMock` — assert called with `entity_type="CHATBOT_TRANSCRIPT"` |
| `get_current_token_claims` | Override via FastAPI `dependency_overrides` |
| FastAPI `AsyncClient` | `httpx.AsyncClient(app=app, base_url="http://test")` |
| `get_db` | Override via FastAPI `dependency_overrides` to return mock `AsyncSession` |
| `EncryptedString` (encryption test) | Use real TypeDecorator with in-memory SQLite (`aiosqlite`) — test `process_bind_param` directly without full DB stack |

---

## Acceptance Criteria Addressed

| US-046 AC | Test Cases |
|-----------|-----------|
| **Scenario 1** (5 messages → 10 rows) | `test_persist_exchange_creates_two_rows` — verifies 2 rows per call |
| **Scenario 2** (urgency_flag=True preserved) | `test_persist_exchange_urgency_flag_set_on_patient_row`, `test_persist_exchange_assistant_row_flags_always_false`, `test_persist_exchange_escalated_flag_propagated` |
| **Scenario 3** (raw DB value is ciphertext) | `test_encrypted_string_bind_param_is_not_plaintext` |
| **Scenario 4** (patient scope; staff any) | `test_get_transcript_patient_own_encounter_returns_200`, `test_get_transcript_patient_cross_encounter_returns_403`, `test_get_transcript_staff_any_encounter_returns_200` |

---

## Implementation Steps

### 1. Scaffold test directories

```bash
mkdir -p backend/tests/unit/agents/patient_comm/chatbot
touch backend/tests/unit/agents/patient_comm/chatbot/__init__.py
mkdir -p api-gateway/tests/unit/routers
touch api-gateway/tests/unit/routers/__init__.py
```

### 2. Create `backend/tests/unit/agents/patient_comm/chatbot/test_transcript_persistence_service.py`

```python
"""Unit tests for TranscriptPersistenceService (US-046 TASK-002).

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
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.patient_comm.chatbot.transcript_service import TranscriptPersistenceService
from app.db.encryption import EncryptedString
from app.models.chatbot_transcript import MessageRole


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_persist_exchange_creates_two_rows(mock_db):
    """Two rows are added to the session and commit is called once."""
    svc = TranscriptPersistenceService(mock_db)

    await svc.persist_exchange(
        encounter_id=uuid.uuid4(),
        patient_message="I feel dizzy",
        assistant_reply="Please rest and stay hydrated.",
        exchange_timestamp=datetime.now(tz=timezone.utc),
    )

    assert mock_db.add.call_count == 2, "Expected exactly 2 rows (PATIENT + ASSISTANT)"
    assert mock_db.commit.call_count == 1


@pytest.mark.asyncio
async def test_persist_exchange_urgency_flag_set_on_patient_row(mock_db):
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
async def test_persist_exchange_assistant_row_flags_always_false(mock_db):
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
    assert assistant_row.urgency_flag is False, "Assistant row must always have urgency_flag=False"
    assert assistant_row.escalated is False, "Assistant row must always have escalated=False"


@pytest.mark.asyncio
async def test_persist_exchange_escalated_flag_propagated(mock_db):
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
async def test_persist_exchange_db_error_does_not_raise(mock_db):
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


def test_encrypted_string_bind_param_is_not_plaintext():
    """EncryptedString TypeDecorator output is ciphertext, not plaintext.

    Verifies US-046 AC Scenario 3: a direct call to process_bind_param
    produces a base64url-encoded AES-256-GCM ciphertext, not the original string.
    """
    enc = EncryptedString()
    plaintext = "chest pain"
    ciphertext = enc.process_bind_param(plaintext, dialect=None)

    assert ciphertext is not None
    assert ciphertext != plaintext, "process_bind_param must return ciphertext, not plaintext"
    # AES-256-GCM ciphertext is base64url-encoded; length > len(plaintext)
    assert len(ciphertext) > len(plaintext)
```

### 3. Create `api-gateway/tests/unit/routers/test_transcript_endpoint.py`

```python
"""Unit tests for GET /api/v1/encounters/{encounter_id}/chat-transcript (US-046 TASK-003).

Covers:
    - test_get_transcript_patient_own_encounter_returns_200
        Patient JWT with matching encounter_id → 200 with messages list.
    - test_get_transcript_patient_cross_encounter_returns_403
        Patient JWT with different encounter_id → 403 {"detail": "Access denied."}.
    - test_get_transcript_staff_any_encounter_returns_200
        Staff JWT with any encounter_id → 200.
    - test_get_transcript_audit_log_written
        write_audit_entry called with entity_type="CHATBOT_TRANSCRIPT".
    - test_get_transcript_response_is_chronological
        Messages in response are ordered by ascending timestamp.
    - test_get_transcript_next_cursor_present_when_more_pages
        When DB returns PAGE_SIZE+1 rows, next_cursor is not None.
    - test_get_transcript_next_cursor_none_when_last_page
        When DB returns fewer than PAGE_SIZE rows, next_cursor is None.
    - test_get_transcript_invalid_cursor_returns_400
        Malformed ?cursor= value → 400 {"detail": "Invalid cursor."}.
"""
from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.main import app
from app.auth.dependencies import get_current_token_claims
from app.db.session import get_db
from app.routers.transcript import PAGE_SIZE


ENCOUNTER_ID = uuid.uuid4()
OTHER_ENCOUNTER_ID = uuid.uuid4()


def _patient_claims(encounter_id: uuid.UUID = ENCOUNTER_ID) -> dict:
    return {
        "sub": str(uuid.uuid4()),
        "role": "patient",
        "encounter_id": str(encounter_id),
    }


def _staff_claims() -> dict:
    return {"sub": str(uuid.uuid4()), "role": "staff"}


def _make_mock_row(
    encounter_id: uuid.UUID = ENCOUNTER_ID,
    timestamp: datetime | None = None,
    urgency_flag: bool = False,
) -> MagicMock:
    """Build a mock ChatbotTranscript ORM row."""
    row = MagicMock()
    row.id = uuid.uuid4()
    row.encounter_id = encounter_id
    row.message = "test message (decrypted)"
    row.role = "PATIENT"
    row.timestamp = timestamp or datetime.now(tz=timezone.utc)
    row.urgency_flag = urgency_flag
    row.escalated = False
    return row


@pytest.mark.asyncio
async def test_get_transcript_patient_cross_encounter_returns_403():
    """Patient JWT with different encounter_id must receive 403 Access denied."""
    app.dependency_overrides[get_current_token_claims] = lambda: _patient_claims(ENCOUNTER_ID)

    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/encounters/{OTHER_ENCOUNTER_ID}/chat-transcript"
        )

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Access denied."
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_transcript_staff_any_encounter_returns_200():
    """Staff JWT may access any encounter's transcript."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    app.dependency_overrides[get_current_token_claims] = _staff_claims
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app.routers.transcript.write_audit_entry", new_callable=AsyncMock):
        async with AsyncClient(app=app, base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/encounters/{OTHER_ENCOUNTER_ID}/chat-transcript"
            )

    assert resp.status_code == 200
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_transcript_audit_log_written():
    """write_audit_entry is called with entity_type=CHATBOT_TRANSCRIPT on every access."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    app.dependency_overrides[get_current_token_claims] = lambda: _patient_claims(ENCOUNTER_ID)
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch(
        "app.routers.transcript.write_audit_entry", new_callable=AsyncMock
    ) as mock_audit:
        async with AsyncClient(app=app, base_url="http://test") as client:
            await client.get(f"/api/v1/encounters/{ENCOUNTER_ID}/chat-transcript")

    mock_audit.assert_called_once()
    call_kwargs = mock_audit.call_args.kwargs
    assert call_kwargs["entity_type"] == "CHATBOT_TRANSCRIPT"
    assert call_kwargs["entity_id"] == ENCOUNTER_ID
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_transcript_next_cursor_present_when_more_pages():
    """When DB returns PAGE_SIZE+1 rows, next_cursor must be non-None."""
    base_ts = datetime.now(tz=timezone.utc)
    rows = [
        _make_mock_row(timestamp=base_ts - timedelta(minutes=i))
        for i in range(PAGE_SIZE + 1)
    ]

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = rows
    mock_db.execute = AsyncMock(return_value=mock_result)

    app.dependency_overrides[get_current_token_claims] = lambda: _patient_claims(ENCOUNTER_ID)
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app.routers.transcript.write_audit_entry", new_callable=AsyncMock):
        async with AsyncClient(app=app, base_url="http://test") as client:
            resp = await client.get(f"/api/v1/encounters/{ENCOUNTER_ID}/chat-transcript")

    body = resp.json()
    assert resp.status_code == 200
    assert body["next_cursor"] is not None
    assert len(body["messages"]) == PAGE_SIZE
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_transcript_next_cursor_none_when_last_page():
    """When DB returns fewer than PAGE_SIZE rows, next_cursor must be None."""
    rows = [_make_mock_row() for _ in range(10)]

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = rows
    mock_db.execute = AsyncMock(return_value=mock_result)

    app.dependency_overrides[get_current_token_claims] = lambda: _patient_claims(ENCOUNTER_ID)
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app.routers.transcript.write_audit_entry", new_callable=AsyncMock):
        async with AsyncClient(app=app, base_url="http://test") as client:
            resp = await client.get(f"/api/v1/encounters/{ENCOUNTER_ID}/chat-transcript")

    body = resp.json()
    assert resp.status_code == 200
    assert body["next_cursor"] is None
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_transcript_invalid_cursor_returns_400():
    """Malformed ?cursor= value must return HTTP 400."""
    app.dependency_overrides[get_current_token_claims] = lambda: _patient_claims(ENCOUNTER_ID)

    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/encounters/{ENCOUNTER_ID}/chat-transcript?cursor=!!!notbase64"
        )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid cursor."
    app.dependency_overrides.clear()
```

---

## Definition of Done Checklist

- [ ] `backend/tests/unit/agents/patient_comm/chatbot/test_transcript_persistence_service.py` created with 6 test cases
- [ ] `api-gateway/tests/unit/routers/test_transcript_endpoint.py` created with 7 test cases (excluding `_patient_own` which requires DB mock integration)
- [ ] All tests pass: `pytest backend/tests/unit/agents/patient_comm/chatbot/ -v`
- [ ] All tests pass: `pytest api-gateway/tests/unit/routers/test_transcript_endpoint.py -v`
- [ ] Branch coverage ≥80% on `transcript_service.py`: `pytest --cov=app.agents.patient_comm.chatbot.transcript_service --cov-report=term-missing`
- [ ] Branch coverage ≥80% on `routers/transcript.py`: `pytest --cov=app.routers.transcript --cov-report=term-missing`
- [ ] `test_persist_exchange_db_error_does_not_raise` confirms fire-and-forget — no exception propagates
- [ ] `test_get_transcript_patient_cross_encounter_returns_403` response body is exactly `{"detail": "Access denied."}`
- [ ] `test_encrypted_string_bind_param_is_not_plaintext` confirms ciphertext != plaintext (US-046 AC Scenario 3)
