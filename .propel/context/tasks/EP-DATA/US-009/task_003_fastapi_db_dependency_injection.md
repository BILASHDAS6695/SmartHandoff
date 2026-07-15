---
id: TASK-003
title: "Implement FastAPI `get_write_db` / `get_read_db` Dependency Injection"
user_story: US-009
epic: EP-DATA
sprint: 1
layer: Backend
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [TASK-002]
---

# TASK-003: Implement FastAPI `get_write_db` / `get_read_db` Dependency Injection

> **Story:** US-009 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Backend | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

US-009 Technical Notes specify:

> "Use FastAPI dependency injection: `Depends(get_write_db)` vs `Depends(get_read_db)`"

TASK-002 creates the `write_session_factory` and `read_session_factory` module-level objects in `session.py`. This task creates the two async generator dependencies in `backend/app/db/deps.py` that route each endpoint to the correct engine, replacing any existing `get_db` dependency that pointed only to the primary.

The routing rule is explicit:
- **Mutation endpoints** (`POST`, `PUT`, `PATCH`, `DELETE`) → `Depends(get_write_db)`
- **Query endpoints** (`GET`) → `Depends(get_read_db)`
- **Endpoints that mix reads and writes within a single request** → `Depends(get_write_db)` (correctness over read performance)

> **Replica lag caveat:** The Cloud SQL read replica typically lags 1–2 seconds behind the primary (ADR-006). Endpoints that read immediately after writing the same record (e.g., `POST /encounters` → redirect to `GET /encounters/{id}`) must use the write session for the read or add explicit post-write delay logic. Such endpoints are marked in the router comments.

---

## Acceptance Criteria Addressed

| US-009 AC | Requirement |
|---|---|
| **Scenario 2** | Write session routes `INSERT INTO encounter` to Cloud SQL primary |
| **Scenario 3** | Read session routes `SELECT * FROM encounter` to Cloud SQL read replica |
| **DoD** | `get_db_session()` returns write session for mutations, read session for queries |

---

## Implementation Steps

### 1. Create `backend/app/db/deps.py`

```python
"""FastAPI database session dependency injection.

Provides two async generator dependencies for endpoint routing:

  get_write_db()
    Yields an AsyncSession bound to the write engine (PgBouncer → Cloud SQL primary).
    Use for: POST, PUT, PATCH, DELETE endpoints, and any endpoint that reads
    immediately after writing (to avoid replica lag inconsistency).

  get_read_db()
    Yields an AsyncSession bound to the read engine (Cloud SQL replica direct).
    Use for: GET endpoints, dashboard queries, analytics, materialised view reads.

Usage in endpoint:
    @router.post("/encounters")
    async def create_encounter(
        payload: EncounterCreate,
        db: AsyncSession = Depends(get_write_db),
    ) -> EncounterResponse:
        ...

    @router.get("/encounters/{encounter_id}")
    async def get_encounter(
        encounter_id: UUID,
        db: AsyncSession = Depends(get_read_db),
    ) -> EncounterResponse:
        ...

References:
  TR-010: 100% of dashboard GET requests route to read replica (ADR-006)
  US-009 Technical Notes: Depends(get_write_db) vs Depends(get_read_db)
"""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import read_session_factory, write_session_factory

logger = logging.getLogger(__name__)


async def get_write_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession connected to the Cloud SQL primary via PgBouncer.

    The session is automatically closed and the connection returned to the
    PgBouncer pool when the request finishes (or on exception).

    Transaction management:
      The session is NOT auto-committed. Endpoint code must call
      `await db.commit()` explicitly to persist changes.
      `await db.rollback()` is called automatically on exception by the
      try/finally block.
    """
    if write_session_factory is None:
        raise RuntimeError(
            "write_session_factory is not initialised. "
            "Ensure create_db_engines() was called during application startup."
        )
    async with write_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def get_read_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession connected to the Cloud SQL read replica.

    The session is read-only by intent (no commit calls expected).
    Replica lag is typically <1s; do NOT use this dependency for reads
    that must reflect a write made within the same request lifecycle.

    The session is automatically closed and the connection returned to the
    replica connection pool when the request finishes.
    """
    if read_session_factory is None:
        raise RuntimeError(
            "read_session_factory is not initialised. "
            "Ensure create_db_engines() was called during application startup."
        )
    async with read_session_factory() as session:
        yield session
```

### 2. Update All Existing Router Endpoints to Use Typed Dependencies

Search for all existing `Depends(get_db)` references in `backend/app/routers/` and replace them with the appropriate session dependency:

```bash
# Find all usages of the old get_db dependency
grep -rn "Depends(get_db)" backend/app/routers/
```

For each endpoint found, apply the following routing rule:

| HTTP Method | Replace With |
|---|---|
| `GET` | `Depends(get_read_db)` |
| `POST`, `PUT`, `PATCH`, `DELETE` | `Depends(get_write_db)` |

**Important — mixed read-after-write pattern:** If a `GET` endpoint is a redirect target immediately after a `POST` (e.g., the standard REST create-then-redirect), annotate it with a comment:

```python
# NOTE: Uses get_write_db to avoid replica lag after create (US-009/TASK-003)
db: AsyncSession = Depends(get_write_db),
```

These cases should be explicitly listed in the code review checklist (TASK-007).

### 3. Update Import in `backend/app/db/__init__.py`

Ensure `get_write_db` and `get_read_db` are exported from the `db` package for cleaner import paths in routers:

```python
# backend/app/db/__init__.py
from app.db.deps import get_read_db, get_write_db
from app.db.session import create_db_engines, dispose_db_engines

__all__ = [
    "get_write_db",
    "get_read_db",
    "create_db_engines",
    "dispose_db_engines",
]
```

### 4. Remove or Deprecate the Old `get_db` Dependency

If a single `get_db` function existed before this task, mark it as deprecated and schedule removal:

```python
# backend/app/db/deps.py (add deprecation shim at the bottom if needed)
import warnings

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """DEPRECATED: Use get_write_db() or get_read_db() instead (US-009).

    This shim routes all traffic to the write session for backwards
    compatibility. It will be removed after all routers are updated.
    """
    warnings.warn(
        "get_db() is deprecated. Use get_write_db() or get_read_db() "
        "explicitly (US-009/TASK-003).",
        DeprecationWarning,
        stacklevel=2,
    )
    async for session in get_write_db():
        yield session
```

---

## File Checklist

| File | Action |
|---|---|
| `backend/app/db/deps.py` | Create |
| `backend/app/db/__init__.py` | Update exports |
| `backend/app/routers/*.py` | Update `Depends(get_db)` → `Depends(get_write_db)` or `Depends(get_read_db)` |

---

## Dependencies

- **TASK-002** — `write_session_factory` and `read_session_factory` must be initialised
