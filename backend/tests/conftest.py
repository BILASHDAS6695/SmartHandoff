"""Pytest configuration and shared fixtures for US-006 integration tests.

Uses testcontainers to spin up a real PostgreSQL 15 instance matching Cloud SQL.
The container is shared across all tests in the session for performance.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer

# Absolute path to the backend/ directory (parent of tests/).  All Alembic
# operations resolve paths relative to this directory, regardless of the
# working directory from which pytest is invoked.
_BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent


# ── Session-scoped PostgreSQL container ───────────────────────────────────────

@pytest.fixture(scope="session")
def pg_container():
    """Start a PostgreSQL 15 container for the test session."""
    with PostgresContainer("postgres:15-alpine") as postgres:
        yield postgres


@pytest.fixture(scope="session")
def database_url(pg_container: PostgresContainer) -> str:
    """Return the asyncpg-compatible URL for the test container."""
    url = pg_container.get_connection_url()
    # Convert to asyncpg scheme
    return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")


@pytest.fixture(scope="session")
def apply_migrations(database_url: str) -> None:
    """Apply all Alembic migrations to the test database (session scope).

    Runs synchronously before any async tests to ensure the schema is ready.
    """
    # Set DATABASE_URL so env.py can resolve the connection string
    os.environ["DATABASE_URL"] = database_url

    # Use absolute paths so tests are runnable from any working directory.
    alembic_cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    command.upgrade(alembic_cfg, "head")


@pytest.fixture(scope="session")
def async_engine(database_url: str, apply_migrations):
    """Shared async SQLAlchemy engine connected to the test container."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    yield engine
    # asyncio.run() creates a fresh event loop for teardown — safe in Python 3.10+
    # (replaces the deprecated asyncio.get_event_loop().run_until_complete() pattern).
    asyncio.run(engine.dispose())


@pytest_asyncio.fixture
async def db_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    """Per-test async session with automatic rollback for test isolation.

    Each test gets a fresh session. Changes are rolled back after the test
    to keep the database clean for subsequent tests.
    """
    session_factory = async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        async with session.begin():
            yield session
            # Rollback to clean state after each test
            await session.rollback()
