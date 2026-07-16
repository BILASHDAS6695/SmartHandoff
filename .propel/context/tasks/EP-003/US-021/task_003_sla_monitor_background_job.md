---
id: TASK-003
title: "Implement `SLAMonitor` APScheduler Background Job — Breach Detection and `sla_breached` Flag Update"
user_story: US-021
epic: EP-003
sprint: 2
layer: Backend
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [TASK-001, TASK-002]
---

# TASK-003: Implement `SLAMonitor` APScheduler Background Job — Breach Detection and `sla_breached` Flag Update

> **Story:** US-021 | **Epic:** EP-003 | **Sprint:** 2 | **Layer:** Backend | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-021 Scenario 1 and DoD mandate:

> *"`SLAMonitor` background task runs every 5 minutes (APScheduler or asyncio `create_task`)"*
> *"`sla_breached` boolean flag updated on `AgentTask` record when threshold exceeded"*
> *"SLA monitor uses `READ` DB session (replica routing) to avoid write contention with agent tasks"*

This task implements `SLAMonitor` as an `APScheduler AsyncIOScheduler` job. The monitor:

1. Polls the DB read replica every 5 minutes for `AgentTask` records with `status IN ('IN_PROGRESS', 'PENDING')`.
2. Compares `NOW() - created_at` against the per-agent SLA threshold from `SLAConfig` (TASK-001).
3. For each breached task, sets `sla_breached = True` on the `AgentTask` record (write session).
4. Populates `sla_threshold_minutes` on first touch if not yet set.
5. Invokes `EscalationPublisher.publish()` (TASK-004) with idempotency enforcement.
6. Skips tasks with `status = COMPLETED` or `CANCELLED` — only active tasks are evaluated.

Design decisions:

| Decision | Rationale |
|----------|-----------|
| `APScheduler AsyncIOScheduler` | Integrates with FastAPI lifespan; avoids `time.sleep()` blocking (US-021 Technical Notes) |
| Read replica for polling | Avoids write contention on primary; SLA poll is read-heavy (TR-010, US-021 Technical Notes) |
| Write session for `sla_breached` update | Ensures breach flag is durably committed before escalation fires |
| Breach check is idempotent | Re-running on already-breached tasks is safe; `sla_breached` is a no-op if already `True` |

---

## Acceptance Criteria Addressed

| US-021 AC | Requirement |
|---|---|
| **Scenario 1** | Task in `IN_PROGRESS` for 30 minutes triggers `SUPERVISOR_ESCALATION` at the next 5-minute monitor tick |
| **Scenario 3** | Completed tasks (`status=COMPLETED`) are excluded from evaluation — only `IN_PROGRESS` and `PENDING` tasks evaluated |
| **Scenario 4** | `threshold_for(agent_type)` from `SLAConfig` (TASK-001) applied per task — `BED_MANAGEMENT` escalates after 15 minutes |
| **DoD** | Monitor runs every 5 minutes; `sla_breached` flag updated when threshold exceeded |

---

## Implementation Steps

### 1. Create `sla-monitor/app/monitor/sla_monitor.py`

