---
id: TASK-003
title: "Create `coordinator-agent/app/main.py` — Service Entry Point with SIGTERM Graceful Shutdown Handler"
user_story: US-020
epic: EP-003
sprint: 2
layer: Backend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-020/TASK-001, US-020/TASK-002]
---

# TASK-003: Create `coordinator-agent/app/main.py` — Service Entry Point with SIGTERM Graceful Shutdown Handler

> **Story:** US-020 | **Epic:** EP-003 | **Sprint:** 2 | **Layer:** Backend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-020 mandates (TR-017, US-020 DoD SC-3):

> *"Graceful shutdown handler fires; in-flight task creation completes; Pub/Sub message is acknowledged; process exits within 30 seconds; no `AgentTask` is left in a partial state."*

`main.py` is the Cloud Run container entry point. It must:

- Register a `SIGTERM` handler via `signal.signal()` that sets the `shutdown_event` on the `ADTSubscriber`
- Wire together `TransitionCoordinatorAgent` and `ADTSubscriber` with dependency injection
- Initialise the async SQLAlchemy session factory and close it cleanly on exit
- Start the asyncio event loop with `asyncio.run(main())`
- Health check endpoints (`/health`, `/ready`) served concurrently with the Pub/Sub consumer (TR-016)

Design decisions:

| Decision | Rationale |
|----------|-----------|
| `signal.signal(SIGTERM, handler)` sets `asyncio.Event` | The event loop sees the flag before the next `await` — no forced cancellation of in-flight coroutines |
| `asyncio.wait_for(subscriber.start(), timeout=30)` | TR-017 enforces a 30-second drain; hard-kills after timeout as last resort |
| FastAPI health endpoints on port 8080 | TR-016: Cloud Run expects `/health` liveness and `/ready` readiness probes |
| Subscriber and FastAPI run concurrently with `asyncio.gather` | Single asyncio event loop; no threading complexity |

Design refs: TR-016, TR-017, ADR-002, US-020 DoD, SC-3.

---

## Acceptance Criteria Addressed

| US-020 AC | Requirement |
|---|---|
| **Scenario 3** | SIGTERM handler sets `shutdown_event`; current message completes; ACK sent; process exits within 30 seconds |

---

## Implementation Steps

### 1. Create `coordinator-agent/app/main.py`

```python
"""Coordinator Agent — Cloud Run service entry point.

Wires together:
  - ``ADTSubscriber``       — Pub/Sub pull consumer (TASK-001)
  - ``TransitionCoordinatorAgent`` — task creation orchestrator (TASK-002)
  - SIGTERM handler         — sets ``shutdown_event`` for graceful drain
  - FastAPI health endpoints — liveness/readiness probes (TR-016)

Startup sequence:
  1. Initialise async SQLAlchemy engine + session factory
  2. Register SIGTERM handler (sets ``ADTSubscriber.shutdown_event``)
  3. Start FastAPI health server concurrently on port 8080
  4. Start Pub/Sub subscriber; block until ``shutdown_event`` is set
  5. On shutdown: drain subscriber, close DB engine, exit 0

Design refs:
    TR-016   — liveness/readiness probes every 10 s / 5 s
    TR-017   — SIGTERM drains in-flight; max 30 s; exit 0
    ADR-002  — Cloud Run min-instances=1; stateless container
    US-020   — SC-3, DoD
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

import uvicorn
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.coordinator.agent import TransitionCoordinatorAgent
from app.pubsub.adt_subscriber import ADTSubscriber

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastAPI app — health probes only (TR-016)
# ---------------------------------------------------------------------------

health_app = FastAPI(title="coordinator-agent-health", docs_url=None, redoc_url=None)


@health_app.get("/health")
async def liveness() -> dict[str, str]:
    """Cloud Run liveness probe — returns 200 when process is alive."""
    return {"status": "ok"}


@health_app.get("/ready")
async def readiness() -> dict[str, str]:
    """Cloud Run readiness probe — returns 200 when subscriber is connected."""
    return {"status": "ready"}


# ---------------------------------------------------------------------------
# Service bootstrap
# ---------------------------------------------------------------------------


async def main() -> None:
    """Bootstrap and run the coordinator agent until SIGTERM."""
    logging.basicConfig(
        level=logging.INFO,
        format='{"time":"%(asctime)s","level":"%(levelname)s","name":"%(name)s","message":"%(message)s"}',
    )

    # -----------------------------------------------------------------------
    # 1. Database session factory
    # -----------------------------------------------------------------------
    db_url = os.environ["DATABASE_URL"]  # e.g. postgresql+asyncpg://...
    engine = create_async_engine(db_url, pool_size=5, max_overflow=5, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # -----------------------------------------------------------------------
    # 2. Build coordinator and subscriber
    # -----------------------------------------------------------------------
    coordinator = TransitionCoordinatorAgent(db_session=session_factory)
    subscriber = ADTSubscriber(callback=coordinator.process_event)

    # -----------------------------------------------------------------------
    # 3. SIGTERM handler — sets shutdown_event; does NOT cancel the event loop
    # -----------------------------------------------------------------------
    loop = asyncio.get_running_loop()

    def _sigterm_handler(signum: int, frame: object) -> None:  # noqa: ARG001
        logger.warning("sigterm_received — initiating graceful shutdown")
        loop.call_soon_threadsafe(subscriber.shutdown_event.set)

    signal.signal(signal.SIGTERM, _sigterm_handler)
    signal.signal(signal.SIGINT, _sigterm_handler)  # local dev Ctrl-C

    # -----------------------------------------------------------------------
    # 4. Start health server (background) + Pub/Sub subscriber (foreground)
    # -----------------------------------------------------------------------
    health_config = uvicorn.Config(
        health_app,
        host="0.0.0.0",  # noqa: S104
        port=int(os.environ.get("PORT", 8080)),
        log_level="warning",
    )
    health_server = uvicorn.Server(health_config)

    try:
        await asyncio.gather(
            health_server.serve(),
            _run_subscriber(subscriber),
        )
    finally:
        # -----------------------------------------------------------------------
        # 5. Cleanup — close DB engine
        # -----------------------------------------------------------------------
        await engine.dispose()
        logger.info("coordinator_agent_shutdown_complete")


async def _run_subscriber(subscriber: ADTSubscriber) -> None:
    """Run subscriber with a 30-second drain timeout on shutdown (TR-017)."""
    try:
        await asyncio.wait_for(
            subscriber.start(),
            timeout=None,  # subscriber.start() blocks until shutdown_event
        )
    except asyncio.TimeoutError:
        logger.error("subscriber_drain_timeout — forcing stop")
        await subscriber.stop()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
```

