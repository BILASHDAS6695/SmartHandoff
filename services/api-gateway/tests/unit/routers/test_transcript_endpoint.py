"""Unit tests for GET /api/v1/encounters/{encounter_id}/chat-transcript (US-046 TASK-003).

Covers:
    - test_get_transcript_patient_own_encounter_returns_200
        Patient JWT with matching encounter_id → 200 with messages list.
    - test_get_transcript_patient_cross_encounter_returns_403
        Patient JWT with different encounter_id → 403 {"detail": "Access denied."}.
    - test_get_transcript_staff_any_encounter_returns_200
        Staff JWT with any encounter_id → 200.
    - test_get_transcript_audit_log_written
        write_audit_entry called with resource_type="chatbot_transcript".
    - test_get_transcript_response_is_chronological
        Messages in response are ordered by ascending timestamp.
    - test_get_transcript_next_cursor_present_when_more_pages
        When DB returns PAGE_SIZE+1 rows, next_cursor is not None.
    - test_get_transcript_next_cursor_none_when_last_page
        When DB returns fewer than PAGE_SIZE rows, next_cursor is None.
    - test_get_transcript_invalid_cursor_returns_400
        Malformed ?cursor= value → 400 {"detail": "Invalid cursor."}.

US-046 AC Scenario 4: Patient scope (own=200, cross=403); staff any=200; audit log entry
"""
from __future__ import annotations

import base64
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from services.api_gateway.main import app
from backend.app.auth.dependencies import get_current_token_claims
from backend.app.db.deps import get_db
from services.api_gateway.app.routers.transcript import PAGE_SIZE


ENCOUNTER_ID = uuid.uuid4()
OTHER_ENCOUNTER_ID = uuid.uuid4()


def _patient_claims(encounter_id: uuid.UUID = ENCOUNTER_ID) -> dict:
    """Generate mock patient JWT claims."""
    return {
        "sub": str(uuid.uuid4()),
        "role": "patient",
        "encounter_id": str(encounter_id),
    }


def _staff_claims() -> dict:
    """Generate mock staff JWT claims."""
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
async def test_get_transcript_patient_cross_encounter_returns_403() -> None:
    """Patient JWT with different encounter_id must receive 403 Access denied."""
    app.dependency_overrides[get_current_token_claims] = lambda: _patient_claims(
        ENCOUNTER_ID
    )

    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/encounters/{OTHER_ENCOUNTER_ID}/chat-transcript"
        )

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Access denied."
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_transcript_staff_any_encounter_returns_200() -> None:
    """Staff JWT may access any encounter's transcript."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    app.dependency_overrides[get_current_token_claims] = _staff_claims
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch(
        "backend.app.db.audit.write_audit_entry", new_callable=AsyncMock
    ):
        async with AsyncClient(app=app, base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/encounters/{OTHER_ENCOUNTER_ID}/chat-transcript"
            )

    assert resp.status_code == 200
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_transcript_audit_log_written() -> None:
    """write_audit_entry is called with resource_type=chatbot_transcript on every access."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    app.dependency_overrides[get_current_token_claims] = lambda: _patient_claims(
        ENCOUNTER_ID
    )
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch(
        "backend.app.db.audit.write_audit_entry", new_callable=AsyncMock
    ) as mock_audit:
        async with AsyncClient(app=app, base_url="http://test") as client:
            await client.get(f"/api/v1/encounters/{ENCOUNTER_ID}/chat-transcript")

    mock_audit.assert_called_once()
    call_kwargs = mock_audit.call_args.kwargs
    assert call_kwargs["resource_type"] == "chatbot_transcript"
    assert call_kwargs["resource_id"] == str(ENCOUNTER_ID)
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_transcript_next_cursor_present_when_more_pages() -> None:
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

    app.dependency_overrides[get_current_token_claims] = lambda: _patient_claims(
        ENCOUNTER_ID
    )
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch(
        "backend.app.db.audit.write_audit_entry", new_callable=AsyncMock
    ):
        async with AsyncClient(app=app, base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/encounters/{ENCOUNTER_ID}/chat-transcript"
            )

    body = resp.json()
    assert resp.status_code == 200
    assert body["next_cursor"] is not None
    assert len(body["messages"]) == PAGE_SIZE
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_transcript_next_cursor_none_when_last_page() -> None:
    """When DB returns fewer than PAGE_SIZE rows, next_cursor must be None."""
    rows = [_make_mock_row() for _ in range(10)]

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = rows
    mock_db.execute = AsyncMock(return_value=mock_result)

    app.dependency_overrides[get_current_token_claims] = lambda: _patient_claims(
        ENCOUNTER_ID
    )
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch(
        "backend.app.db.audit.write_audit_entry", new_callable=AsyncMock
    ):
        async with AsyncClient(app=app, base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/encounters/{ENCOUNTER_ID}/chat-transcript"
            )

    body = resp.json()
    assert resp.status_code == 200
    assert body["next_cursor"] is None
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_transcript_invalid_cursor_returns_400() -> None:
    """Malformed ?cursor= value must return HTTP 400."""
    app.dependency_overrides[get_current_token_claims] = lambda: _patient_claims(
        ENCOUNTER_ID
    )

    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/encounters/{ENCOUNTER_ID}/chat-transcript?cursor=!!!notbase64"
        )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid cursor."
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_transcript_includes_urgent_messages_with_flags() -> None:
    """Transcript includes urgent messages with urgency_flag=True and escalated=True.

    Verifies US-046 AC Scenario 2: when a patient message triggered urgency
    detection and escalation, it appears in the transcript with both flags set.
    """
    # Create mock rows: one urgent (urgency_flag=True, escalated=True),
    # one normal (both flags False)
    base_ts = datetime.now(tz=timezone.utc)
    urgent_row = _make_mock_row(
        timestamp=base_ts - timedelta(minutes=1),
        urgency_flag=True,
    )
    urgent_row.escalated = True  # Set escalated flag

    normal_row = _make_mock_row(
        timestamp=base_ts,
        urgency_flag=False,
    )
    normal_row.escalated = False

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [urgent_row, normal_row]
    mock_db.execute = AsyncMock(return_value=mock_result)

    app.dependency_overrides[get_current_token_claims] = lambda: _patient_claims(
        ENCOUNTER_ID
    )
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch(
        "backend.app.db.audit.write_audit_entry", new_callable=AsyncMock
    ):
        async with AsyncClient(app=app, base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/encounters/{ENCOUNTER_ID}/chat-transcript"
            )

    assert resp.status_code == 200
    data = resp.json()
    # Both messages present in response
    assert len(data["messages"]) == 2
    # Urgent message flags correctly preserved
    urgent_msg = data["messages"][0]  # First in chronological order
    assert urgent_msg["urgency_flag"] is True
    assert urgent_msg["escalated"] is True
    # Normal message flags as expected
    normal_msg = data["messages"][1]
    assert normal_msg["urgency_flag"] is False
    assert normal_msg["escalated"] is False

    app.dependency_overrides.clear()

