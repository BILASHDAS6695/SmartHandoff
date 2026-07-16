---
id: TASK-001
title: "Implement `ChangeLogEntry` Pydantic Schema and `Document.change_log` JSONB Migration"
user_story: US-028
epic: EP-004
sprint: 2
layer: Backend — Data Model
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-025, US-026]
---

# TASK-001: Implement `ChangeLogEntry` Pydantic Schema and `Document.change_log` JSONB Migration

> **Story:** US-028 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Backend — Data Model | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-028 Scenario 2 requires every clinician edit to produce a JSON diff entry appended to
`Document.metadata.change_log`. This task establishes:

1. The `ChangeLogEntry` Pydantic schema — the single source of truth for the diff record format
2. An Alembic migration adding `change_log` as a JSONB array column to the `document` table
3. The `DocumentStatus` enum update to expose `PENDING_REVIEW` and `APPROVED` / `REJECTED` states

These artefacts are consumed by TASK-002 (diff computation), TASK-003 (auto-save endpoint),
TASK-004 (approve/reject endpoints), and TASK-005 (Angular editor component).

---

## Acceptance Criteria Addressed

| US-028 AC | Requirement |
|---|---|
| **Scenario 2** | `ChangeLogEntry` fields: `field`, `old_value`, `new_value`, `author_id`, `timestamp` |
| **Scenario 3** | `DocumentStatus.PENDING_REVIEW` retained after save-draft |
| **Scenario 4** | `DocumentStatus` transitions controlled at API layer (TASK-004) |

---

## Implementation Steps

### 1. Create `backend/api/schemas/document_schemas.py` (extend if exists)

```python
"""
Pydantic schemas for Document API request/response contracts.

ChangeLogEntry is the canonical diff record format stored in
Document.metadata['change_log'] (JSONB). All fields are required to satisfy
HIPAA audit trail requirements (BR-001).
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class DocumentStatus(str, Enum):
    """Document lifecycle states (FR-024, US-028 Scenario 3 & 4)."""

    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ChangeLogEntry(BaseModel):
    """
    Single auditable change record appended to Document.metadata['change_log'].

    Produced by the diff engine on every auto-save (debounced 2 s, Scenario 2).
    Immutable once written — append-only semantics enforced at ORM layer.
    """

    field: str = Field(
        ...,
        description="Top-level section key that was changed, e.g. 'medications_at_discharge'.",
    )
    old_value: Any = Field(
        ...,
        description="Previous field value (string or nested object) before the edit.",
    )
    new_value: Any = Field(
        ...,
        description="New field value after the edit.",
    )
    author_id: UUID = Field(
        ...,
        description="UUID of the authenticated user who made the change.",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the change was recorded.",
    )

    model_config = {"frozen": True}  # Immutable once created


class DocumentSaveDraftRequest(BaseModel):
    """
    Request body for PATCH /api/v1/documents/{id} (auto-save / save-draft).

    `diff` contains only the fields that changed in this edit cycle.
    The backend appends one ChangeLogEntry per key in `diff`.
    """

    content: dict = Field(
        ...,
        description="Full updated document content (structured sections as JSON object).",
    )
    diff: dict[str, dict[str, Any]] = Field(
        ...,
        description=(
            "Field-level diff map: {field_name: {old_value: ..., new_value: ...}}. "
            "One ChangeLogEntry is written per key."
        ),
    )


class DocumentApproveRequest(BaseModel):
    """Request body for PATCH /api/v1/documents/{id}/approve."""

    notes: Optional[str] = Field(
        default=None,
        description="Optional physician notes recorded at approval time.",
        max_length=1000,
    )


class DocumentRejectRequest(BaseModel):
    """Request body for PATCH /api/v1/documents/{id}/reject (Scenario 4 — all reviewers)."""

    rejection_reason: str = Field(
        ...,
        description="Mandatory reason for rejection. Stored in Document.metadata.",
        min_length=10,
        max_length=2000,
    )


class ChangeLogEntryResponse(BaseModel):
    """Serialised ChangeLogEntry for API responses (change log timeline)."""

    field: str
    old_value: Any
    new_value: Any
    author_id: UUID
    timestamp: datetime
    author_display_name: Optional[str] = None  # Joined from User table at query time
```

### 2. Create Alembic Migration `backend/alembic/versions/0008_add_document_change_log.py`

```python
"""add document change_log and rejection_reason columns

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-16
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add change_log JSONB array column — default empty list
    op.add_column(
        "document",
        sa.Column(
            "change_log",
            JSONB,
            nullable=False,
            server_default="[]",
            comment="Append-only audit trail of field-level edits (US-028 Scenario 2).",
        ),
    )
    # Add rejection_reason text column — nullable (only set on REJECTED documents)
    op.add_column(
        "document",
        sa.Column(
            "rejection_reason",
            sa.Text,
            nullable=True,
            comment="Mandatory reason provided when a document is rejected (US-028 Scenario 4).",
        ),
    )
    # Ensure status column covers all new enum values
    op.execute(
        "ALTER TYPE documentstatus ADD VALUE IF NOT EXISTS 'REJECTED';"
    )


def downgrade() -> None:
    op.drop_column("document", "rejection_reason")
    op.drop_column("document", "change_log")
```

### 3. Update `Document` SQLAlchemy ORM Model

Locate `backend/models/document.py` and add the two new columns:

```python
from sqlalchemy.dialects.postgresql import JSONB

# Inside Document model class — append after existing columns:
change_log: Mapped[list[dict]] = mapped_column(
    JSONB,
    nullable=False,
    default=list,
    server_default="[]",
    comment="Append-only change audit trail (US-028).",
)
rejection_reason: Mapped[Optional[str]] = mapped_column(
    Text,
    nullable=True,
    comment="Rejection reason set when document status transitions to REJECTED.",
)
```

---

## File Locations

| File | Path |
|---|---|
| `document_schemas.py` | `backend/api/schemas/document_schemas.py` |
| Alembic migration | `backend/alembic/versions/0008_add_document_change_log.py` |
| ORM model update | `backend/models/document.py` |

---

## Validation Checklist

- [ ] `ChangeLogEntry` has exactly 5 required fields: `field`, `old_value`, `new_value`, `author_id`, `timestamp`
- [ ] `ChangeLogEntry.model_config = {"frozen": True}` prevents mutation after creation
- [ ] `DocumentStatus` enum includes `PENDING_REVIEW`, `APPROVED`, `REJECTED`, `DRAFT`
- [ ] `DocumentSaveDraftRequest.diff` accepts arbitrary JSON values (not just strings)
- [ ] `DocumentRejectRequest.rejection_reason` has `min_length=10` to prevent empty reasons
- [ ] Alembic migration `up` adds both columns; `downgrade` removes both cleanly
- [ ] ORM model `change_log` defaults to `[]` — never `None`
- [ ] `rejection_reason` column is nullable (absent on non-rejected documents)

---

## Dependencies

| Dependency | Notes |
|---|---|
| `US-025` | `Document` model and `DocumentStatus` must already exist |
| `pydantic>=2.0` | `model_config = {"frozen": True}` requires Pydantic v2 |
| `alembic` | Migration must chain from the latest revision in the project |
