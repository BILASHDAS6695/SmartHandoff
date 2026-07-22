---
id: TASK-002
title: "Implement `AuditLogMiddleware` — FastAPI PHI Access Interceptor"
user_story: US-058
epic: EP-011
sprint: 1
layer: Backend
estimate: 2h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-058/TASK-001, US-056/TASK-004]
---

# TASK-002: Implement `AuditLogMiddleware` — FastAPI PHI Access Interceptor

> **Story:** US-058 | **Epic:** EP-011 | **Sprint:** 1 | **Layer:** Backend | **Est:** 2 h
> **Status:** Done | **Date:** 2026-07-15

---

## Context

This task implements `AuditLogMiddleware`, the Starlette-compatible FastAPI middleware (stack position 7 per design.md §3.3) that intercepts every request to a PHI-bearing path under `/api/v1/` and writes an `audit_log` entry **after** the response is dispatched.

The middleware:
1. Runs **after** the JWT Validator (position 4) and RBAC Enforcer (position 5) — `request.state.current_user` is populated by the time this middleware executes.
2. Uses the IP-extraction helper (supporting `X-Forwarded-For` for Cloud Run proxy chains) per US-058 DoD.
3. Derives `entity_type` and `entity_id` from the URL path pattern.
4. Fires `write_audit_entry()` (TASK-001) after the response is sent — non-blocking; errors absorbed without impacting the caller.

The middleware only logs requests that match **PHI entity paths** (defined via a configurable prefix list). Non-PHI paths (`/health`, `/ready`, `/metrics`, `/api/v1/auth/*`) are excluded.

---

## Acceptance Criteria Addressed

| US-058 AC | Requirement |
|---|---|
| **Scenario 1** | `GET /api/v1/patients/{id}` → `audit_log` entry with `action=READ`, `entity_type=PATIENT`, `entity_id={id}`, `user_id`, `ip_address`, `timestamp=UTC` |
| **Scenario 2** | `PATCH /api/v1/documents/{id}/approve` → `audit_log` entry with `action=APPROVE`, `entity_type=DOCUMENT`, `entity_id={id}` |
| **DoD** | `AuditLogMiddleware`: logs every request to PHI entity paths; IP from `X-Forwarded-For` (Cloud Run proxy-aware) |

---

## Implementation Steps

### 1. Create `backend/app/middleware/audit_log_middleware.py`

