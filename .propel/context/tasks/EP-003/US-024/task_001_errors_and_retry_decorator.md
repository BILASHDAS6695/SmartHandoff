---
id: TASK-001
title: "Create `base-agent/app/base/errors.py` — RetryableError, NonRetryableError, and retry_with_backoff Decorator"
user_story: US-024
epic: EP-003
sprint: 2
layer: Backend
estimate: 1.5h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: []
---

# TASK-001: Create `base-agent/app/base/errors.py` — RetryableError, NonRetryableError, and retry_with_backoff Decorator

> **Story:** US-024 | **Epic:** EP-003 | **Sprint:** 2 | **Layer:** Backend | **Est:** 1.5 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-024 mandates (TR-015, DoD):

> *"Retry decorator: 3 attempts, exponential backoff (1s, 2s, 4s) for `RetryableError` subclass"*
> *"Non-retryable errors: propagate without retry; task status set to `FAILED` with error JSON"*

This task creates the error hierarchy and retry decorator that all specialist agents inherit via `BaseAgent`. The decorator must:

1. Catch only `RetryableError` (and its subclasses) to trigger retry
2. Apply exponential backoff delays: 1 s, 2 s, 4 s
3. Propagate `NonRetryableError` immediately without retry
4. Raise the last `RetryableError` when all attempts are exhausted (so the base agent can set `FAILED`)

Design decisions:

| Decision | Rationale |
|----------|-----------|
| `RetryableError` and `NonRetryableError` as distinct hierarchies | Keeps retry logic exhaustive — unknown errors propagate as `NonRetryableError` (fail-fast) |
| Exponential backoff via `asyncio.sleep` | Agent containers are async Cloud Run services; blocking `time.sleep` would stall the event loop |
| Decorator uses `functools.wraps` | Preserves function metadata for stack traces and test introspection |
| Max attempts = 3 (delays 1 s, 2 s, 4 s) | Matches US-024 DoD; total retry window ≤7 s, within 30 s agent timeout (TR-004) |
| `error_detail` dict attached to exception | `BaseAgent` serialises this to JSON for `AgentTask.error_details` field |

Design refs: TR-015, US-024 DoD, AC Scenarios 2 and 4.

---

## Acceptance Criteria Addressed

| US-024 AC | Requirement |
|---|---|
| **Scenario 2** | `RetryableError` triggers retry with exponential backoff; attempts capped at 3 |
| **Scenario 4** | `NonRetryableError` propagates immediately; message delivered to DLQ after 5 Pub/Sub delivery attempts |

---

## Implementation Steps

### 1. Scaffold directory structure

```
base-agent/
├── app/
│   └── base/
│       ├── __init__.py
│       └── errors.py      ← THIS TASK
```

```bash
mkdir -p base-agent/app/base
touch base-agent/app/base/__init__.py
```

### 2. Create `base-agent/app/base/errors.py`

