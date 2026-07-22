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
import warnings
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
