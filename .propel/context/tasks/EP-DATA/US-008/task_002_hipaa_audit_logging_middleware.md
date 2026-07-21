---
id: TASK-002
title: "Implement HIPAA Audit Logging FastAPI Middleware"
user_story: US-008
epic: EP-DATA
sprint: 1
layer: Backend
estimate: 3h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [TASK-001]
---

# TASK-002: Implement HIPAA Audit Logging FastAPI Middleware

> **Story:** US-008 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Backend | **Est:** 3 h
> **Status:** Done | **Date:** 2026-07-15

---

## Context

HIPAA Technical Safeguards (45 CFR §164.312(b)) require an audit control mechanism that records activity in information systems containing PHI. US-008 satisfies this via a FastAPI audit logging middleware that intercepts every request to a PHI endpoint and writes an immutable record to `audit_log` using the `audit_writer` database role.

Key design constraints from the US-008 Technical Notes:

- **Do NOT log PHI field values** in `audit_log` — only `entity_type`, `entity_id`, `action`, `user_id`, `ip_address`, and `created_at`
- Middleware uses a **separate `audit_writer` database session** (different role from the main `app_write` session) so that even if the application is compromised, the audit trail write path is isolated
- The middleware must run **after** authentication (JWT must be validated before audit record is written so `user_id` is known)
- Audit entries are written as a **fire-and-forget background task** to avoid adding latency to the request path; failures are logged to Cloud Logging but do NOT cause the primary request to fail

### PHI Endpoint Set

The following router prefixes are considered PHI endpoints and must be audited:

| Prefix | Audited Actions |
|---|---|
| `/api/v1/patients` | READ, WRITE, DELETE |
| `/api/v1/encounters` | READ, WRITE |
| `/api/v1/documents` | READ, WRITE |
| `/api/v1/medications` | READ, WRITE |
| `/api/v1/admin/audit` | READ |
| `/api/v1/admin/users` | READ, WRITE |

Non-PHI endpoints (`/health`, `/ready`, `/metrics`, `/docs`, `/openapi.json`) must be excluded.

---

## Acceptance Criteria Addressed

| US-008 AC | Requirement |
|---|---|
| **Scenario 3** | `audit_writer` role successfully inserts records with all required fields |
| **DoD** | Middleware logs every PHI access via `audit_writer` role |

---

## Implementation Steps

### 1. Create `backend/app/db/audit_session.py` — Dedicated `audit_writer` Session Factory

This session factory connects using the `audit_writer` PostgreSQL role. It must **not** share the `app_write` connection pool.

```python
"""Dedicated async session factory for the audit_writer PostgreSQL role.

The audit_writer role has INSERT-only privileges on audit_log (US-008/TASK-001).
This session is intentionally isolated from the main app_write session to
ensure the audit trail write path cannot be silenced by app_write privilege
revocation.

Security: The audit_writer DB URL is stored in Secret Manager under
'smarthandoff-audit-writer-db-url-<environment>'.
"""
from __future__ import annotations

import logging
import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logger = logging.getLogger(__name__)

_audit_engine = None
_audit_session_factory: async_sessionmaker[AsyncSession] | None = None


def _build_audit_db_url() -> str:
    """Resolve the audit_writer connection URL from Secret Manager or env var.

    Uses the same resolution pattern as the main DB URL (see alembic/env.py),
    but reads a different secret ID so the role credentials are separate.
    """
    url = os.getenv("AUDIT_WRITER_DATABASE_URL")
    if url:
        logger.warning(
            "AUDIT_WRITER_DATABASE_URL is set via env var — "
            "acceptable for local dev only. Use Secret Manager in production."
        )
        return url

    # Production: resolve from Secret Manager
    secret_id = os.getenv(
        "AUDIT_WRITER_DB_URL_SECRET_ID",
        "smarthandoff-audit-writer-db-url",
    )
    try:
        from google.cloud import secretmanager  # type: ignore[import]

        client = secretmanager.SecretManagerServiceClient()
        project_id = os.environ["GCP_PROJECT_ID"]
        name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("utf-8")
    except Exception:
        logger.exception(
            "Failed to resolve audit_writer DB URL from Secret Manager. "
            "Audit logging will be unavailable."
        )
        raise


def get_audit_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the module-level audit session factory, initialising it on first call."""
    global _audit_engine, _audit_session_factory
    if _audit_session_factory is None:
        url = _build_audit_db_url()
        _audit_engine = create_async_engine(
            url,
            pool_size=5,
            max_overflow=5,
            pool_timeout=10,
            pool_recycle=3600,
            echo=False,
        )
        _audit_session_factory = async_sessionmaker(
            _audit_engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _audit_session_factory
```