```python
"""Error hierarchy and retry decorator for SmartHandoff base agent.

All specialist agents inherit these via ``BaseAgent``. The retry decorator
applies exponential backoff only for ``RetryableError`` subclasses; all
other exceptions propagate immediately.

Backoff schedule (US-024 DoD):
    Attempt 1 → wait 1 s → Attempt 2 → wait 2 s → Attempt 3 → raise

Design refs:
    TR-015  — DLQ: Pub/Sub max_delivery_attempts=5; non-retryable propagates so
              Pub/Sub counts the delivery and eventually routes to DLQ
    US-024  — retry decorator 3 attempts; exponential backoff 1s/2s/4s
"""
from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

_F = TypeVar("_F", bound=Callable[..., Any])

# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


class AgentError(Exception):
    """Base class for all SmartHandoff agent errors.

    Args:
        message: Human-readable error description.
        error_detail: Optional structured dict serialised to
            ``AgentTask.error_details`` in the DB.
    """

    def __init__(self, message: str, error_detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_detail: dict[str, Any] = error_detail or {}


class RetryableError(AgentError):
    """Transient error that should be retried with exponential backoff.

    Raise for conditions that are expected to self-resolve:
    - Database connection timeouts
    - Pub/Sub transient delivery failures
    - Vertex AI rate-limit (429) responses
    - Network I/O errors

    Example::

        raise RetryableError(
            "DB connection timeout",
            error_detail={"db_host": "cloud-sql-proxy", "attempt": 1},
        )
    """


class NonRetryableError(AgentError):
    """Permanent error that must NOT be retried.

    Raise for conditions that cannot be resolved by retrying:
    - Schema validation failures (malformed Pub/Sub payload)
    - Business rule violations (encounter not found in FHIR)
    - Pydantic structured-output schema mismatch

    Example::

        raise NonRetryableError(
            "ADTEvent schema validation failed",
            error_detail={"field": "encounter_id", "value": None},
        )
    """


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------

_BACKOFF_DELAYS: tuple[float, ...] = (1.0, 2.0, 4.0)
"""Exponential backoff delays in seconds for each retry attempt (US-024 DoD)."""

MAX_ATTEMPTS: int = len(_BACKOFF_DELAYS) + 1
"""Total attempts = initial attempt + len(BACKOFF_DELAYS) = 4 total tries."""


def retry_with_backoff(func: _F) -> _F:
    """Async decorator that retries ``RetryableError`` with exponential backoff.

    Wraps an ``async`` coroutine function. On ``RetryableError``, waits the
    scheduled backoff delay then retries up to ``MAX_ATTEMPTS`` total. On
    ``NonRetryableError`` or any other exception, propagates immediately.

    Args:
        func: An ``async`` coroutine function to wrap.

    Returns:
        Wrapped coroutine with retry logic.

    Raises:
        RetryableError: When all ``MAX_ATTEMPTS`` are exhausted.
        NonRetryableError: Immediately, without retry.
        Exception: Any other exception, immediately, without retry.

    Example::

        class MyAgent(BaseAgent):
            @retry_with_backoff
            async def process(self, event: ADTEvent) -> BaseAgentOutput:
                ...
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        last_exc: RetryableError | None = None

        for attempt, delay in enumerate(
            [0.0] + list(_BACKOFF_DELAYS), start=1
        ):
            if delay > 0:
                logger.warning(
                    "agent_retry_backoff",
                    extra={
                        "attempt": attempt,
                        "delay_seconds": delay,
                        "function": func.__qualname__,
                    },
                )
                await asyncio.sleep(delay)

            try:
                return await func(*args, **kwargs)

            except NonRetryableError:
                # Propagate immediately — no retry
                raise

            except RetryableError as exc:
                last_exc = exc
                logger.warning(
                    "agent_retryable_error",
                    extra={
                        "attempt": attempt,
                        "max_attempts": MAX_ATTEMPTS,
                        "error": str(exc),
                        "error_detail": exc.error_detail,
                        "function": func.__qualname__,
                    },
                )
                if attempt >= MAX_ATTEMPTS:
                    break  # exhausted — raise below

            except Exception:
                # Unknown error — treat as non-retryable; propagate immediately
                raise

        # All attempts exhausted
        raise last_exc  # type: ignore[misc]

    return wrapper  # type: ignore[return-value]
```

---

## Validation

Run from `base-agent/`:

```bash
# 1. Syntax check
python -c "
import ast, pathlib
ast.parse(pathlib.Path('app/base/errors.py').read_text())
print('Syntax check app/base/errors.py: PASSED')
"

# 2. RetryableError is a subclass of AgentError
python -c "
from app.base.errors import RetryableError, NonRetryableError, AgentError
assert issubclass(RetryableError, AgentError), 'RetryableError must extend AgentError'
assert issubclass(NonRetryableError, AgentError), 'NonRetryableError must extend AgentError'
print('Error hierarchy: PASSED')
"

# 3. retry_with_backoff retries exactly 3 times on RetryableError then raises
python -c "
import asyncio
from app.base.errors import RetryableError, retry_with_backoff

call_count = 0

@retry_with_backoff
async def always_fails():
    global call_count
    call_count += 1
    raise RetryableError('transient', error_detail={'attempt': call_count})

async def run():
    global call_count
    try:
        await always_fails()
    except RetryableError:
        pass
    assert call_count == 4, f'Expected 4 total attempts, got {call_count}'
    print(f'Retry count (4 total attempts including initial): PASSED')

asyncio.run(run())
"

# 4. NonRetryableError propagates on first attempt (no retry)
python -c "
import asyncio
from app.base.errors import NonRetryableError, retry_with_backoff

call_count = 0

@retry_with_backoff
async def immediate_fail():
    global call_count
    call_count += 1
    raise NonRetryableError('permanent')

async def run():
    global call_count
    try:
        await immediate_fail()
    except NonRetryableError:
        pass
    assert call_count == 1, f'Expected 1 attempt, got {call_count}'
    print('NonRetryableError no retry: PASSED')

asyncio.run(run())
"
```

---

## Files Created / Modified

| Action | Path |
|--------|------|
| CREATE | `base-agent/app/base/__init__.py` |
| CREATE | `base-agent/app/base/errors.py` |

---

## Definition of Done Checklist

- [ ] `RetryableError` and `NonRetryableError` both extend `AgentError`
- [ ] `retry_with_backoff` decorator: exactly 4 total attempts (1 initial + 3 retries)
- [ ] Backoff delays: 1 s, 2 s, 4 s between attempts (via `asyncio.sleep`)
- [ ] `NonRetryableError` propagates on first attempt — no retry
- [ ] Unknown exceptions propagate immediately — no retry
- [ ] `error_detail` dict accessible on all `AgentError` subclasses
- [ ] No PHI in structured log fields (only function name, attempt count, error message)
- [ ] Syntax check passes with `ast.parse`
