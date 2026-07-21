"""SQLAlchemy async engine and session factory configuration.

Two engines are configured:
  write_engine  → PgBouncer sidecar (localhost:5432) → Cloud SQL primary
  read_engine   → Cloud SQL read replica (direct private IP)

Both URLs are resolved from environment variables (Secret Manager in production,
env var for local development). See _resolve_db_url() for resolution order.

The legacy `get_async_session` / `AsyncSessionLocal` symbols are preserved
for backwards compatibility and route to the write engine.

References:
  TR-009: ≤500 DB connections via PgBouncer transaction-pool mode
  TR-010: 100% of dashboard GET requests routed to read replica
  ADR-006: CQRS — write path via primary, read path via replica
  US-009 Technical Notes: write_session_factory / read_session_factory
"""
from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator
from typing import Final

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger(__name__)

# ── Connection pool configuration ────────────────────────────────────────────
# Write engine: small pool — PgBouncer multiplexes these onto 20 server connections.
# Keep app pool small so total PgBouncer client connections stay within max_client_conn=500.
_WRITE_POOL_SIZE: Final[int] = 5
_WRITE_MAX_OVERFLOW: Final[int] = 10

# Read engine: larger pool — direct to replica, read-heavy workloads benefit from
# pre-warmed connections.
_READ_POOL_SIZE: Final[int] = 10
_READ_MAX_OVERFLOW: Final[int] = 20

# Module-level engine singletons (initialised in create_db_engines())
_write_engine: AsyncEngine | None = None
_read_engine: AsyncEngine | None = None

write_session_factory: async_sessionmaker[AsyncSession] | None = None
read_session_factory: async_sessionmaker[AsyncSession] | None = None


def _resolve_db_url(env_var_name: str, secret_id_env_var: str) -> str:
    """Resolve a database connection URL from Secret Manager or env var.

    Resolution order:
      1. If <env_var_name> is set: use directly (local dev / CI).
         Logs a WARNING to prevent accidental use in production.
      2. Otherwise: load from GCP Secret Manager using the secret ID in
         <secret_id_env_var>.

    Raises RuntimeError if neither source is available.
    """
    direct_url = os.getenv(env_var_name)
    if direct_url:
        logger.warning(
            "%s is set via environment variable — acceptable for local dev only. "
            "Use GCP Secret Manager in production (set %s instead).",
            env_var_name,
            secret_id_env_var,
        )
        return direct_url

    secret_id = os.getenv(secret_id_env_var)
    if not secret_id:
        raise RuntimeError(
            f"Database URL not configured: neither {env_var_name} nor "
            f"{secret_id_env_var} environment variable is set. "
            "In production, set the Secret Manager secret ID via "
            f"{secret_id_env_var}."
        )

    try:
        from google.cloud import secretmanager  # type: ignore[import]

        client = secretmanager.SecretManagerServiceClient()
        name = (
            secret_id
            if secret_id.startswith("projects/")
            else f"projects/{os.environ['GOOGLE_CLOUD_PROJECT']}/secrets/{secret_id}/versions/latest"
        )
        response = client.access_secret_version(request={"name": name})
        url = response.payload.data.decode("utf-8").strip()
        logger.info("Database URL loaded from Secret Manager secret: %s", secret_id)
        return url
    except Exception as exc:
        raise RuntimeError(
            f"Failed to load database URL from Secret Manager "
            f"(secret_id={secret_id}): {exc}"
        ) from exc


