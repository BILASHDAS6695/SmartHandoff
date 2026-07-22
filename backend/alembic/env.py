"""Alembic environment configuration.

DB connection string is resolved from the DATABASE_URL environment variable,
which is injected at Cloud Run startup from GCP Secret Manager.
No credentials are hardcoded in this file (TR-021, SEC-011).
"""
from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

# Load alembic.ini logging config
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import ORM metadata so Alembic is aware of the schema.
# autogenerate is NOT used for production migrations (hand-authored only).
# This import is kept for offline inspection / tooling only.
try:
    from app.db.base import Base  # noqa: F401 — registers all model metadata
    target_metadata = Base.metadata
except ImportError:
    # Allow env.py to be loaded before models are defined (e.g., during init)
    target_metadata = None


def get_database_url() -> str:
    """Resolve async-compatible DB URL from environment.

    Cloud Run injects DATABASE_URL via Secret Manager binding.
    For local dev, set DATABASE_URL in .env or shell.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set. "
            "Ensure the Secret Manager binding is active in Cloud Run "
            "or set DATABASE_URL for local development."
        )
    # Ensure the asyncpg driver is used (SQLAlchemy 2.x async requirement)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def include_object(object, name, type_, reflected, compare_to):
    """Exclude objects that are managed outside of autogenerate.

    Materialised views (mv_*) are hand-authored (US-009/TASK-004).
    Alembic cannot detect or manage materialised view drift automatically.
    """
    if type_ == "table" and name.startswith("mv_"):
        return False
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generates SQL without DB connection).

    Useful for generating migration SQL for DBA review before applying.
    """
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations using an async SQLAlchemy engine."""
    connectable = create_async_engine(
        get_database_url(),
        poolclass=pool.NullPool,  # Alembic does not benefit from connection pooling
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online migration mode (applies to live DB)."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
