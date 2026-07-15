---
id: TASK-002
title: "Implement SQLAlchemy Dual-Engine Session Factory — Write (Primary) and Read (Replica)"
user_story: US-009
epic: EP-DATA
sprint: 1
layer: Backend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [TASK-001, US-001]
---

# TASK-002: Implement SQLAlchemy Dual-Engine Session Factory — Write (Primary) and Read (Replica)

> **Story:** US-009 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Backend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

US-009 Technical Notes specify:

> "SQLAlchemy `sessionmaker` factory: `write_session_factory` bound to primary URL, `read_session_factory` bound to replica URL"

The write engine connects to PgBouncer on `localhost:5432` (the sidecar from TASK-001), which proxies to the Cloud SQL **primary**. The read engine connects **directly** to the Cloud SQL read replica via private VPC IP — it bypasses PgBouncer because read workloads (dashboard queries, materialised view reads) benefit from persistent connections and the replica does not participate in write transactions that need PgBouncer's transaction-mode pooling.

Both URLs are resolved from **GCP Secret Manager** at application startup — never hardcoded. The session module follows the same resolution pattern established in US-008 `audit_session.py`.

### Connection URL formats

| Engine | URL env var | Target | Pool strategy |
|---|---|---|---|
| Write | `PRIMARY_DATABASE_URL` | PgBouncer localhost:5432 → Cloud SQL primary | `pool_size=5`, `max_overflow=10` (PgBouncer multiplexes; keep app pool small) |
| Read | `REPLICA_DATABASE_URL` | Cloud SQL replica private IP (direct) | `pool_size=10`, `max_overflow=20` (read-heavy; larger pool is safe) |

**Why small write pool?** Each FastAPI worker instance connects through PgBouncer. PgBouncer multiplexes up to 500 client connections onto 20 server connections. If the app pool is too large, it creates more PgBouncer client connections than necessary. A pool of 5 per worker with max_overflow=10 gives 15 potential connections per Cloud Run instance × 20 max instances = 300 PgBouncer client connections, well within the 500 limit.

---

## Acceptance Criteria Addressed

| US-009 AC | Requirement |
|---|---|
| **Scenario 2** | `INSERT INTO encounter` routed to Cloud SQL primary |
| **Scenario 3** | `SELECT * FROM encounter` routed to Cloud SQL read replica |
| **DoD** | `get_db_session()` dependency returns write session for mutations, read session for queries |

---

## Implementation Steps

### 1. Create `backend/app/db/session.py`

This module is the **single source of truth** for all SQLAlchemy engine and session factory configuration in the application.

```python
"""SQLAlchemy async engine and session factory configuration.

Two engines are configured:
  write_engine  → PgBouncer sidecar (localhost:5432) → Cloud SQL primary
  read_engine   → Cloud SQL read replica (direct private IP)

Both URLs are resolved from environment variables (Secret Manager in production,
env var for local development). See _resolve_db_url() for resolution order.

References:
  TR-009: ≤500 DB connections via PgBouncer transaction-pool mode
  TR-010: 100% of dashboard GET requests routed to read replica
  ADR-006: CQRS — write path via primary, read path via replica
  US-009 Technical Notes: write_session_factory / read_session_factory
"""
from __future__ import annotations

import logging
import os
from typing import Final

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

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
```

### 2. Register Required Secrets in Secret Manager

Add the following entries to the `infra/terraform/modules/secrets/main.tf` (or provision manually for initial dev environments):

| Secret ID | Description |
|---|---|
| `smarthandoff-primary-db-url-<env>` | Full async DSN: `postgresql+asyncpg://app_user:password@127.0.0.1:5432/smarthandoff` (via PgBouncer) |
| `smarthandoff-replica-db-url-<env>` | Full async DSN: `postgresql+asyncpg://app_user:password@<replica-private-ip>:5432/smarthandoff` |

The Cloud Run environment variables `PRIMARY_DB_SECRET_ID` and `REPLICA_DB_SECRET_ID` must be set to the respective secret IDs.

### 3. Update `backend/app/main.py` — Lifespan Integration

Add `create_db_engines()` to the FastAPI startup lifespan and `dispose_db_engines()` to the shutdown path. This ensures connection pools are warmed up before the service handles its first request (avoiding cold-start latency spikes).

```python
# In backend/app/main.py (relevant lifespan section only)
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.db.session import create_db_engines, dispose_db_engines

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: warm DB connection pools (write + read)
    create_db_engines()
    yield
    # Shutdown: drain connections gracefully before SIGTERM timeout
    await dispose_db_engines()

app = FastAPI(lifespan=lifespan, ...)
```

> **Note:** The lifespan integration is the minimum change required by this task. TASK-003 adds the `get_write_db` / `get_read_db` FastAPI dependency functions that call these factories.

---

## File Checklist

| File | Action |
|---|---|
| `backend/app/db/session.py` | Create |
| `backend/app/main.py` | Update lifespan to call `create_db_engines()` / `dispose_db_engines()` |
| `infra/terraform/modules/secrets/main.tf` | Add `smarthandoff-primary-db-url-<env>` and `smarthandoff-replica-db-url-<env>` secrets |

---

## Dependencies

- **TASK-001** — PgBouncer sidecar must be running on `localhost:5432` for the write URL to resolve
- **US-001** — Cloud SQL replica private IP must be known to populate the replica DSN secret
