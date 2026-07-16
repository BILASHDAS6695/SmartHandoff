---
id: TASK-005
title: "Create `base-agent/tests/test_base_agent.py` — Unit Tests for All 4 AC Scenarios"
user_story: US-024
epic: EP-003
sprint: 2
layer: Backend — Tests
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [US-024/TASK-001, US-024/TASK-002, US-024/TASK-003, US-024/TASK-004]
---

# TASK-005: Create `base-agent/tests/test_base_agent.py` — Unit Tests for All 4 AC Scenarios

> **Story:** US-024 | **Epic:** EP-003 | **Sprint:** 2 | **Layer:** Backend — Tests | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-024 mandates (DoD):

> *"Unit tests: (a) success path, (b) retry on transient error, (c) cancellation check, (d) non-retryable failure"*

This task creates pytest unit tests covering all 4 acceptance criteria scenarios. Tests must be **fully isolated** — no live Redis, Pub/Sub, or Vertex AI connections. All external dependencies are mocked via `unittest.mock` or `pytest-asyncio` fixtures.

Test coverage targets:

| Test | US-024 AC | Description |
|------|-----------|-------------|
| `test_success_path` | Scenario 1 | ACK sent; `AgentTask.status = COMPLETED` |
| `test_retry_on_retryable_error` | Scenario 2 | NACK sent; `retry_count` incremented; backoff applied |
| `test_cancellation_flag_exits_cleanly` | Scenario 3 | No DB persist; `CANCELLED` status; ACK sent |
| `test_nonretryable_failure_sets_failed_status` | Scenario 4 | `FAILED` status with error JSON; ACK sent |
| `test_retry_decorator_exhaustion` | Scenario 2 | After 4 total attempts `RetryableError` is raised |
| `test_retry_decorator_nonretryable_immediate` | Scenario 4 | `NonRetryableError` propagates on first attempt |
| `test_cancellation_checker_redis_fail_safe` | Scenario 3 | Redis error → returns `False` (not cancelled) |
| `test_structured_output_rate_limit_retryable` | Scenario 4 | HTTP 429 → `RetryableError` |

Design decisions:

| Decision | Rationale |
|----------|-----------|
| `pytest-asyncio` with `asyncio_mode=auto` | All agent methods are async; avoids boilerplate `asyncio.run()` in each test |
| `MagicMock` / `AsyncMock` for all I/O | Eliminates flaky test dependencies on live GCP services |
| Concrete `ConcreteAgent` test subclass | Allows instantiation of the abstract `BaseAgent` without a full specialist implementation |
| `freezegun` not needed | Backoff delays are patched via `asyncio.sleep` mock — no real time passes in tests |

Design refs: US-024 DoD, AC Scenarios 1–4.

---

## Acceptance Criteria Addressed

| US-024 AC | Requirement |
|---|---|
| **Scenario 1** | `test_success_path` — ACK + `COMPLETED` |
| **Scenario 2** | `test_retry_on_retryable_error`, `test_retry_decorator_exhaustion` |
| **Scenario 3** | `test_cancellation_flag_exits_cleanly`, `test_cancellation_checker_redis_fail_safe` |
| **Scenario 4** | `test_nonretryable_failure_sets_failed_status`, `test_retry_decorator_nonretryable_immediate`, `test_structured_output_rate_limit_retryable` |

---

## Implementation Steps

### 1. Scaffold test directory

```bash
mkdir -p base-agent/tests
touch base-agent/tests/__init__.py
```

### 2. Create `base-agent/tests/conftest.py`