### 2. Create `backend/app/models/audit_log.py` — `AuditLog` ORM Model

The `audit_log` table was created in the US-006 initial schema migration. This file maps to that existing table.

```python
"""ORM model for the audit_log table.

audit_log is append-only enforced by PostgreSQL RLS (US-008/TASK-001).
No UPDATE or DELETE operations are permitted via any ORM method.
The INSERT path uses the audit_writer session exclusively.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.UUID(as_uuid=True), nullable=True
    )
    action: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    entity_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(sa.String(45), nullable=True)
    endpoint: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
```

### 3. Create `backend/app/middleware/audit.py` — HIPAA Audit Middleware

```python
"""HIPAA audit logging middleware.

Intercepts all requests to PHI endpoints and writes an immutable record
to audit_log via the audit_writer PostgreSQL role.

Key constraints (US-008 Technical Notes):
- PHI field values are NEVER written to audit_log
- Audit write is a BackgroundTask — does not block the response path
- Failures are logged to Cloud Logging but do NOT surface to the client
- user_id is extracted from the validated JWT (available after auth middleware)

Request lifecycle position:
  Cloud Armor → TLS → Rate Limiter → JWT Validator → RBAC →
  PHI Log Sanitiser → HIPAA Audit Logger ← this middleware
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Callable

from fastapi import BackgroundTasks, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.db.audit_session import get_audit_session_factory
from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)

# ── PHI endpoint prefixes that must be audited ────────────────────────────────
_PHI_PREFIXES: tuple[str, ...] = (
    "/api/v1/patients",
    "/api/v1/encounters",
    "/api/v1/documents",
    "/api/v1/medications",
    "/api/v1/admin/audit",
    "/api/v1/admin/users",
)

# ── HTTP method → audit action mapping ───────────────────────────────────────
_METHOD_ACTION: dict[str, str] = {
    "GET": "READ",
    "HEAD": "READ",
    "POST": "WRITE",
    "PUT": "WRITE",
    "PATCH": "WRITE",
    "DELETE": "DELETE",
}

# ── Endpoints explicitly excluded from auditing ───────────────────────────────
_EXCLUDED_PATHS: frozenset[str] = frozenset(
    {"/health", "/ready", "/metrics", "/docs", "/openapi.json", "/favicon.ico"}
)


def _is_phi_endpoint(path: str) -> bool:
    """Return True if the request path targets a PHI-scoped endpoint."""
    if path in _EXCLUDED_PATHS:
        return False
    return any(path.startswith(prefix) for prefix in _PHI_PREFIXES)


def _extract_entity_info(path: str) -> tuple[str, str | None]:
    """Derive entity_type and entity_id from the URL path.

    Examples:
      /api/v1/patients/abc-123        → ("patient", "abc-123")
      /api/v1/encounters/xyz/documents → ("encounter", "xyz")
      /api/v1/medications             → ("medication", None)
    """
    segments = [s for s in path.split("/") if s]
    # segments[3] is the resource name after /api/v1/
    resource_map = {
        "patients": "patient",
        "encounters": "encounter",
        "documents": "document",
        "medications": "medication",
        "users": "user",
        "audit": "audit_log",
    }
    entity_type = "unknown"
    entity_id: str | None = None

    if len(segments) >= 3:
        entity_type = resource_map.get(segments[2], segments[2].rstrip("s"))
    if len(segments) >= 4:
        # segments[3] is typically the resource UUID
        candidate = segments[3]
        # Only use as entity_id if it looks like a UUID or short alphanumeric ID
        if len(candidate) <= 64 and candidate not in resource_map:
            entity_id = candidate

    return entity_type, entity_id


async def _write_audit_record(
    user_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: str | None,
    ip_address: str | None,
    endpoint: str,
) -> None:
    """Persist one audit_log row via the audit_writer session.

    This coroutine runs as a BackgroundTask. Any exception is caught and
    logged to Cloud Logging — it must NOT propagate to the ASGI layer.
    """
    try:
        factory = get_audit_session_factory()
        async with factory() as session:
            record = AuditLog(
                id=uuid.uuid4(),
                user_id=user_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                ip_address=ip_address,
                endpoint=endpoint,
            )
            session.add(record)
            await session.commit()
    except Exception:
        # Audit write failure is NOT surfaced to the client.
        # Structured log for Cloud Logging alerting (P2 alert threshold).
        logger.exception(
            "HIPAA audit log write failed",
            extra={
                "user_id": str(user_id) if user_id else None,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "endpoint": endpoint,
                # ip_address intentionally omitted from error log (PII)
            },
        )


class HIPAAAuditMiddleware(BaseHTTPMiddleware):
    """Starlette/FastAPI middleware that writes an audit record for every
    request targeting a PHI endpoint.

    Must be added to the FastAPI app AFTER the JWT validation middleware
    so that ``request.state.user_id`` is populated by the time this
    middleware reads it.

    Usage in ``backend/app/main.py``:

        app.add_middleware(HIPAAAuditMiddleware)

    The middleware is idempotent — if ``request.state.user_id`` is absent
    (unauthenticated request that somehow reached this layer), ``user_id``
    is recorded as ``None`` to capture the access attempt without masking it.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        path = request.url.path
        if not _is_phi_endpoint(path):
            return response

        # Extract user identity set by JWT middleware
        user_id: uuid.UUID | None = getattr(request.state, "user_id", None)
        action = _METHOD_ACTION.get(request.method, "READ")
        entity_type, entity_id = _extract_entity_info(path)

        # Client IP — respect X-Forwarded-For set by Cloud Load Balancer
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            # Take the first (leftmost) IP — the original client
            ip_address = forwarded_for.split(",")[0].strip()
        else:
            ip_address = request.client.host if request.client else None

        # Fire-and-forget background write — does not affect response latency
        background = BackgroundTasks()
        background.add_task(
            _write_audit_record,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            ip_address=ip_address,
            endpoint=path,
        )
        response.background = background

        return response
```

