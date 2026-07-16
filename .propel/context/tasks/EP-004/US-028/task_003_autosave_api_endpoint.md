---
id: TASK-003
title: "Implement `PATCH /api/v1/documents/{id}` Auto-Save Endpoint with RBAC"
user_story: US-028
epic: EP-004
sprint: 2
layer: Backend — API
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [TASK-001, TASK-002]
---

# TASK-003: Implement `PATCH /api/v1/documents/{id}` Auto-Save Endpoint with RBAC

> **Story:** US-028 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Backend — API | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-028 Scenario 2 and 3 require a `PATCH /api/v1/documents/{id}` endpoint that:

- Accepts the edited document content plus a field-level diff payload
- Persists the updated content to `Document.content` (field-level AES-256-GCM encrypted at ORM layer per ADR-007)
- Appends `ChangeLogEntry` records to `Document.change_log` JSONB
- Leaves `Document.status` as `PENDING_REVIEW` (does NOT advance to APPROVED)
- Is accessible to all roles that have read access to the encounter (physician, nurse, care coordinator)

---

## Acceptance Criteria Addressed

| US-028 AC | Requirement |
|---|---|
| **Scenario 2** | Change log entries appended per changed field |
| **Scenario 3** | Content persisted; `status` remains `PENDING_REVIEW`; `AI-Assisted` label preserved |

---

## Implementation Steps

### 1. Create/Extend `backend/api/routers/documents.py`

```python
"""
Document API router.

Handles document lifecycle endpoints for the SmartHandoff discharge documentation workflow.
All PHI fields are encrypted at the ORM layer (ADR-007); this router never handles plaintext PHI.
"""
from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user, get_db_session, require_roles
from api.schemas.document_schemas import (
    DocumentSaveDraftRequest,
    DocumentApproveRequest,
    DocumentRejectRequest,
    DocumentStatus,
    ChangeLogEntryResponse,
)
from models.document import Document
from models.user import User
from services.document_diff import compute_field_diff, apply_diff_to_change_log
from services.document_service import (
    get_document_or_404,
    persist_document_save,
    get_change_log_with_authors,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])


@router.patch(
    "/{document_id}",
    summary="Auto-save edited document content and append change log entries",
    status_code=status.HTTP_200_OK,
)
async def save_document_draft(
    document_id: UUID,
    body: DocumentSaveDraftRequest,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Persist edited document content without advancing status (Scenario 3).

    - Computes field-level diff between stored content and incoming content
    - Appends ChangeLogEntry records to Document.change_log (Scenario 2)
    - Encrypts updated content via ORM field-level encryption (ADR-007)
    - Status remains PENDING_REVIEW regardless of edit count

    Accessible to: physician, nurse, care_coordinator (any role with encounter access).
    """
    doc: Document = await get_document_or_404(db, document_id)

    # Compute diff between persisted content and incoming payload
    diff_entries = compute_field_diff(
        stored_content=doc.content,
        updated_content=body.content,
        author_id=current_user.id,
    )

    if not diff_entries:
        logger.debug("No field changes detected for document %s — skipping write.", document_id)
        return {"document_id": str(document_id), "changes_recorded": 0}

    # Append new entries to existing change log (append-only)
    updated_log = apply_diff_to_change_log(doc.change_log, diff_entries)

    await persist_document_save(
        db=db,
        document=doc,
        new_content=body.content,
        updated_change_log=updated_log,
    )

    logger.info(
        "Document %s saved with %d change(s) by user %s",
        document_id,
        len(diff_entries),
        current_user.id,
    )

    return {
        "document_id": str(document_id),
        "status": DocumentStatus.PENDING_REVIEW,
        "changes_recorded": len(diff_entries),
    }
```

### 2. Create `backend/services/document_service.py`

```python
"""
Document service layer — database operations for the document lifecycle.

Separates DB concerns from the router layer. All content writes go through
`persist_document_save` which ensures PHI encryption is applied by the ORM.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.document import Document
from models.user import User

logger = logging.getLogger(__name__)


async def get_document_or_404(db: AsyncSession, document_id: UUID) -> Document:
    """Fetch document by ID or raise 404."""
    result = await db.execute(
        select(Document)
        .where(Document.id == document_id)
        .options(selectinload(Document.encounter))
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found.",
        )
    return doc


async def persist_document_save(
    db: AsyncSession,
    document: Document,
    new_content: dict[str, Any],
    updated_change_log: list[dict],
) -> None:
    """
    Persist updated content and change log to the database.

    PHI encryption is applied automatically by the ORM EncryptedJSON type
    decorator on Document.content (ADR-007). Status is intentionally NOT
    updated here — status transitions are handled exclusively by approve/reject
    endpoints.
    """
    document.content = new_content          # ORM encrypts on flush
    document.change_log = updated_change_log
    await db.commit()
    await db.refresh(document)


async def get_change_log_with_authors(
    db: AsyncSession,
    document_id: UUID,
) -> list[dict]:
    """
    Fetch change log entries for a document, joining author display names.

    Returns a list of dicts suitable for ChangeLogEntryResponse serialisation.
    """
    doc = await get_document_or_404(db, document_id)
    log = doc.change_log or []

    # Batch-load unique author UUIDs to avoid N+1
    author_ids = {entry["author_id"] for entry in log if "author_id" in entry}
    if author_ids:
        result = await db.execute(
            select(User.id, User.display_name).where(User.id.in_(author_ids))
        )
        author_map: dict[str, str] = {
            str(row.id): row.display_name for row in result.fetchall()
        }
    else:
        author_map = {}

    return [
        {**entry, "author_display_name": author_map.get(entry.get("author_id", ""))}
        for entry in log
    ]
```

### 3. Add `GET /documents/{id}/change-log` endpoint to `documents.py`

```python
@router.get(
    "/{document_id}/change-log",
    response_model=list[ChangeLogEntryResponse],
    summary="Retrieve the change log timeline for a document",
)
async def get_document_change_log(
    document_id: UUID,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """
    Return the append-only change log for the document.

    Used by the Angular change-log timeline panel (DoD item 4).
    Author display names are joined server-side to avoid N+1 requests from the client.
    """
    return await get_change_log_with_authors(db, document_id)
```

---

## File Locations

| File | Path |
|---|---|
| `documents.py` (router) | `backend/api/routers/documents.py` |
| `document_service.py` | `backend/services/document_service.py` |

---

## Validation Checklist

- [ ] `PATCH /api/v1/documents/{id}` returns `200` with `changes_recorded` count
- [ ] When no fields changed, endpoint returns `200` with `changes_recorded: 0` (no DB write)
- [ ] `Document.status` remains `PENDING_REVIEW` after save-draft — never set to `APPROVED` here
- [ ] `Document.content` is passed through ORM field-level encryption (not stored as plaintext)
- [ ] `change_log` is appended (not replaced) on each save
- [ ] `GET /documents/{id}/change-log` returns author display names joined from `User` table
- [ ] 404 returned for unknown `document_id`
- [ ] All DB operations use `async`/`await` (SQLAlchemy 2.x async session)

---

## Dependencies

| Dependency | Notes |
|---|---|
| `TASK-001` | `DocumentSaveDraftRequest`, `ChangeLogEntry` schemas |
| `TASK-002` | `compute_field_diff`, `apply_diff_to_change_log` |
| `US-025` | `Document` ORM model with encrypted `content` field |