```python
"""Shared pytest fixtures for base-agent unit tests."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.base.agent import AgentTaskStatus, BaseAgent, BaseAgentOutput
from app.base.cancellation import CancellationChecker
from app.models.adt_event import ADTEvent


# ---------------------------------------------------------------------------
# Concrete agent for testing the abstract BaseAgent
# ---------------------------------------------------------------------------


class ConcreteAgent(BaseAgent):
    """Minimal concrete subclass of BaseAgent for unit testing."""

    def __init__(self, *args, process_side_effect=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._process_side_effect = process_side_effect

    async def process(self, event: ADTEvent) -> BaseAgentOutput:
        if self._process_side_effect is not None:
            raise self._process_side_effect
        return BaseAgentOutput()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db_session():
    """Async SQLAlchemy session factory mock."""
    session_mock = AsyncMock()
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=False)
    session_mock.begin = MagicMock(return_value=session_mock)
    session_mock.execute = AsyncMock()

    factory = MagicMock(return_value=session_mock)
    return factory


@pytest.fixture
def mock_cancellation_checker():
    """CancellationChecker mock (not cancelled by default)."""
    checker = AsyncMock(spec=CancellationChecker)
    checker.is_cancelled = AsyncMock(return_value=False)
    return checker


@pytest.fixture
def mock_subscriber():
    """google.cloud.pubsub_v1.SubscriberClient mock."""
    subscriber = MagicMock()
    subscriber.acknowledge = MagicMock()
    subscriber.modify_ack_deadline = MagicMock()
    return subscriber


@pytest.fixture
def sample_adt_event() -> ADTEvent:
    """Minimal ADTEvent fixture."""
    return ADTEvent(
        encounter_id="enc-test-0001",
        event_type="ADT^A01",
        patient_id="pat-0001",
        unit="ICU-3",
        timestamp="2026-07-16T08:00:00Z",
    )


@pytest.fixture
def make_received_message(sample_adt_event):
    """Factory for mock Pub/Sub ReceivedMessage."""

    def _make(task_id: str = "task-uuid-001"):
        msg = MagicMock()
        msg.ack_id = "ack-id-test-001"
        msg.message.data = sample_adt_event.model_dump_json().encode()
        msg.message.attributes = {"task_id": task_id}
        return msg

    return _make
```

### 3. Create `base-agent/tests/test_base_agent.py`

