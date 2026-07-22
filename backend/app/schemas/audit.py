"""Pydantic response schemas for the audit log query API (US-058/TASK-004).

Two schemas:
  - AuditLogEntryFull:    returned to ADMIN role (includes ip_address, user_agent)
  - AuditLogEntrySummary: returned to other roles (entity info + timestamp only)

Note: PHI field values are NEVER stored in audit_log — these schemas are safe
to return as-is; masking only applies to ip_address and user_agent.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AuditLogEntrySummary(BaseModel):
    """Minimal audit log entry for non-admin roles."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    action: str
    resource_type: str
    resource_id: str
    created_at: datetime


class AuditLogEntryFull(AuditLogEntrySummary):
    """Full audit log entry for ADMIN / compliance roles.

    Extends the summary with ip_address, user_agent, user_id, and user_role.
    """

    user_id: Optional[uuid.UUID] = None
    user_role: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    endpoint: Optional[str] = None


class AuditLogPage(BaseModel):
    """Paginated response envelope for audit log queries."""

    items: list[AuditLogEntryFull | AuditLogEntrySummary]
    total: int = Field(description="Total matching records (for pagination UI)")
    page: int
    page_size: int
    pages: int
