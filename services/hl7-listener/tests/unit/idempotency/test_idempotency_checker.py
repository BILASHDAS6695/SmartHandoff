"""Unit tests for app/idempotency/idempotency_checker.py.

DoD coverage:
  (b) Duplicate detection — is_duplicate() returns True for known MSH-10,
      emits duplicate_message_skipped log, uses parameterised SQL query.
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.idempotency.idempotency_checker import IdempotencyChecker


# ---------------------------------------------------------------------------
# Helper — build a mock AsyncSession
# ---------------------------------------------------------------------------

def _make_session(exists: bool) -> AsyncMock:
    """Build a mock AsyncSession whose execute() returns ``exists``."""
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = exists
    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result
    return mock_session


# ---------------------------------------------------------------------------
# Scenario 2: duplicate detection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestIdempotencyCheckerDuplicate:
    """Scenario 2: duplicate detection."""

    async def test_is_duplicate_returns_true_for_known_id(self):
        """Known source_message_id → is_duplicate() returns True (SC-2)."""
        checker = IdempotencyChecker()
        session = _make_session(exists=True)
        result = await checker.is_duplicate(session, "MSG-20260714-001")
        assert result is True

    async def test_is_duplicate_returns_false_for_new_id(self):
        """Unknown source_message_id → is_duplicate() returns False."""
        checker = IdempotencyChecker()
        session = _make_session(exists=False)
        result = await checker.is_duplicate(session, "MSG-NEW-999")
        assert result is False

    async def test_duplicate_emits_structured_log(self, caplog):
        """Duplicate detection emits duplicate_message_skipped structured log."""
        checker = IdempotencyChecker()
        session = _make_session(exists=True)
        with caplog.at_level(logging.INFO):
            await checker.is_duplicate(session, "MSG-DUP-001")
        assert "duplicate_message_skipped" in caplog.text

    async def test_non_duplicate_does_not_emit_duplicate_log(self, caplog):
        """New message — no duplicate_message_skipped log entry."""
        checker = IdempotencyChecker()
        session = _make_session(exists=False)
        with caplog.at_level(logging.INFO):
            await checker.is_duplicate(session, "MSG-NEW-001")
        assert "duplicate_message_skipped" not in caplog.text

    async def test_uses_parameterised_query_not_string_interpolation(self):
        """execute() must be called with a bindparam dict — prevents SQL injection."""
        checker = IdempotencyChecker()
        session = _make_session(exists=False)
        await checker.is_duplicate(session, "MSG-PARAM-TEST")
        # Verify execute was called with two positional args (stmt, params dict)
        call_args = session.execute.call_args
        assert len(call_args.args) >= 2, "Expected (stmt, params) positional args"
        params = call_args.args[1]
        assert isinstance(params, dict)
        assert "msg_id" in params
        assert params["msg_id"] == "MSG-PARAM-TEST"

    async def test_session_execute_is_called_once(self):
        """Only one DB query should be made per is_duplicate() call."""
        checker = IdempotencyChecker()
        session = _make_session(exists=False)
        await checker.is_duplicate(session, "MSG-001")
        session.execute.assert_awaited_once()

    async def test_checker_is_stateless_across_calls(self):
        """IdempotencyChecker instance can be reused — no mutable state per call."""
        checker = IdempotencyChecker()
        session_dup = _make_session(exists=True)
        session_new = _make_session(exists=False)
        assert await checker.is_duplicate(session_dup, "MSG-OLD") is True
        assert await checker.is_duplicate(session_new, "MSG-NEW") is False

    async def test_select_exists_query_used(self):
        """The SQL statement must use SELECT EXISTS for O(log n) performance."""
        checker = IdempotencyChecker()
        session = _make_session(exists=False)
        await checker.is_duplicate(session, "MSG-001")
        call_args = session.execute.call_args
        stmt = call_args.args[0]
        # The compiled text should reference EXISTS
        stmt_text = str(stmt).upper()
        assert "EXISTS" in stmt_text
        assert "ADT_EVENT" in stmt_text
        assert "SOURCE_MESSAGE_ID" in stmt_text