```python
"""Unit tests for BaseAgent, retry_with_backoff, CancellationChecker, and StructuredOutputHelper.

Covers all 4 acceptance criteria scenarios from US-024:
  (a) Success path — ACK + COMPLETED
  (b) Retry on RetryableError — NACK + retry_count increment
  (c) Cancellation check — CANCELLED + ACK (no DB persist)
  (d) Non-retryable failure — FAILED + error JSON

Design refs: US-024 DoD, AC Scenarios 1–4.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import redis.asyncio as aioredis
from pydantic import BaseModel

from app.base.agent import AgentTaskStatus, BaseAgentOutput
from app.base.cancellation import CancellationChecker
from app.base.errors import NonRetryableError, RetryableError, retry_with_backoff
from app.base.structured_output import StructuredOutputHelper
from tests.conftest import ConcreteAgent


# ===========================================================================
# Helpers
# ===========================================================================


def make_agent(
    mock_db_session,
    mock_cancellation_checker,
    process_side_effect=None,
) -> ConcreteAgent:
    return ConcreteAgent(
        subscription_path="projects/test/subscriptions/test-sub",
        db_session=mock_db_session,
        cancellation_checker=mock_cancellation_checker,
        process_side_effect=process_side_effect,
    )


# ===========================================================================
# (a) Scenario 1: Success path
# ===========================================================================


@pytest.mark.asyncio
async def test_success_path(
    mock_db_session,
    mock_cancellation_checker,
    mock_subscriber,
    make_received_message,
):
    """ACK is sent and AgentTask status is set to COMPLETED on success."""
    agent = make_agent(mock_db_session, mock_cancellation_checker)
    msg = make_received_message(task_id="task-001")

    await agent._handle_message(mock_subscriber, msg)

    # ACK must be called once
    mock_subscriber.acknowledge.assert_called_once()

    # NACK must NOT be called
    mock_subscriber.modify_ack_deadline.assert_not_called()

    # update_task_status called with COMPLETED (second call; first is IN_PROGRESS)
    calls = mock_db_session().execute.call_args_list
    # Verify at least 2 status updates: IN_PROGRESS then COMPLETED
    assert mock_db_session().execute.call_count >= 2


# ===========================================================================
# (b) Scenario 2: Retry on RetryableError
# ===========================================================================


@pytest.mark.asyncio
async def test_retry_on_retryable_error(
    mock_db_session,
    mock_cancellation_checker,
    mock_subscriber,
    make_received_message,
):
    """NACK is sent and retry_count is incremented when RetryableError is raised."""
    agent = make_agent(
        mock_db_session,
        mock_cancellation_checker,
        process_side_effect=RetryableError("DB timeout", error_detail={"host": "sql-proxy"}),
    )
    msg = make_received_message(task_id="task-002")

    await agent._handle_message(mock_subscriber, msg)

    # NACK must be called
    mock_subscriber.modify_ack_deadline.assert_called_once_with(
        request={
            "subscription": agent._subscription_path,
            "ack_ids": [msg.ack_id],
            "ack_deadline_seconds": 0,
        }
    )

    # ACK must NOT be called
    mock_subscriber.acknowledge.assert_not_called()


@pytest.mark.asyncio
async def test_retry_decorator_exhaustion():
    """retry_with_backoff raises RetryableError after 4 total attempts (1 + 3 retries)."""
    call_count = 0

    @retry_with_backoff
    async def always_retryable():
        nonlocal call_count
        call_count += 1
        raise RetryableError("transient")

    with patch("app.base.errors.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(RetryableError):
            await always_retryable()

    assert call_count == 4, f"Expected 4 total attempts, got {call_count}"


# ===========================================================================
# (c) Scenario 3: Cancellation check
# ===========================================================================


@pytest.mark.asyncio
async def test_cancellation_flag_exits_cleanly(
    mock_db_session,
    mock_cancellation_checker,
    mock_subscriber,
    make_received_message,
):
    """Agent exits without calling process(); AgentTask = CANCELLED; ACK sent."""
    mock_cancellation_checker.is_cancelled = AsyncMock(return_value=True)

    agent = make_agent(mock_db_session, mock_cancellation_checker)
    msg = make_received_message(task_id="task-003")

    # Track whether process() was called by patching it
    process_called = False
    original_process = agent.process

    async def spy_process(*args, **kwargs):
        nonlocal process_called
        process_called = True
        return await original_process(*args, **kwargs)

    agent.process = spy_process

    await agent._handle_message(mock_subscriber, msg)

    # process() must NOT have been called
    assert not process_called, "process() must not be called when encounter is cancelled"

    # ACK must be sent (to prevent DLQ accumulation)
    mock_subscriber.acknowledge.assert_called_once()

    # NACK must NOT be called
    mock_subscriber.modify_ack_deadline.assert_not_called()


@pytest.mark.asyncio
async def test_cancellation_checker_redis_fail_safe():
    """CancellationChecker returns False (not cancelled) on Redis connection error."""
    mock_redis = AsyncMock()
    mock_redis.exists = AsyncMock(side_effect=aioredis.RedisError("connection refused"))

    checker = CancellationChecker(redis_client=mock_redis)
    result = await checker.is_cancelled("enc-fail-safe-001")

    assert result is False, "Redis failure should return False (not-cancelled)"


# ===========================================================================
# (d) Scenario 4: Non-retryable failure
# ===========================================================================


@pytest.mark.asyncio
async def test_nonretryable_failure_sets_failed_status(
    mock_db_session,
    mock_cancellation_checker,
    mock_subscriber,
    make_received_message,
):
    """AgentTask.status = FAILED with error JSON; ACK sent on NonRetryableError."""
    agent = make_agent(
        mock_db_session,
        mock_cancellation_checker,
        process_side_effect=NonRetryableError(
            "Schema validation failed",
            error_detail={"field": "encounter_id", "value": None},
        ),
    )
    msg = make_received_message(task_id="task-004")

    await agent._handle_message(mock_subscriber, msg)

    # ACK must be sent (non-retryable — Pub/Sub delivery counter manages DLQ)
    mock_subscriber.acknowledge.assert_called_once()

    # NACK must NOT be called
    mock_subscriber.modify_ack_deadline.assert_not_called()


@pytest.mark.asyncio
async def test_retry_decorator_nonretryable_immediate():
    """NonRetryableError propagates on first attempt — no retry."""
    call_count = 0

    @retry_with_backoff
    async def always_nonretryable():
        nonlocal call_count
        call_count += 1
        raise NonRetryableError("permanent")

    with pytest.raises(NonRetryableError):
        await always_nonretryable()

    assert call_count == 1, f"Expected 1 attempt, got {call_count}"


# ===========================================================================
# StructuredOutputHelper
# ===========================================================================


@pytest.mark.asyncio
async def test_structured_output_rate_limit_retryable():
    """HTTP 429 from Vertex AI raises RetryableError."""
    mock_response = MagicMock()
    mock_response.status_code = 429

    class SimpleOutput(BaseModel):
        content: str

    helper = StructuredOutputHelper()

    with patch("app.base.structured_output.ChatVertexAI") as MockLLM:
        mock_chain = AsyncMock()
        mock_chain.ainvoke = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "rate limit", request=MagicMock(), response=mock_response
            )
        )
        MockLLM.return_value.with_structured_output.return_value = mock_chain

        with pytest.raises(RetryableError) as exc_info:
            await helper.invoke_structured("test prompt", SimpleOutput)

    assert "429" in str(exc_info.value)


@pytest.mark.asyncio
async def test_structured_output_success():
    """invoke_structured returns validated Pydantic instance on success."""

    class SimpleOutput(BaseModel):
        content: str

    expected = SimpleOutput(content="discharge summary")
    helper = StructuredOutputHelper()

    with patch("app.base.structured_output.ChatVertexAI") as MockLLM:
        mock_chain = AsyncMock()
        mock_chain.ainvoke = AsyncMock(return_value=expected)
        MockLLM.return_value.with_structured_output.return_value = mock_chain

        result = await helper.invoke_structured("test prompt", SimpleOutput)

    assert result == expected
    assert isinstance(result, SimpleOutput)
```