```python
"""SLAMonitor — APScheduler background job for AgentTask SLA breach detection.

Runs every 5 minutes (configurable via sla_config.yaml: monitor_interval_seconds).
Evaluates only ACTIVE tasks (IN_PROGRESS, PENDING); skips COMPLETED / CANCELLED.

On breach:
  1. Sets AgentTask.sla_breached = True (write session).
  2. Populates AgentTask.sla_threshold_minutes if not already set.
  3. Delegates escalation to EscalationPublisher (app/publisher/escalation_publisher.py).

US-021: SLA Monitor must use READ DB session for poll query (replica routing, TR-010).
US-021 Technical Notes: avoid time.sleep(); use APScheduler AsyncIOScheduler.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.sla_loader import SLAConfig, load_sla_config
from app.db.session import get_read_session, get_write_session
from app.models.agent_task import AgentTask, AgentTaskStatus
from app.publisher.escalation_publisher import EscalationPublisher

logger = logging.getLogger(__name__)

# Statuses eligible for SLA evaluation (US-021 Scenario 3).
_ACTIVE_STATUSES: frozenset[str] = frozenset({"IN_PROGRESS", "PENDING"})


class SLAMonitor:
    """Scheduled SLA breach detector for AgentTask records.

    Usage (startup lifespan):
        monitor = SLAMonitor(publisher=EscalationPublisher(...))
        monitor.start()
        # on shutdown:
        monitor.shutdown()
    """

    def __init__(self, publisher: EscalationPublisher) -> None:
        self._publisher = publisher
        self._config: SLAConfig = load_sla_config()
        self._scheduler = AsyncIOScheduler(timezone="UTC")

    def start(self) -> None:
        """Register the monitor job and start the scheduler."""
        self._scheduler.add_job(
            self._run_check,
            trigger="interval",
            seconds=self._config.monitor_interval_seconds,
            id="sla_monitor",
            replace_existing=True,
            max_instances=1,  # prevent overlapping runs
        )
        self._scheduler.start()
        logger.info(
            "SLAMonitor started — polling every %d seconds",
            self._config.monitor_interval_seconds,
        )

    def shutdown(self) -> None:
        """Stop the scheduler gracefully."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("SLAMonitor stopped")

    async def _run_check(self) -> None:
        """Single monitor tick: detect and escalate SLA breaches.

        Uses READ session for poll query (TR-010 replica routing).
        Uses WRITE session for breach flag updates.
        """
        logger.debug("SLAMonitor tick — scanning for SLA breaches")
        now = datetime.now(tz=timezone.utc)

        async with get_read_session() as read_session:
            breached_tasks = await self._find_breached_tasks(read_session, now)

        if not breached_tasks:
            logger.debug("SLAMonitor tick — no breaches found")
            return

        logger.info("SLAMonitor tick — %d breach(es) detected", len(breached_tasks))

        async with get_write_session() as write_session:
            for task in breached_tasks:
                await self._handle_breach(write_session, task, now)
            await write_session.commit()

    async def _find_breached_tasks(
        self,
        session: AsyncSession,
        now: datetime,
    ) -> list[AgentTask]:
        """Query active tasks and return those that have exceeded their SLA.

        Applies the partial index ix_agent_task_active_status_created (TASK-002)
        by filtering on status IN ('IN_PROGRESS', 'PENDING').
        """
        stmt = (
            sa.select(AgentTask)
            .where(AgentTask.status.in_(_ACTIVE_STATUSES))
            .execution_options(populate_existing=True)
        )
        result = await session.execute(stmt)
        active_tasks: list[AgentTask] = list(result.scalars().all())

        breached: list[AgentTask] = []
        for task in active_tasks:
            threshold_minutes = self._config.threshold_for(task.agent_type)
            elapsed_minutes = (now - task.created_at.replace(tzinfo=timezone.utc)).total_seconds() / 60
            if elapsed_minutes >= threshold_minutes:
                breached.append(task)

        return breached

    async def _handle_breach(
        self,
        session: AsyncSession,
        task: AgentTask,
        now: datetime,
    ) -> None:
        """Update breach flag and fire escalation for a single breached task.

        Idempotent: if `sla_breached` is already True, skips the DB write.
        Escalation idempotency is enforced inside EscalationPublisher (TASK-004).
        """
        threshold_minutes = self._config.threshold_for(task.agent_type)
        elapsed_minutes = int(
            (now - task.created_at.replace(tzinfo=timezone.utc)).total_seconds() / 60
        )

        # Re-fetch the task in the WRITE session to avoid stale state.
        db_task: AgentTask | None = await session.get(AgentTask, task.id)
        if db_task is None:
            logger.warning("AgentTask %s not found in write session — skipping", task.id)
            return

        if not db_task.sla_breached:
            db_task.sla_breached = True
            db_task.sla_threshold_minutes = threshold_minutes
            session.add(db_task)
            logger.info(
                "SLA breach flagged: task_id=%s agent_type=%s elapsed=%d min threshold=%d min",
                db_task.id,
                db_task.agent_type,
                elapsed_minutes,
                threshold_minutes,
            )

        # Always attempt to publish escalation — EscalationPublisher deduplicates.
        await self._publisher.publish(
            encounter_id=db_task.encounter_id,
            agent_type=db_task.agent_type,
            minutes_elapsed=elapsed_minutes,
            supervisor_id=db_task.supervisor_id,  # resolved from encounter (TASK-004)
        )
```

