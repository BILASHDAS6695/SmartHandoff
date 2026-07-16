---
id: TASK-002
title: "Extend `PATCH /api/v1/documents/{id}/approve` — Set Audit Fields and Enforce `physician|advanced_practice` RBAC"
user_story: US-029
epic: EP-004
sprint: 2
layer: Backend — API
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [TASK-001, US-028/TASK-004]
---

# TASK-002: Extend Approve Endpoint — Audit Fields and Expanded RBAC

> **Story:** US-029 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Backend — API | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-028 TASK-004 implemented `PATCH /api/v1/documents/{id}/approve` restricted to the
`physician` role. US-029 extends this endpoint to:

1. **Widen RBAC** — also allow `advanced_practice` role (Scenario 4 DoD)
2. **Set `approved_at`** to current UTC timestamp (Scenario 4)
3. **Set `reviewed_by_user_id`** to the approving user's ID (Scenario 4)
4. **Preserve `ai_assisted_label=True`** — the field must NOT be reset on approval
5. **Write a HIPAA audit log entry** recording the approval action (DoD)

The existing `require_roles` dependency factory from US-028 TASK-004 is reused — only
the allowed-roles list widens from `("physician",)` to
`("physician", "advanced_practice")`.

---

## Acceptance Criteria Addressed

| US-029 AC | Requirement |
|---|---|
| **Scenario 4** | `approved_at` = UTC now; `reviewed_by_user_id` = approving user ID; `ai_assisted_label` stays `True`; `status=APPROVED` |
| **DoD** | RBAC: only `physician` or `advanced_practice` may approve |
| **DoD** | Audit log entry created on approval |

---

## Implementation Steps

### 1. Update Approve Endpoint in `backend/api/routers/documents.py`

Replace the existing `require_roles("physician")` dependency with the widened role list
and add the three new field writes from TASK-001.

```python
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db_session, require_roles
from api.schemas.document_schemas import DocumentResponse, DocumentStatus
from models.document import Document
from models.user import User
from services.audit_service import write_audit_log
from .utils import get_document_or_404


@router.patch(
    "/{document_id}/approve",
    summary="Approve a document — physician or advanced_practice role only (US-029 Scenario 4)",
    status_code=status.HTTP_200_OK,
    response_model=DocumentResponse,
)
async def approve_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_roles("physician", "advanced_practice")),
) -> DocumentResponse:
    """
    Transition document status PENDING_REVIEW → APPROVED and record approval metadata.

    Sets:
      - Document.status           = APPROVED
      - Document.approved_at      = UTC now
      - Document.reviewed_by_user_id = current_user.id
      - Document.ai_assisted_label remains True (permanent provenance — must NOT be reset)

    RBAC: restricted to `physician` and `advanced_practice` JWT roles (US-029 DoD).
    Returns 403 for all other roles.
    Returns 404 if document not found.
    Returns 409 if document is already APPROVED or REJECTED.

    A HIPAA audit log entry is written unconditionally on success.
    """
    doc: Document = await get_document_or_404(db, document_id)

    if doc.status == DocumentStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document is already approved.",
        )
    if doc.status == DocumentStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Rejected documents cannot be approved directly. Regenerate the document.",
        )

    # ── Apply approval fields (US-029 Scenario 4) ─────────────────────────────
    doc.status = DocumentStatus.APPROVED
    doc.approved_at = datetime.now(tz=timezone.utc)
    doc.reviewed_by_user_id = current_user.id
    # NOTE: doc.ai_assisted_label is deliberately NOT modified here.
    #       The permanent provenance flag must remain True after approval (BR-011).

    # ── HIPAA audit log (US-029 DoD) ──────────────────────────────────────────
    await write_audit_log(
        db=db,
        action="DOCUMENT_APPROVED",
        resource_type="Document",
        resource_id=document_id,
        performed_by=current_user.id,
        metadata={
            "document_type": doc.document_type,
            "encounter_id": str(doc.encounter_id),
            "ai_assisted_label": doc.ai_assisted_label,
            "approved_at": doc.approved_at.isoformat(),
        },
    )

    await db.commit()
    await db.refresh(doc)

    return DocumentResponse.model_validate(doc)
```

### 2. Verify `require_roles` in `backend/api/dependencies.py`

Confirm (or update) the existing `require_roles` factory to be role-list variadic — no
structural change needed if US-028 TASK-004 already implemented it with `*allowed_roles`.
The only change is the call site passes two role strings instead of one.

```python
# No code change required here if the factory already accepts *args.
# Call site diff only:
#
# BEFORE (US-028):  Depends(require_roles("physician"))
# AFTER  (US-029):  Depends(require_roles("physician", "advanced_practice"))
```

### 3. Extend `backend/services/audit_service.py` — `write_audit_log` helper

If `write_audit_log` does not yet exist, create it. If it does, confirm it accepts the
`metadata` dict parameter.

```python
"""
HIPAA-compliant audit log writer.

Appends an immutable record to the `audit_log` table for every privileged action.
PHI is excluded from the metadata dict — only resource IDs and action names are stored.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.audit_log import AuditLog


async def write_audit_log(
    db: AsyncSession,
    action: str,
    resource_type: str,
    resource_id: UUID,
    performed_by: UUID,
    metadata: Optional[dict[str, Any]] = None,
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
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            performed_by=performed_by,
            performed_at=datetime.now(tz=timezone.utc),
            metadata=metadata or {},
        )
        db.add(entry)
        # Flushed (not committed) here; the caller's commit includes this row.
        await db.flush()
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger("audit").error(
            "Failed to write audit log entry: action=%s resource_id=%s error=%s",
            action,
            resource_id,
            exc,
        )
```

### 4. Extend `DocumentResponse` Resolver in `backend/api/routers/documents.py`

When serialising the approved document, resolve `reviewed_by_display_name` from the
eager-loaded relationship set in TASK-001.

```python
def _resolve_display_name(doc: Document) -> Optional[str]:
    """
    Return the approving clinician's display_name for the UI footer.

    Returns None if the document is not yet approved or the user record
    cannot be resolved (e.g. deleted account).
    """
    if doc.reviewed_by_user is None:
        return None
    return doc.reviewed_by_user.display_name


# In the approve endpoint response assembly:
response = DocumentResponse.model_validate(doc)
response.reviewed_by_display_name = _resolve_display_name(doc)
return response
```

---

## File Targets

| Action | Path |
|--------|------|
| **Modify** | `backend/api/routers/documents.py` |
| **Modify** | `backend/api/dependencies.py` (call-site role list only) |
| **Create / Modify** | `backend/services/audit_service.py` |

---

## Definition of Done

- [ ] `PATCH /api/v1/documents/{id}/approve` accepts `physician` and `advanced_practice` JWT roles
- [ ] `PATCH /api/v1/documents/{id}/approve` returns 403 for any other role
- [ ] On success: `Document.approved_at` = UTC now, `Document.reviewed_by_user_id` = current user ID
- [ ] `Document.ai_assisted_label` is not modified by the approve endpoint
- [ ] `Document.status` transitions to `APPROVED`
- [ ] Audit log row written on every successful approval
- [ ] 409 returned if document already `APPROVED` or `REJECTED`
- [ ] `reviewed_by_display_name` populated in response from `app_user.display_name` join

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 | Story task | Schema columns `approved_at`, `reviewed_by_user_id` must exist |
| US-028/TASK-004 | Story task | Base approve endpoint and `require_roles` dependency factory |
