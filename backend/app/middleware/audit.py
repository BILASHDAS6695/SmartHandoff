"""HIPAA audit logging middleware (US-058/TASK-002).

Intercepts all requests to PHI endpoints and writes an immutable record
to audit_log via the audit_writer PostgreSQL role.

Key constraints (US-008 Technical Notes):
- PHI field values (name, DOB, MRN, phone, email) are NEVER written to audit_log
- Audit write is a BackgroundTask — does not block the primary HTTP response
- Audit write failures are logged to Cloud Logging but do NOT surface as 5xx
- user_id is extracted from request.state (set by JWT validation middleware)

Request lifecycle position:
  Cloud Armor → TLS → Rate Limiter → JWT Validator → RBAC →
  PHI Log Sanitiser → HIPAA Audit Logger ← this middleware → Route Handler

US-058 enhancements:
  - user_agent captured from User-Agent header
  - Action suffix overrides: /approve → approve, /reject → reject, /resolve → resolve
  - Extended PHI prefixes: /alerts, /beds, /tasks added
  - X-Forwarded-For: first non-RFC-1918 IP used (Cloud Run proxy-aware)
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from ipaddress import AddressValueError, ip_address as parse_ip
from typing import Optional

from fastapi import BackgroundTasks, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.db.audit import write_audit_entry

logger = logging.getLogger(__name__)

# ── PHI endpoint prefixes that must be audited ────────────────────────────────
_PHI_PREFIXES: tuple[str, ...] = (
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

# ── HTTP method → audit action mapping ───────────────────────────────────────
_METHOD_ACTION: dict[str, str] = {
    "GET": "read",
    "HEAD": "read",
    "POST": "create",
    "PUT": "update",
    "PATCH": "update",
    "DELETE": "delete",
}

# ── Path suffix → action override (checked before method mapping) ─────────────
_SUFFIX_ACTION: dict[str, str] = {
    "/approve": "approve",
    "/reject": "reject",
    "/resolve": "resolve",
}

# ── Endpoints explicitly excluded from auditing ───────────────────────────────
_EXCLUDED_PATHS: frozenset[str] = frozenset(
    {"/health", "/ready", "/metrics", "/docs", "/openapi.json", "/favicon.ico"}
)

# ── Resource name mapping (URL segment → singular entity name) ───────────────
_RESOURCE_MAP: dict[str, str] = {
    "patients": "patient",
    "encounters": "encounter",
    "documents": "document",
    "medications": "medication",
    "alerts": "alert",
    "beds": "bed",
    "tasks": "agent_task",
    "users": "user",
    "audit": "audit_log",
}

# RFC-1918 private prefixes — skipped when resolving real client IP from XFF
_PRIVATE_PREFIXES = (
    "10.", "172.16.", "172.17.", "172.18.", "172.19.", "172.20.", "172.21.",
    "172.22.", "172.23.", "172.24.", "172.25.", "172.26.", "172.27.", "172.28.",
    "172.29.", "172.30.", "172.31.", "192.168.", "127.", "::1",
)


def _is_phi_endpoint(path: str) -> bool:
    """Return True if the request path targets a PHI-scoped endpoint."""
    if path in _EXCLUDED_PATHS:
        return False
    return any(path.startswith(prefix) for prefix in _PHI_PREFIXES)


def _extract_resource_info(path: str) -> tuple[str, str]:
    """Derive resource_type and resource_id from the URL path.

    Examples:
      /api/v1/patients/abc-123          → ("patient", "abc-123")
      /api/v1/encounters/xyz/documents  → ("encounter", "xyz")
      /api/v1/medications               → ("medication", "collection")
    """
    segments = [s for s in path.split("/") if s]
    # Expected structure: ["api", "v1", "<resource>", "<id>", ...]
    resource_type = "unknown"
    resource_id = "collection"

    if len(segments) >= 3:
        resource_type = _RESOURCE_MAP.get(segments[2], segments[2].rstrip("s"))
    if len(segments) >= 4:
        candidate = segments[3]
        # Use as resource_id only if it is not itself a resource segment
        if len(candidate) <= 128 and candidate not in _RESOURCE_MAP:
            resource_id = candidate

    return resource_type, resource_id


def _extract_action(path: str, method: str) -> str:
    """Determine audit action from path suffix (priority) or HTTP method.

    Path suffix overrides take priority — PATCH /documents/abc/approve → "approve".
    """
    path_lower = path.lower()
    for suffix, action in _SUFFIX_ACTION.items():
        if path_lower.endswith(suffix):
            return action
    return _METHOD_ACTION.get(method.upper(), "read")


def _extract_ip(request: Request) -> Optional[str]:
    """Extract the real client IP, preferring X-Forwarded-For over remote addr.

    Cloud Run sits behind Google's managed load balancer which inserts the
    original client IP as the first entry in X-Forwarded-For.  We skip
    RFC-1918 addresses to find the first public IP in the chain.
    Falls back to request.client.host if no public IP found.
    """
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        for candidate in (ip.strip() for ip in xff.split(",")):
            if not any(candidate.startswith(p) for p in _PRIVATE_PREFIXES):
                try:
                    parse_ip(candidate)
                    return candidate
                except (AddressValueError, ValueError):
                    continue
    if request.client:
        return request.client.host
    return None


async def _write_audit_record(
    user_id: uuid.UUID | None,
    user_role: str | None,
    action: str,
    resource_type: str,
    resource_id: str,
    ip_address: str | None,
    user_agent: str | None,
    endpoint: str | None,
    request_id: str | None,
) -> None:
    """Persist one audit_log row via the audit_writer session (BackgroundTask).

    Any exception is caught and logged — must NOT propagate to the ASGI layer.
    PHI field values are never passed to this function.
    """
    await write_audit_entry(
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        user_id=user_id,
        user_role=user_role,
        ip_address=ip_address,
        user_agent=user_agent,
        endpoint=endpoint,
        request_id=request_id,
    )


class HIPAAAuditMiddleware(BaseHTTPMiddleware):
    """Starlette/FastAPI middleware that writes an audit record for every
    request targeting a PHI endpoint.

    Must be registered AFTER the JWT validation middleware so that
    ``request.state.user_id`` is already populated when this middleware runs.

    Usage in ``backend/app/main.py``::

        app.add_middleware(HIPAAAuditMiddleware)

    The middleware is idempotent — if ``request.state.user_id`` is absent
    (unauthenticated request), ``user_id`` is recorded as ``None`` to
    capture the access attempt without masking it.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        path = request.url.path
        if not _is_phi_endpoint(path):
            return response

        # Extract user identity set by JWT validation middleware
        user_id: uuid.UUID | None = getattr(request.state, "user_id", None)
        user_role: str | None = getattr(request.state, "user_role", None)
        action = _extract_action(path, request.method)
        resource_type, resource_id = _extract_resource_info(path)
        ip_address = _extract_ip(request)
        user_agent: str | None = request.headers.get("User-Agent")

        # Distributed trace ID for correlation with Cloud Logging
        request_id: str | None = request.headers.get("x-cloud-trace-context")

        # Fire-and-forget background write — does not add latency to response
        background = BackgroundTasks()
        background.add_task(
            _write_audit_record,
            user_id=user_id,
            user_role=user_role,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip_address,
            user_agent=user_agent,
            endpoint=path,
            request_id=request_id,
        )
        response.background = background

        return response
