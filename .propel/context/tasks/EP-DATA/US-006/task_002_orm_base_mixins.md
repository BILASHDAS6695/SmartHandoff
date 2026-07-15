---
id: TASK-002
title: "Define SQLAlchemy ORM Base — `DeclarativeBase`, Timestamp Mixin, and Soft-Delete Mixin"
user_story: US-006
epic: EP-DATA
sprint: 1
layer: Backend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [TASK-001]
---

# TASK-002: Define SQLAlchemy ORM Base — `DeclarativeBase`, Timestamp Mixin, and Soft-Delete Mixin

> **Story:** US-006 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Backend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

All 10 ORM models (TASK-003 through TASK-005) share common infrastructure:

- **`DeclarativeBase`** — the single SQLAlchemy 2.x base class all models inherit from, which registers their metadata with Alembic's `env.py`
- **`TimestampMixin`** — adds `created_at` / `updated_at` columns (auto-managed) to all tables that need audit timestamps
- **`SoftDeleteMixin`** — adds the `deleted_at` column required by DR-005 for `patient` and `encounter`; provides a query helper that filters active records

Without this shared infrastructure, every model would duplicate column definitions and the soft-delete filter, violating the DRY principle and creating maintenance risk.

This task also creates the `SessionFactory` helper that all backend services import to obtain DB sessions, ensuring consistent async session lifecycle management.

---

## Acceptance Criteria Addressed

| US-006 AC | Requirement |
|---|---|
| **Scenario 4** | Soft delete: `deleted_at` column populated on soft-delete; standard queries exclude soft-deleted records — the `SoftDeleteMixin` is the foundational mechanism |
| **DoD** | Soft-delete columns (`deleted_at`) on `patient` and `encounter` tables (DR-005) |

---

## Implementation Steps

### 1. Author `backend/app/db/base.py` — `DeclarativeBase` and `Base`

```python
"""SQLAlchemy 2.x declarative base for all ORM models.

All models must inherit from `Base`. This registers their metadata
with Alembic's `env.py` via the `target_metadata = Base.metadata` reference.
"""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Project-wide SQLAlchemy declarative base.

    Usage:
        class MyModel(Base):
            __tablename__ = "my_model"
            ...
    """
    pass
```

### 2. Author `backend/app/db/mixins.py` — `TimestampMixin` and `SoftDeleteMixin`

```python
"""Reusable SQLAlchemy ORM mixins for timestamp management and soft deletes.

DR-005: Soft deletes on `patient` and `encounter` — no hard deletes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """Adds `created_at` and `updated_at` columns to any model.

    `created_at` is set once at INSERT time (server default).
    `updated_at` is updated on every UPDATE (onupdate trigger).
    Both columns store UTC timestamps.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """Adds `deleted_at` column and active-record query helper.

    DR-005: Patient and encounter records are never hard-deleted.
    `deleted_at=NULL` → active record.
    `deleted_at=<timestamp>` → soft-deleted; excluded from standard queries.

    Usage:
        # Standard query (excludes deleted):
        stmt = select(Patient).where(Patient.deleted_at.is_(None))

        # Include deleted (admin / audit use only):
        stmt = select(Patient)  # no filter
    """

    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        index=True,  # Index supports `WHERE deleted_at IS NULL` queries
    )

    def soft_delete(self) -> None:
        """Mark this record as deleted by setting `deleted_at` to UTC now.

        Does NOT flush or commit — caller is responsible for the session.
        """
        self.deleted_at = datetime.now(tz=timezone.utc)

    @property
    def is_deleted(self) -> bool:
        """Return True if this record has been soft-deleted."""
        return self.deleted_at is not None
```

### 3. Author `backend/app/db/session.py` — Async Session Factory

```python
"""Async SQLAlchemy session factory.

All backend services obtain DB sessions through `get_async_session`.
The session lifetime is one request (FastAPI dependency injection pattern).

Connection pool is configured for Cloud Run:
- pool_size and max_overflow are intentionally 0 (NullPool) — PgBouncer
  handles pooling externally (TR-009). Cloud Run instances must not
  maintain long-lived DB connections.
"""
from __future__ import annotations

import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool


def _build_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is not set.")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


_engine = create_async_engine(
    _build_database_url(),
    poolclass=NullPool,  # PgBouncer handles external pooling (TR-009)
    echo=os.environ.get("SQL_ECHO", "false").lower() == "true",
)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an async DB session per request.

    Usage:
        @router.get("/patients")
        async def list_patients(db: AsyncSession = Depends(get_async_session)):
            ...
    """
    async with AsyncSessionLocal() as session:
        yield session
```

### 4. Update `backend/app/db/__init__.py`

Expose the key symbols for clean imports:

```python
from app.db.base import Base
from app.db.session import AsyncSessionLocal, get_async_session

__all__ = ["Base", "AsyncSessionLocal", "get_async_session"]
```

### 5. Verify Metadata Registration

Confirm that `Base.metadata` is populated when models are imported. This is verified in TASK-008 (integration tests), but a quick smoke check can be done locally:

```python
# Run from backend/ directory
from app.db.base import Base
print(Base.metadata.tables)  # Should print {} before models are imported
```

---

## Definition of Done

- [ ] `backend/app/db/base.py` defines `Base(DeclarativeBase)` with no columns (clean base class)
- [ ] `backend/app/db/mixins.py` defines `TimestampMixin` (created_at, updated_at) and `SoftDeleteMixin` (deleted_at, soft_delete(), is_deleted)
- [ ] `backend/app/db/session.py` defines async session factory using `NullPool` (PgBouncer-compatible)
- [ ] `SoftDeleteMixin.deleted_at` column has `index=True` for query performance
- [ ] `backend/app/db/__init__.py` exports `Base`, `AsyncSessionLocal`, `get_async_session`
- [ ] `TimestampMixin.created_at` uses `server_default=func.now()` (DB-side default, not Python-side)
- [ ] `TimestampMixin.updated_at` uses `onupdate=func.now()` for automatic update tracking
- [ ] No hardcoded DB credentials in any file in this task

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 | Preceding task | `backend/app/db/` directory stub must exist |

---

## Files Modified

| File | Action |
|---|---|
| `backend/app/db/base.py` | Create |
| `backend/app/db/mixins.py` | Create |
| `backend/app/db/session.py` | Create |
| `backend/app/db/__init__.py` | Update (add exports) |
