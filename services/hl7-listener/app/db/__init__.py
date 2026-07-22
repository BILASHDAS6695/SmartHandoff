"""Async SQLAlchemy session factory for the HL7 Listener service.

Provides ``get_async_session()`` — an async context manager yielding an
``AsyncSession`` bound to the Cloud SQL PostgreSQL instance.

Configuration (environment variables):
    DATABASE_URL — async SQLAlchemy connection URL, e.g.:
        postgresql+asyncpg://user:pass@/dbname?host=/cloudsql/proj:region:instance

Design refs:
    ADR-003 — Cloud SQL PostgreSQL as system of record
    TR-001  — Async DB access via asyncpg driver
    US-006  — adt_event table schema and source_message_id index
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ---------------------------------------------------------------------------
# Engine — lazy singleton
# ---------------------------------------------------------------------------

_engine = None
_SessionLocal: async_sessionmaker[AsyncSession] | None = None


def _get_engine():
    """Lazy-initialise the async engine from DATABASE_URL env var."""
    global _engine, _SessionLocal
    if _engine is None:
        database_url = os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://localhost/smarthandoff",
        )
        _engine = create_async_engine(
            database_url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            echo=False,
        )
        _SessionLocal = async_sessionmaker(
            bind=_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _engine, _SessionLocal


# ---------------------------------------------------------------------------
# Public session factory
# ---------------------------------------------------------------------------

@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a SQLAlchemy async session; commit on success, rollback on error.

    Usage::

        async with get_async_session() as session:
            result = await session.execute(...)
    """
    _, session_factory = _get_engine()
    assert session_factory is not None
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