```python
"""AuditLogMiddleware — PHI access audit interceptor for SmartHandoff.

Runs at position 7 in the FastAPI middleware stack (design.md §3.3).
Intercepts every request to a PHI entity path after routing is complete,
extracts user identity from request.state.current_user (set by JWT
middleware at position 4), and writes an append-only audit_log entry.

PHI path matching:
    Only paths that expose PHI entity data are audited. Auth, health, and
    metrics paths are explicitly excluded (see _PHI_PATH_PREFIXES and
    _EXCLUDED_PATH_PREFIXES).

Action mapping:
    HTTP method → AuditAction enum value for standard CRUD.
    Special path suffixes (/approve, /reject, /resolve) override the
    default method mapping.

IP extraction:
    Cloud Run sits behind a Google-managed load balancer. The real client
    IP is in the X-Forwarded-For header. The first non-RFC-1918 IP in
    the chain is used. Falls back to request.client.host.

Design refs:
    design.md §3.3 middleware stack position 7
    design.md §8.4 PHI Protection Layers
    SEC-006, BR-023, US-058
"""
from __future__ import annotations

import logging
import re
import uuid
from ipaddress import AddressValueError, ip_address
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.db.audit import write_audit_entry
from app.db.session import get_audit_db_session
from app.models.audit_log import AuditAction

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# PHI entity paths that must be audited. Pattern: /api/v1/{entity}[/{id}[/...]]
_PHI_PATH_PREFIXES: tuple[str, ...] = (
    "/api/v1/patients",
    "/api/v1/encounters",
    "/api/v1/documents",
    "/api/v1/medications",
    "/api/v1/alerts",
    "/api/v1/beds",
    "/api/v1/tasks",
    "/api/v1/admin/audit",
    "/api/v1/admin/users",
)

# Paths that are never audited even if they match a PHI prefix.
_EXCLUDED_PATH_PREFIXES: tuple[str, ...] = (
    "/api/v1/auth",
    "/health",
    "/ready",
    "/metrics",
    "/docs",
    "/openapi.json",
    "/hubs",
    "/webhooks",
)

# Path suffix → AuditAction override. Checked before HTTP method mapping.
_SUFFIX_ACTION_MAP: dict[str, AuditAction] = {
    "/approve": AuditAction.APPROVE,
    "/reject":  AuditAction.REJECT,
    "/resolve": AuditAction.RESOLVE,
}

# HTTP method → default AuditAction
_METHOD_ACTION_MAP: dict[str, AuditAction] = {
    "GET":    AuditAction.READ,
    "HEAD":   AuditAction.READ,
    "POST":   AuditAction.WRITE,
    "PUT":    AuditAction.WRITE,
    "PATCH":  AuditAction.WRITE,
    "DELETE": AuditAction.DELETE,
}

# Regex: extracts entity_type and entity_id from path
# Matches: /api/v1/{entity}/{uuid}[/anything]
_ENTITY_PATH_RE = re.compile(
    r"^/api/v\d+/(?:admin/)?(?P<entity>[a-z_]+)"
    r"(?:/(?P<entity_id>[0-9a-f-]{36}))?",
    re.IGNORECASE,
)

# RFC-1918 private prefixes used to skip internal IPs in XFF chain
_PRIVATE_PREFIXES = ("10.", "172.16.", "172.17.", "172.18.", "172.19.",
                     "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
                     "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
                     "172.30.", "172.31.", "192.168.", "127.", "::1")


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _should_audit(path: str) -> bool:
    """Return True if this path requires an audit log entry."""
    for excluded in _EXCLUDED_PATH_PREFIXES:
        if path.startswith(excluded):
            return False
    for phi in _PHI_PATH_PREFIXES:
        if path.startswith(phi):
            return True
    return False


def _extract_entity(path: str) -> tuple[str, Optional[uuid.UUID]]:
    """Parse the entity_type (uppercase) and optional entity_id from path."""
    match = _ENTITY_PATH_RE.match(path)
    if not match:
        return ("UNKNOWN", None)
    entity_type = match.group("entity").upper().rstrip("S")  # patients→PATIENT
    raw_id = match.group("entity_id")
    entity_id: Optional[uuid.UUID] = None
    if raw_id:
        try:
            entity_id = uuid.UUID(raw_id)
        except ValueError:
            pass
    return (entity_type, entity_id)


def _extract_action(path: str, method: str) -> AuditAction:
    """Determine AuditAction from path suffix (priority) or HTTP method."""
    path_lower = path.lower()
    for suffix, action in _SUFFIX_ACTION_MAP.items():
        if path_lower.endswith(suffix):
            return action
    return _METHOD_ACTION_MAP.get(method.upper(), AuditAction.READ)


def _extract_ip(request: Request) -> Optional[str]:
    """Extract the real client IP, preferring X-Forwarded-For over remote addr.

    Cloud Run inserts the original client IP as the first entry in
    X-Forwarded-For. We skip RFC-1918 addresses to find the public IP.
    Falls back to request.client.host if no public IP is found in the chain.
    """
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        for candidate in (ip.strip() for ip in xff.split(",")):
            if not any(candidate.startswith(p) for p in _PRIVATE_PREFIXES):
                try:
                    ip_address(candidate)  # validate format
                    return candidate
                except (AddressValueError, ValueError):
                    continue
    if request.client:
        return request.client.host
    return None


# ---------------------------------------------------------------------------
# Middleware class
# ---------------------------------------------------------------------------

class AuditLogMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that writes PHI access records to audit_log.

    Must be registered AFTER the JWT validation middleware so that
    request.state.current_user is populated before this middleware runs.

    Registration in main.py (after JWT middleware):
        app.add_middleware(PhiLogSanitiserMiddleware)  # position 6
        app.add_middleware(AuditLogMiddleware)          # position 7
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        if not _should_audit(request.url.path):
            return response

        # Fire-and-forget audit write after response is dispatched
        try:
            user = getattr(request.state, "current_user", None)
            user_id: Optional[uuid.UUID] = (
                uuid.UUID(str(user.sub)) if user and hasattr(user, "sub") else None
            )

            entity_type, entity_id = _extract_entity(request.url.path)
            action = _extract_action(request.url.path, request.method)
            ip = _extract_ip(request)
            ua = request.headers.get("User-Agent")

            async with get_audit_db_session() as db:
                await write_audit_entry(
                    db=db,
                    user_id=user_id,
                    action=action,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    ip_address=ip,
                    user_agent=ua,
                )
        except Exception as exc:  # noqa: BLE001
            # Audit failure must never break the response
            logger.error(
                "AuditLogMiddleware unhandled error",
                extra={"event": "audit_middleware_error", "error": str(exc)},
            )

        return response
```

