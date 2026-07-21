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
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
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


@lru_cache(maxsize=1)
def _get_engine() -> AsyncEngine:
    """Return the shared async engine, creating it on first call.

    Deferred creation ensures `DATABASE_URL` does not need to be set at
    module import time — it only needs to be present when the first DB
    session is requested (TR-009, Cloud Run Secret Manager binding).
    """
    return create_async_engine(
        _build_database_url(),
        poolclass=NullPool,  # PgBouncer handles external pooling (TR-009)
        echo=os.environ.get("SQL_ECHO", "false").lower() == "true",
    )


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=_get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
    )


# Public alias — kept for backwards compatibility with any code that imports
# `AsyncSessionLocal` directly.  Resolves lazily on first attribute access.
class _LazySessionLocal:
    """Proxy that creates the session factory on first use."""

    def __call__(self, **kwargs):  # type: ignore[override]
        return _get_session_factory()(**kwargs)

    def __getattr__(self, name: str):
        return getattr(_get_session_factory(), name)


AsyncSessionLocal: async_sessionmaker[AsyncSession] = _LazySessionLocal()  # type: ignore[assignment]


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an async DB session per request.

    Usage:
        @router.get("/patients")
        async def list_patients(db: AsyncSession = Depends(get_async_session)):
            ...
    """
    async with _get_session_factory()() as session:
        yield session
