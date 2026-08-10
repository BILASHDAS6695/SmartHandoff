"""
HIPAA-compliant audit log writer.

Appends an immutable record to the `audit_log` table for every privileged action.
PHI is excluded from the metadata dict — only resource IDs and action names are stored.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


async def write_audit_log(
    db: AsyncSession,
    action: str,
    resource_type: str,
    resource_id: UUID,
    performed_by: UUID,
    metadata: dict[str, Any] | None = None,
) -> None:
    """
    Append an immutable audit log row (US-029 DoD, BR-001, SEC-006).

    This function must never raise — failures are caught and logged to
    Cloud Logging without bubbling up to the caller.

    Args:
        db:            Active async SQLAlchemy session (flushed, not committed).
        action:        Machine-readable action label, e.g. "DOCUMENT_APPROVED".
        resource_type: ORM entity name, e.g. "Document".
        resource_id:   UUID of the affected resource.
        performed_by:  UUID of the authenticated user performing the action.
        metadata:      Optional non-PHI supplementary context dict.
    """
    try:
        entry = AuditLog(
            user_id=performed_by,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id),
            outcome="SUCCESS",
            created_at=datetime.now(tz=timezone.utc),
        )
        db.add(entry)
        # Flushed (not committed) here; the caller's commit includes this row.
        await db.flush()
    except Exception as exc:  # noqa: BLE001
        # Roll back so the caller's session remains usable after a flush failure.
        await db.rollback()
        logger.error(
            "Failed to write audit log entry: action=%s resource_id=%s error=%s",
            action,
            resource_id,
            exc,
        )
