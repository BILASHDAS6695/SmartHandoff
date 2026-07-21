---
id: TASK-001
title: "Initialize Alembic Project Structure and Configure `alembic.ini` with Secret Manager DB URL"
user_story: US-006
epic: EP-DATA
sprint: 1
layer: Backend
estimate: 2h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: []
---

# TASK-001: Initialize Alembic Project Structure and Configure `alembic.ini` with Secret Manager DB URL

> **Story:** US-006 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Backend | **Est:** 2 h
> **Status:** Done | **Date:** 2026-07-15

---

## Context

US-006 requires every environment to be bootstrapped from a deterministic, version-controlled schema managed by Alembic (DR-001). Before any migration file can be authored, the Alembic project scaffolding must exist and be configured to:

1. Retrieve the PostgreSQL connection string from **GCP Secret Manager** at runtime — not from a hardcoded `sqlalchemy.url` in `alembic.ini` (TR-021).
2. Use an **asyncpg** async driver compatible with SQLAlchemy 2.x async sessions.
3. Enforce the **hand-authored migration** policy (`autogenerate = False`) to prevent drift between generated and actual DDL (US-006 Technical Notes).

This task creates the skeleton into which all subsequent tasks (TASK-002 through TASK-007) will insert their ORM models and migration files.

---

## Acceptance Criteria Addressed

| US-006 AC | Requirement |
|---|---|
| **Scenario 1** | `alembic upgrade head` must execute without errors on a fresh database — the project structure and configuration are the prerequisite |
| **DoD** | `alembic.ini` must use Secret Manager reference for DB connection string, not a hardcoded value |

---

## Implementation Steps

### 1. Create the `backend/` Directory Structure

Create the following directories and empty placeholder files:

```
backend/
├── alembic.ini
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── .gitkeep
└── app/
    ├── __init__.py
    ├── db/
    │   └── __init__.py
    └── models/
        └── __init__.py
```

Run `alembic init alembic` inside `backend/` to generate the standard scaffold, then customise each file as described below.

### 2. Configure `backend/alembic.ini`

Replace the generated `sqlalchemy.url` with a placeholder that signals the URL is resolved at runtime (not from this file). The actual connection string is injected by `env.py` via Secret Manager:

```ini
[alembic]
# Script location relative to this file
script_location = alembic

# file_template controls migration filename format
file_template = %%(rev)s_%%(slug)s

# Truncate slug at 40 chars for readability
truncate_slug_length = 40

# sqlalchemy.url is intentionally OMITTED — the DB URL is resolved
# at runtime from GCP Secret Manager in alembic/env.py.
# Do NOT add sqlalchemy.url here (TR-021: zero hardcoded credentials).

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

### 3. Author `backend/alembic/env.py`

This is the critical configuration file. It must:
- Retrieve the DB URL from **Secret Manager** (or `DATABASE_URL` env var injected by Cloud Run Secret Manager binding)
- Create an **async** SQLAlchemy engine using `asyncpg`
- Import `Base.metadata` from the ORM models to allow future `autogenerate` if needed (even though it is disabled for production migrations)
- Set `autogenerate = False` equivalent by not calling `context.configure(autogenerate=True)`

```python
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
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
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
```

### 4. Update `backend/alembic/script.py.mako`

Replace the default template to enforce consistent migration file headers:

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

### 5. Add `backend/requirements.txt` Dependencies

Ensure the following packages are listed (create the file if it doesn't exist):

```
alembic>=1.13.0
sqlalchemy>=2.0.0
asyncpg>=0.29.0
cryptography>=42.0.0
google-cloud-secret-manager>=2.20.0
```

### 6. Verify `alembic.ini` Contains No Hardcoded Credentials

Run a security check to confirm the implementation is clean:

```bash
grep -n "sqlalchemy.url\|password\|://.*:.*@" backend/alembic.ini
```

**Expected output:** No matches. The `sqlalchemy.url` key must be absent from `alembic.ini`.

---

## Definition of Done

- [ ] `backend/alembic/` directory exists with `env.py`, `script.py.mako`, and `versions/.gitkeep`
- [ ] `backend/alembic.ini` contains no `sqlalchemy.url` entry (DB URL resolved at runtime)
- [ ] `backend/alembic/env.py` reads `DATABASE_URL` from environment and converts to `asyncpg` scheme
- [ ] `alembic history` and `alembic current` commands execute without import errors (models stub in place)
- [ ] `grep -n "sqlalchemy.url\|password" backend/alembic.ini` returns zero matches
- [ ] `backend/app/db/__init__.py` and `backend/app/models/__init__.py` are present (empty stubs acceptable)

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| US-001 (TASK-001–TASK-008) | Story | Cloud SQL instance and `DATABASE_URL` secret must exist in Secret Manager before `alembic upgrade` can run against a real DB |

---

## Files Modified

| File | Action |
|---|---|
| `backend/alembic.ini` | Create |
| `backend/alembic/env.py` | Create |
| `backend/alembic/script.py.mako` | Create |
| `backend/alembic/versions/.gitkeep` | Create |
| `backend/app/__init__.py` | Create (empty stub) |
| `backend/app/db/__init__.py` | Create (empty stub) |
| `backend/app/models/__init__.py` | Create (empty stub) |
| `backend/requirements.txt` | Create or update |