def create_db_engines() -> None:
    """Initialise write and read engines and session factories.

    Must be called once at application startup (FastAPI lifespan context).
    Calling twice is a no-op if engines are already initialised.
    """
    global _write_engine, _read_engine, write_session_factory, read_session_factory

    if _write_engine is not None:
        logger.debug("DB engines already initialised; skipping re-initialisation.")
        return

    write_url = _resolve_db_url(
        env_var_name="PRIMARY_DATABASE_URL",
        secret_id_env_var="PRIMARY_DB_SECRET_ID",
    )
    read_url = _resolve_db_url(
        env_var_name="REPLICA_DATABASE_URL",
        secret_id_env_var="REPLICA_DB_SECRET_ID",
    )

    _write_engine = create_async_engine(
        write_url,
        pool_size=_WRITE_POOL_SIZE,
        max_overflow=_WRITE_MAX_OVERFLOW,
        pool_pre_ping=True,   # Verify connection before use (handles PgBouncer timeout)
        pool_recycle=1800,    # Recycle connections every 30 min to avoid stale sockets
        echo=False,
    )

    _read_engine = create_async_engine(
        read_url,
        pool_size=_READ_POOL_SIZE,
        max_overflow=_READ_MAX_OVERFLOW,
        pool_pre_ping=True,
        pool_recycle=1800,
        echo=False,
    )

    write_session_factory = async_sessionmaker(
        bind=_write_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )

    read_session_factory = async_sessionmaker(
        bind=_read_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )

    logger.info(
        "DB engines initialised — write pool: %d+%d, read pool: %d+%d",
        _WRITE_POOL_SIZE,
        _WRITE_MAX_OVERFLOW,
        _READ_POOL_SIZE,
        _READ_MAX_OVERFLOW,
    )


async def dispose_db_engines() -> None:
    """Dispose both engines gracefully on application shutdown.

    Must be called from FastAPI lifespan shutdown handler to drain
    in-flight connections before the Cloud Run SIGTERM timeout (30s).
    """
    global _write_engine, _read_engine, write_session_factory, read_session_factory

    if _write_engine is not None:
        await _write_engine.dispose()
        logger.info("Write DB engine disposed.")
    if _read_engine is not None:
        await _read_engine.dispose()
        logger.info("Read DB engine disposed.")

    _write_engine = None
    _read_engine = None
    write_session_factory = None
    read_session_factory = None


def get_write_engine() -> AsyncEngine:
    """Return the write engine. Raises if not yet initialised."""
    if _write_engine is None:
        raise RuntimeError(
            "Write DB engine is not initialised. "
            "Ensure create_db_engines() is called in the FastAPI lifespan."
        )
    return _write_engine


def get_read_engine() -> AsyncEngine:
    """Return the read engine. Raises if not yet initialised."""
    if _read_engine is None:
        raise RuntimeError(
            "Read DB engine is not initialised. "
            "Ensure create_db_engines() is called in the FastAPI lifespan."
        )
    return _read_engine


# ── Backwards-compatibility shims ────────────────────────────────────────────
# Preserved for any code that predates US-009. These route to the write engine.

class _LazySessionLocal:
    """Proxy that creates the write session factory on first use."""

    def __call__(self, **kwargs):  # type: ignore[override]
        if write_session_factory is None:
            raise RuntimeError(
                "write_session_factory is not initialised. "
                "Ensure create_db_engines() is called during application startup."
            )
        return write_session_factory(**kwargs)

    def __getattr__(self, name: str):
        if write_session_factory is None:
            raise RuntimeError(
                "write_session_factory is not initialised. "
                "Ensure create_db_engines() is called during application startup."
            )
        return getattr(write_session_factory, name)


AsyncSessionLocal: async_sessionmaker[AsyncSession] = _LazySessionLocal()  # type: ignore[assignment]


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an async write DB session per request.

    DEPRECATED: Use get_write_db() or get_read_db() from app.db.deps instead (US-009).
    This shim routes to the write engine for backwards compatibility.

    Usage:
        @router.get("/patients")
        async def list_patients(db: AsyncSession = Depends(get_async_session)):
            ...
    """
    if write_session_factory is None:
        raise RuntimeError(
            "write_session_factory is not initialised. "
            "Ensure create_db_engines() is called during application startup."
        )
    async with write_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