### 2. Create `sla-monitor/app/db/session.py`

```python
"""SQLAlchemy async session factories for SLA monitor.

Provides separate read (replica) and write (primary) session context managers
per TR-010 (read replica routing) and US-021 Technical Notes.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.settings import settings

# Primary (write) engine
_write_engine = create_async_engine(
    settings.database_write_url,
    pool_size=10,
    max_overflow=5,
    echo=False,
)

# Read replica engine (TR-010)
_read_engine = create_async_engine(
    settings.database_read_url,
    pool_size=10,
    max_overflow=5,
    echo=False,
)

_WriteSession = async_sessionmaker(_write_engine, class_=AsyncSession, expire_on_commit=False)
_ReadSession = async_sessionmaker(_read_engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def get_write_session() -> AsyncIterator[AsyncSession]:
    """Async context manager yielding a write (primary) DB session."""
    async with _WriteSession() as session:
        yield session


@asynccontextmanager
async def get_read_session() -> AsyncIterator[AsyncSession]:
    """Async context manager yielding a read (replica) DB session (TR-010)."""
    async with _ReadSession() as session:
        yield session
```

### 3. Create `sla-monitor/app/main.py` (SLA Monitor Service Entry Point)

```python
"""SLA Monitor service entry point.

Starts the APScheduler SLAMonitor as a FastAPI lifespan background job.
Exposes /health and /ready probes for Cloud Run (TR-016).

US-021 DoD: SLAMonitor runs every 5 minutes via APScheduler AsyncIOScheduler.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.monitor.sla_monitor import SLAMonitor
from app.publisher.escalation_publisher import EscalationPublisher
from app.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    publisher = EscalationPublisher(
        project_id=settings.gcp_project_id,
        topic_id="notification-requests",
    )
    monitor = SLAMonitor(publisher=publisher)
    monitor.start()
    yield
    monitor.shutdown()


app = FastAPI(title="SLA Monitor", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    """Liveness probe (TR-016)."""
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict:
    """Readiness probe (TR-016)."""
    return {"status": "ready"}


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8080, log_level="info")
```

---

## Validation Checklist

- [ ] `APScheduler AsyncIOScheduler` used — no `time.sleep()` anywhere in this module
- [ ] Monitor interval driven by `SLAConfig.monitor_interval_seconds` (not hardcoded 300)
- [ ] Poll query filters `status IN ('IN_PROGRESS', 'PENDING')` only — `COMPLETED` tasks excluded
- [ ] `_find_breached_tasks` uses `get_read_session()` (replica)
- [ ] `_handle_breach` uses `get_write_session()` (primary)
- [ ] `sla_breached` flag only written when `db_task.sla_breached is False` (idempotent write)
- [ ] `sla_threshold_minutes` populated on first breach
- [ ] `max_instances=1` on scheduler job prevents overlapping monitor runs
- [ ] `/health` and `/ready` endpoints respond `200 OK`
- [ ] Service starts and shuts down cleanly via FastAPI lifespan

---

## Files Created

| Path | Purpose |
|---|---|
| `sla-monitor/app/monitor/sla_monitor.py` | `SLAMonitor` APScheduler job implementation |
| `sla-monitor/app/db/session.py` | Read/write async session factories |
| `sla-monitor/app/main.py` | FastAPI lifespan entry point with health probes |

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| `apscheduler>=3.10` | Runtime | `AsyncIOScheduler` |
| `sqlalchemy>=2.0` | Runtime | Async ORM |
| `fastapi>=0.110` | Runtime | Lifespan + probes |
| `uvicorn` | Runtime | ASGI server |
| TASK-001 | Task | `SLAConfig` and `load_sla_config` |
| TASK-002 | Task | `sla_breached` and `sla_threshold_minutes` columns on `AgentTask` |
| TASK-004 | Task | `EscalationPublisher` interface |