---

## Validation

Run from `base-agent/`:

```bash
# Install test dependencies
pip install pytest pytest-asyncio httpx

# Run all unit tests
pytest tests/test_base_agent.py -v

# Expected output — all 8 tests PASSED:
# test_success_path PASSED
# test_retry_on_retryable_error PASSED
# test_retry_decorator_exhaustion PASSED
# test_cancellation_flag_exits_cleanly PASSED
# test_cancellation_checker_redis_fail_safe PASSED
# test_nonretryable_failure_sets_failed_status PASSED
# test_retry_decorator_nonretryable_immediate PASSED
# test_structured_output_rate_limit_retryable PASSED
# test_structured_output_success PASSED

# Verify test coverage
pytest tests/test_base_agent.py --tb=short -q
```

---

## Files Created / Modified

| Action | Path |
|--------|------|
| CREATE | `base-agent/tests/__init__.py` |
| CREATE | `base-agent/tests/conftest.py` |
| CREATE | `base-agent/tests/test_base_agent.py` |

---

## Definition of Done Checklist

- [ ] `test_success_path` — ACK called once; `NACK` not called; `update_task_status` called with `COMPLETED`
- [ ] `test_retry_on_retryable_error` — NACK called; ACK not called; `retry_count` increment triggered
- [ ] `test_retry_decorator_exhaustion` — exactly 4 total calls; `RetryableError` raised
- [ ] `test_cancellation_flag_exits_cleanly` — `process()` not called; ACK sent; status = `CANCELLED`
- [ ] `test_cancellation_checker_redis_fail_safe` — Redis error returns `False`
- [ ] `test_nonretryable_failure_sets_failed_status` — ACK sent; status = `FAILED`
- [ ] `test_retry_decorator_nonretryable_immediate` — exactly 1 call; `NonRetryableError` propagated
- [ ] `test_structured_output_rate_limit_retryable` — HTTP 429 raises `RetryableError`
- [ ] `test_structured_output_success` — returns validated Pydantic instance
- [ ] All tests pass with `pytest -v`; no live external dependencies
- [ ] `asyncio.sleep` patched in backoff tests — no real wait time
