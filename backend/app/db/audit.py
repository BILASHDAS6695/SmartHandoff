"""Database write helpers for the audit_log table (US-058).

All writes use the ``audit_writer`` database role (US-008/TASK-001) which has
INSERT-only permission on audit_log.  This file is the sole write path —
no other module inserts to audit_log directly.

write_audit_entry      — called by AuditLogMiddleware (US-058/TASK-002).
write_rbac_audit_entry — called by app/core/auth/rbac.py (US-057/TASK-002).

Design refs:
    design.md §6.1 DR-003 — Audit log immutability
    design.md §8.4         — PHI Protection Layers
    SEC-006, BR-023         — Audit requirements
    US-008                  — Table + RLS provisioning
    US-058                  — This story
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from app.db.audit_session import get_audit_session_factory
from app.models.audit_log import AuditAction, AuditLog

logger = logging.getLogger(__name__)


async def write_audit_entry(
    *,
    action: AuditAction | str,
    resource_type: str,
    resource_id: str = "collection",
    user_id: Optional[str | uuid.UUID] = None,
    user_role: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    endpoint: Optional[str] = None,
    request_id: Optional[str] = None,
) -> None:
    """Insert one row into audit_log via the audit_writer role.

    Silently absorbs database errors to ensure audit failures never block
    the primary request.  Errors are emitted to Cloud Logging at ERROR
    severity without PHI values.

    Args:
        action:        AuditAction enum member or its string value.
        resource_type: Lowercase resource name, e.g. ``"patient"``.
        resource_id:   String PK of the entity; ``"collection"`` for list endpoints.
        user_id:       JWT ``sub`` claim (str UUID); None for unauthenticated paths.
        user_role:     JWT ``role`` claim; optional.
        ip_address:    Caller IP (IPv4 or IPv6, max 45 chars).
        user_agent:    Value of ``User-Agent`` request header.
        endpoint:      Request URL path, e.g. ``/api/v1/patients/abc-123``.
        request_id:    Cloud Trace ID for log correlation.
    """
    if isinstance(action, AuditAction):
        action_str = action.value
    else:
        action_str = str(action)

    resolved_user_id: Optional[uuid.UUID] = None
    if user_id is not None:
        try:
            resolved_user_id = uuid.UUID(str(user_id))
        except ValueError:
            pass

    try:
        factory = get_audit_session_factory()
        async with factory() as session:
            entry = AuditLog(
                id=uuid.uuid4(),
                user_id=resolved_user_id,
                user_role=user_role,
                action=action_str,
                resource_type=resource_type,
                resource_id=str(resource_id)[:128],
                ip_address=ip_address,
                user_agent=user_agent,
                endpoint=endpoint,
                request_id=request_id,
                outcome="success",
            )
            session.add(entry)
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        # Audit write failure must never block the primary response.
        logger.error(
            "audit_log write failed",
            extra={
                "event": "audit_write_failure",
                "resource_type": resource_type,
                "action": action_str,
                "error": str(exc),
            },
        )


async def write_rbac_audit_entry(
    *,
    user_id: str,
    role: str,
    resource: str,
    action: str,
    granted: bool,
) -> None:
    """Write an RBAC permission check result to the audit log.

    Called by app/core/auth/rbac.py on every permission check (grant and denial).
    Maps RBAC vocabulary to the audit_log schema.

    Args:
        user_id:  JWT ``sub`` claim of the requesting user.
        role:     The user's assigned clinical role.
        resource: API resource being accessed (e.g. ``"alert"``).
        action:   Action attempted (e.g. ``"resolve"``).
        granted:  True if permission was granted; False if denied (403).
    """
    outcome_action = action if granted else f"denied:{action}"
    await write_audit_entry(
        action=outcome_action,
        resource_type=resource,
        resource_id="rbac_check",
        user_id=user_id,
        user_role=role,
        endpoint=f"/rbac/{resource}/{action}",
    )