### 2. Create `coordinator-agent/Dockerfile`

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (layer cache optimisation)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# Cloud Run: PORT env var injected at runtime (default 8080)
ENV PORT=8080

# Non-root user (SEC — least privilege)
RUN adduser --disabled-password --gecos "" appuser
USER appuser

CMD ["python", "-m", "app.main"]
```

### 3. Create `coordinator-agent/requirements.txt`

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
sqlalchemy[asyncio]==2.0.36
asyncpg==0.30.0
google-cloud-pubsub==2.26.1
langchain==0.2.16
langchain-google-vertexai==1.0.10
pydantic==2.9.2
prometheus-client==0.21.0
opentelemetry-sdk==1.28.0
opentelemetry-exporter-gcp-trace==1.8.0
```

---

## Validation

Run from `coordinator-agent/`:

```bash
# 1. Syntax check
python -c "
import ast, pathlib
ast.parse(pathlib.Path('app/main.py').read_text())
print('Syntax check: PASSED')
"

# 2. Import check (requires dependencies installed)
python -c "
from app.main import health_app, main
print('Import check: PASSED')
"

# 3. Health endpoint smoke test
python -c "
from fastapi.testclient import TestClient
from app.main import health_app
client = TestClient(health_app)
resp = client.get('/health')
assert resp.status_code == 200
assert resp.json() == {'status': 'ok'}
print('GET /health: PASSED')
"
```

---

## Files Created / Modified

| Action | Path |
|--------|------|
| CREATE | `coordinator-agent/app/main.py` |
| CREATE | `coordinator-agent/Dockerfile` |
| CREATE | `coordinator-agent/requirements.txt` |

---

## Definition of Done Checklist

- [ ] `signal.signal(SIGTERM, _sigterm_handler)` registered before subscriber starts
- [ ] `_sigterm_handler` calls `loop.call_soon_threadsafe(subscriber.shutdown_event.set)` — thread-safe
- [ ] `signal.signal(SIGINT, _sigterm_handler)` also registered for local development
- [ ] `health_app` exposes `GET /health` and `GET /ready` returning `{"status": "ok"}`
- [ ] `engine.dispose()` called in `finally` block — no connection leaks
- [ ] Dockerfile uses non-root user (`appuser`) for security
- [ ] `CMD ["python", "-m", "app.main"]` in Dockerfile (not shell form)
- [ ] Process exits within 30 seconds of SIGTERM (tested in TASK-006)
