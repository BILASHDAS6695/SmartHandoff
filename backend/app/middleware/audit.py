"""HIPAA audit logging middleware.

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
    "GET": "read",
    "HEAD": "read",
    "POST": "create",
    "PUT": "update",
    "PATCH": "update",
    "DELETE": "delete",
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
    "users": "user",
    "audit": "audit_log",
}


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


async def _write_audit_record(
    user_id: uuid.UUID | None,
    user_role: str | None,
    action: str,
    resource_type: str,
    resource_id: str,
    ip_address: str | None,
    endpoint: str | None,
    request_id: str | None,
) -> None:
    """Persist one audit_log row via the audit_writer session.

    This coroutine runs as a BackgroundTask. Any exception is caught and
    logged — it must NOT propagate to the ASGI layer.

    Security: PHI field values are never passed to this function.
    Only opaque identifiers (UUIDs, resource type strings) are logged.
    """
    try:
        factory = get_audit_session_factory()
        async with factory() as session:
            record = AuditLog(
                id=uuid.uuid4(),
                user_id=user_id,
                user_role=user_role,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                ip_address=ip_address,
                endpoint=endpoint,
                request_id=request_id,
                outcome="success",
            )
            session.add(record)
            await session.commit()
    except Exception:
        # Audit write failure is NOT surfaced to the client.
        # Cloud Logging alert fires on this log pattern (P2 threshold).
        logger.exception(
            "HIPAA audit log write failed",
            extra={
                "user_id": str(user_id) if user_id else None,
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "endpoint": endpoint,
                # ip_address intentionally omitted from error log (PII)
            },
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
        action = _METHOD_ACTION.get(request.method, "read")
        resource_type, resource_id = _extract_resource_info(path)

        # Client IP — respect X-Forwarded-For set by Cloud Load Balancer.
        # Take the first (leftmost) IP — the original client, not a proxy.
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            ip_address = forwarded_for.split(",")[0].strip()
        else:
            ip_address = request.client.host if request.client else None

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
            endpoint=path,
            request_id=request_id,
        )
        response.background = background

        return response