### 4. Register Middleware in `backend/app/main.py`

Add the middleware to the FastAPI application. Middleware is applied in reverse order of `add_middleware` calls — the last middleware added is the outermost. Add `HIPAAAuditMiddleware` **after** `JWTValidationMiddleware` so it is invoked inner (i.e., after JWT is validated):

```python
# In backend/app/main.py — middleware registration block
from app.middleware.audit import HIPAAAuditMiddleware
from app.middleware.jwt import JWTValidationMiddleware
from app.middleware.log_sanitiser import PHILogSanitiserMiddleware
from app.middleware.rate_limit import RateLimitMiddleware

# Order: outermost to innermost (each add_middleware wraps the previous)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(JWTValidationMiddleware)
app.add_middleware(PHILogSanitiserMiddleware)
app.add_middleware(HIPAAAuditMiddleware)  # innermost — runs after JWT is validated
```

### 5. Add Secret Manager Secret for `audit_writer` DB URL

The `audit_writer` role needs its own connection string. Add it to the `secrets` Terraform module (EP-TECH/US-001) as a new entry:

```hcl
# In infra/terraform/modules/secrets/main.tf — add to the locals.secrets map:
"audit-writer-db-url" = {}
```

This creates the secret placeholder `smarthandoff-audit-writer-db-url-<env>`. The actual value (PostgreSQL DSN with `audit_writer` credentials) is set post-deploy per the bootstrap runbook.

---

## Files Affected

| File | Action |
|---|---|
| `backend/app/db/audit_session.py` | Create |
| `backend/app/models/audit_log.py` | Create |
| `backend/app/middleware/audit.py` | Create |
| `backend/app/main.py` | Add middleware registration |
| `infra/terraform/modules/secrets/main.tf` | Add `audit-writer-db-url` secret entry |

---

## Definition of Done

- [ ] `HIPAAAuditMiddleware` registered in `main.py` in the correct middleware order
- [ ] Requests to all PHI endpoint prefixes produce an `audit_log` row with correct `user_id`, `action`, `entity_type`, `entity_id`, `ip_address`, and `created_at`
- [ ] Requests to `/health`, `/ready`, `/metrics`, `/docs` do NOT produce `audit_log` rows
- [ ] PHI field values (patient name, DOB, MRN) are NOT present in any `audit_log` column
- [ ] `audit_writer` DB URL secret placeholder added to Terraform secrets module
- [ ] Audit write failure does NOT cause the primary API response to fail (background task pattern confirmed)
