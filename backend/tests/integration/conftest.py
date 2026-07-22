"""Pytest fixtures for US-015 integration tests.

Provides an in-memory SQLite async session fixture that creates the full ORM
schema via ``Base.metadata.create_all``.  Each test function receives a fresh
session that is rolled back after the test to ensure isolation.

Encryption note:
    ``EncryptedString`` / ``EncryptedText`` TypeDecorators (US-007) require a
    32-byte AES key.  The fixture sets ``PHI_ENCRYPTION_KEY`` to a synthetic
    test key before the engine is created so column-level encryption works in
    SQLite in-memory mode without GCP Secret Manager.

Design refs:
    US-015 TASK-006 — integration test: A01 → 5 tasks → A11 → all CANCELLED
    TR-020          — ≥80% branch coverage, CI must pass
"""
from __future__ import annotations

import base64
import os

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base

# 32-byte synthetic test key (base64url-encoded) — never used in production
_TEST_PHI_KEY = base64.urlsafe_b64encode(b"smarthandoff-test-key-0000000000").decode()
os.environ.setdefault("PHI_ENCRYPTION_KEY", _TEST_PHI_KEY)


@pytest_asyncio.fixture(scope="module")
async def _int_engine():
    """Module-scoped in-memory SQLite async engine with schema applied."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture()
async def async_db(_int_engine) -> AsyncSession:
    """Function-scoped async session with rollback isolation.

    Yields a session for each test and rolls it back afterwards so tests
    do not leave state in the shared in-memory database.
    """
    factory = async_sessionmaker(_int_engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