> **Note on `AuditAction.RESOLVE`:** The `RESOLVE` action is used by RBAC events (US-057) but is not a top-level `AuditAction` in US-058 DoD. If the enum defined in TASK-001 does not include `RESOLVE`, use `WRITE` as the fallback action for resolve-suffix paths and add a comment.

### 2. Register middleware in `backend/app/main.py`

Add after the JWT validation middleware:

```python
from app.middleware.audit_log_middleware import AuditLogMiddleware
from app.middleware.phi_log_sanitiser import PhiLogSanitiserMiddleware  # TASK-003

# ... existing middleware registrations ...
app.add_middleware(PhiLogSanitiserMiddleware)   # position 6
app.add_middleware(AuditLogMiddleware)           # position 7
```

> **Ordering matters.** Starlette `add_middleware` wraps in reverse order — the last-added middleware runs first on requests, last on responses. Ensure the JWT middleware is added **before** `AuditLogMiddleware` so `request.state.current_user` is set.

### 3. Create `backend/app/db/session.py` — `get_audit_db_session` context manager

If not already present, add an async context manager that yields an `AsyncSession` bound to the `audit_writer` PostgreSQL role:

```python
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
import os

_AUDIT_DB_URL = os.environ["AUDIT_DB_URL"]  # separate connection string for audit_writer role
_audit_engine = create_async_engine(_AUDIT_DB_URL, pool_size=5, max_overflow=2)
_AuditSessionLocal = async_sessionmaker(_audit_engine, expire_on_commit=False)

@asynccontextmanager
async def get_audit_db_session() -> AsyncSession:
    async with _AuditSessionLocal() as session:
        yield session
```

The `AUDIT_DB_URL` secret must be provisioned in GCP Secret Manager and mounted as a Cloud Run env var (separate from the main `DATABASE_URL` which uses `app_write` role).

---

## Validation

```python
# Smoke test: middleware path matching
from app.middleware.audit_log_middleware import _should_audit, _extract_entity, _extract_action
from app.models.audit_log import AuditAction

assert _should_audit("/api/v1/patients/abc123") is True
assert _should_audit("/api/v1/auth/token") is False
assert _should_audit("/health") is False

entity_type, entity_id = _extract_entity("/api/v1/patients/550e8400-e29b-41d4-a716-446655440000")
assert entity_type == "PATIENT"
assert str(entity_id) == "550e8400-e29b-41d4-a716-446655440000"

assert _extract_action("/api/v1/documents/abc/approve", "PATCH") == AuditAction.APPROVE
assert _extract_action("/api/v1/patients/abc", "GET") == AuditAction.READ
print("All smoke tests passed")
```

---

## Files Touched

| File | Action |
|---|---|
| `backend/app/middleware/audit_log_middleware.py` | Create — `AuditLogMiddleware` + path/action helpers |
| `backend/app/main.py` | Update — register `AuditLogMiddleware` at position 7 |
| `backend/app/db/session.py` | Update — add `get_audit_db_session()` context manager |

---

## Definition of Done Checklist

- [ ] `AuditLogMiddleware` registered in `main.py` after JWT middleware
- [ ] All PHI entity path prefixes covered; `/auth`, `/health`, `/ready` excluded
- [ ] IP extraction handles `X-Forwarded-For` (Cloud Run proxy chain)
- [ ] Action correctly mapped: GET→READ, POST/PATCH/PUT→WRITE, DELETE→DELETE, `/approve`→APPROVE, `/reject`→REJECT
- [ ] Audit write errors absorbed — never propagate to HTTP response
- [ ] `get_audit_db_session()` uses `AUDIT_DB_URL` env var (separate `audit_writer` DB role)
