---
id: TASK-003
title: "Create `base-agent/app/base/cancellation.py` — CancellationChecker with Redis Flag Query"
user_story: US-024
epic: EP-003
sprint: 2
layer: Backend
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [US-024/TASK-001]
---

# TASK-003: Create `base-agent/app/base/cancellation.py` — CancellationChecker with Redis Flag Query

> **Story:** US-024 | **Epic:** EP-003 | **Sprint:** 2 | **Layer:** Backend | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-024 mandates (Technical Notes, DoD):

> *"Cancellation check: `check_cancellation(encounter_id)` queries Redis flag (set by cancellation event handler)"*
> *"Cancellation flag stored in Redis key `cancellation:{encounter_id}` with TTL=3600s (set by EP-001 A11/A12/A13 handler)"*

`CancellationChecker` is a thin Redis client wrapper that `BaseAgent.check_cancellation()` calls before persisting agent output. It must:

1. Query Redis key `cancellation:{encounter_id}` using `aioredis` async client
2. Return `True` if the key exists (encounter is cancelled); `False` if absent
3. Handle Redis connection errors gracefully — treat as **non-cancelled** (fail-safe: avoid falsely stopping agent processing on Redis downtime)

Design decisions:

| Decision | Rationale |
|----------|-----------|
| `aioredis` async client | Agent containers use `asyncio`; blocking Redis call would stall the event loop |
| Return `False` on Redis connection error | Fail-safe: Redis unavailability must not silently cancel valid clinical tasks |
| Key pattern `cancellation:{encounter_id}` | Matches EP-001 A11/A12/A13 handler key format (US-015 dependency) |
| TTL=3600s not enforced here | TTL is set by the EP-001 handler at write time; checker is read-only |
| `CancellationChecker` as injectable class | Enables mock injection in unit tests without a live Redis instance |

Design refs: US-024 Technical Notes, US-015 (EP-001 cancellation handler), US-001 (Cloud Memorystore provisioning).

---

## Acceptance Criteria Addressed

| US-024 AC | Requirement |
|---|---|
| **Scenario 3** | `check_cancellation(encounter_id)` returns `True` → agent exits without DB persist → `AgentTask.status = CANCELLED` → ACK |

---

## Implementation Steps

### 1. Create `base-agent/app/base/cancellation.py`

```python
"""CancellationChecker — Redis-backed cancellation flag query.

Checks whether a cancellation flag has been set for a given encounter by
querying the Redis key ``cancellation:{encounter_id}``.

The flag is written by the EP-001 cancellation event handlers
(ADT^A11 / ADT^A12 / ADT^A13) via Cloud Memorystore (US-015, US-001).

Key format:
    ``cancellation:{encounter_id}``
    TTL: 3600 seconds (set at write time by EP-001 handler)

Fail-safe behaviour:
    Redis connection errors return ``False`` (not-cancelled) to avoid
    falsely stopping valid clinical agent processing on transient Redis
    downtime. The error is logged as WARNING for observability.

Design refs:
    US-024  — cancellation check before DB persist (AC Scenario 3)
    US-015  — EP-001 A11/A12/A13 sets the Redis flag
    US-001  — Cloud Memorystore (Redis) provisioned for cancellation flags
"""
from __future__ import annotations

import logging

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_CANCELLATION_KEY_PREFIX = "cancellation"


class CancellationChecker:
    """Queries Redis for encounter cancellation flags.

    Args:
        redis_client: An async ``redis.asyncio.Redis`` client instance.
            Injected at construction for testability.

    Example::

        import redis.asyncio as aioredis

        redis_client = aioredis.from_url("redis://localhost:6379")
        checker = CancellationChecker(redis_client=redis_client)
        is_cancelled = await checker.is_cancelled("enc-uuid-1234")
    """

    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client

    async def is_cancelled(self, encounter_id: str) -> bool:
        """Return ``True`` if a cancellation flag exists for ``encounter_id``.

        Queries the Redis key ``cancellation:{encounter_id}``. Returns
        ``False`` on Redis connection errors (fail-safe — see module docstring).

        Args:
            encounter_id: UUID string of the encounter to check.

        Returns:
            ``True`` if ``cancellation:{encounter_id}`` key exists in Redis;
            ``False`` if absent or on connection error.
        """
        key = f"{_CANCELLATION_KEY_PREFIX}:{encounter_id}"
        try:
            result = await self._redis.exists(key)
            is_cancelled: bool = bool(result)
            if is_cancelled:
                logger.info(
                    "cancellation_flag_detected",
                    extra={"encounter_id": encounter_id, "redis_key": key},
                )
            return is_cancelled

        except aioredis.RedisError as exc:
            # Fail-safe: treat Redis unavailability as not-cancelled
            logger.warning(
                "cancellation_check_redis_error",
                extra={
                    "encounter_id": encounter_id,
                    "error": str(exc),
                    "action": "treating_as_not_cancelled",
                },
            )
            return False
```

---

## Validation

Run from `base-agent/`:

```bash
# 1. Syntax check
python -c "
import ast, pathlib
ast.parse(pathlib.Path('app/base/cancellation.py').read_text())
print('Syntax check app/base/cancellation.py: PASSED')
"

# 2. is_cancelled returns True when Redis key exists
python -c "
import asyncio
from unittest.mock import AsyncMock, MagicMock
from app.base.cancellation import CancellationChecker

async def test_cancelled():
    mock_redis = AsyncMock()
    mock_redis.exists = AsyncMock(return_value=1)
    checker = CancellationChecker(redis_client=mock_redis)
    result = await checker.is_cancelled('enc-001')
    assert result is True, f'Expected True, got {result}'
    print('is_cancelled=True when key exists: PASSED')

asyncio.run(test_cancelled())
"

# 3. is_cancelled returns False when Redis key absent
python -c "
import asyncio
from unittest.mock import AsyncMock
from app.base.cancellation import CancellationChecker

async def test_not_cancelled():
    mock_redis = AsyncMock()
    mock_redis.exists = AsyncMock(return_value=0)
    checker = CancellationChecker(redis_client=mock_redis)
    result = await checker.is_cancelled('enc-002')
    assert result is False, f'Expected False, got {result}'
    print('is_cancelled=False when key absent: PASSED')

asyncio.run(test_not_cancelled())
"

# 4. Fail-safe: Redis error returns False (no exception raised)
python -c "
import asyncio
from unittest.mock import AsyncMock
import redis.asyncio as aioredis
from app.base.cancellation import CancellationChecker

async def test_redis_error():
    mock_redis = AsyncMock()
    mock_redis.exists = AsyncMock(side_effect=aioredis.RedisError('connection refused'))
    checker = CancellationChecker(redis_client=mock_redis)
    result = await checker.is_cancelled('enc-003')
    assert result is False, f'Expected False on Redis error, got {result}'
    print('Fail-safe on Redis error: PASSED')

asyncio.run(test_redis_error())
"
```

---

## Files Created / Modified

| Action | Path |
|--------|------|
| CREATE | `base-agent/app/base/cancellation.py` |

---

## Definition of Done Checklist

- [ ] `CancellationChecker` uses `redis.asyncio` (async Redis client)
- [ ] Key pattern: `cancellation:{encounter_id}` — matches EP-001 handler format
- [ ] `is_cancelled()` returns `True` when key exists, `False` when absent
- [ ] `RedisError` caught; returns `False` with `WARNING` log (fail-safe)
- [ ] No PHI in Redis key or log fields (only `encounter_id` UUID)
- [ ] `CancellationChecker` injectable (constructor accepts `redis_client`) — testable via mock
- [ ] Syntax check passes with `ast.parse`
