---
id: TASK-004
title: "Implement `PATCH /api/v1/documents/{id}/approve` and `PATCH /api/v1/documents/{id}/reject` Endpoints with RBAC"
user_story: US-028
epic: EP-004
sprint: 2
layer: Backend — API
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [TASK-001, TASK-003]
---

# TASK-004: Implement Approve and Reject API Endpoints with RBAC

> **Story:** US-028 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Backend — API | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-028 Scenarios 3 and 4 require two status-transition endpoints:

- `PATCH /api/v1/documents/{id}/approve` — restricted to `physician` role (403 for all other roles)
- `PATCH /api/v1/documents/{id}/reject` — accessible to all reviewers (physician, nurse, care_coordinator)

Both endpoints write a HIPAA audit log entry and advance `Document.status`. Only the approve
endpoint is restricted by role; the reject endpoint is accessible to all roles with document
access. Neither endpoint permits transitioning from `APPROVED` back to `PENDING_REVIEW`.

---

## Acceptance Criteria Addressed

| US-028 AC | Requirement |
|---|---|
| **Scenario 3** | `status` only advances to `APPROVED` via the approve endpoint — not via save-draft |
| **Scenario 4** | Nurse JWT returns `403 Forbidden`; status remains `PENDING_REVIEW` |

---

## Implementation Steps

### 1. Add `require_roles` Dependency to `backend/api/dependencies.py`

```python
"""
FastAPI dependency helpers for authentication and role-based access control.

`require_roles` enforces that the current user's JWT role claim matches
one of the allowed roles. Returns 403 Forbidden if not.
"""
from __future__ import annotations

from typing import Callable
from fastapi import Depends, HTTPException, status
from models.user import User
from api.dependencies import get_current_user


def require_roles(*allowed_roles: str) -> Callable:
    """
    Dependency factory: enforces role membership from JWT `role` claim.

    Usage:
        current_user: User = Depends(require_roles("physician"))

    Returns a FastAPI dependency that raises HTTP 403 if the user's role is not
    in `allowed_roles`. Roles are compared case-insensitively.
    """
    async def _check(current_user: User = Depends(get_current_user)) -> User:
        normalised_role = (current_user.role or "").lower()
        if normalised_role not in {r.lower() for r in allowed_roles}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Role '{current_user.role}' is not authorised to perform this action. "
                    f"Required role(s): {', '.join(allowed_roles)}."
                ),
            )
        return current_user

    return _check
```

### 2. Add Approve and Reject Endpoints to `backend/api/routers/documents.py`

```python
@router.patch(
    "/{document_id}/approve",
    summary="Approve a document — physician role only (Scenario 4)",
    status_code=status.HTTP_200_OK,
)
async def approve_document(
    document_id: UUID,
    body: DocumentApproveRequest,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_roles("physician")),
) -> dict:
    """
    Transition document status from PENDING_REVIEW → APPROVED.

    Restricted to physician role (JWT `role` claim = 'physician').
    Returns 403 if called with any other role (Scenario 4).
    Returns 409 if document is already APPROVED or REJECTED.
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
            detail="Rejected documents cannot be approved directly. Create a new version.",
        )

    doc.status = DocumentStatus.APPROVED
    if body.notes:
        # Store approval notes in metadata without overwriting existing keys
        metadata = doc.metadata or {}
        metadata["approval_notes"] = body.notes
        metadata["approved_by"] = str(current_user.id)
        doc.metadata = metadata

    await db.commit()
    await db.refresh(doc)

    logger.info(
        "Document %s approved by physician %s", document_id, current_user.id
    )

    return {
        "document_id": str(document_id),
        "status": DocumentStatus.APPROVED,
        "approved_by": str(current_user.id),
    }


@router.patch(
    "/{document_id}/reject",
    summary="Reject a document — all reviewer roles",
    status_code=status.HTTP_200_OK,
)
async def reject_document(
    document_id: UUID,
    body: DocumentRejectRequest,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Transition document status from PENDING_REVIEW → REJECTED.

    Accessible to all authenticated users with document access.
    `rejection_reason` is mandatory (min 10 characters) and stored in
    `Document.rejection_reason` column and `Document.metadata`.
    """
    doc: Document = await get_document_or_404(db, document_id)

    if doc.status == DocumentStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document is already rejected.",
        )

    doc.status = DocumentStatus.REJECTED
    doc.rejection_reason = body.rejection_reason

    metadata = doc.metadata or {}
    metadata["rejected_by"] = str(current_user.id)
    doc.metadata = metadata

    await db.commit()
    await db.refresh(doc)

    logger.info(
        "Document %s rejected by user %s (role: %s)",
        document_id,
        current_user.id,
        current_user.role,
    )

    return {
        "document_id": str(document_id),
        "status": DocumentStatus.REJECTED,
        "rejected_by": str(current_user.id),
    }
```

---

## File Locations

| File | Path |
|---|---|
| `dependencies.py` (update) | `backend/api/dependencies.py` |
| `documents.py` (update) | `backend/api/routers/documents.py` |

---

## Validation Checklist

- [ ] `PATCH /approve` with physician JWT → `200 OK`, `status: APPROVED`
- [ ] `PATCH /approve` with nurse JWT → `403 Forbidden`, `status` remains `PENDING_REVIEW`
- [ ] `PATCH /approve` with care_coordinator JWT → `403 Forbidden`
- [ ] `PATCH /approve` on already-APPROVED document → `409 Conflict`
- [ ] `PATCH /reject` accepts physician, nurse, care_coordinator roles (all succeed)
- [ ] `PATCH /reject` without `rejection_reason` body → `422 Unprocessable Entity`
- [ ] `PATCH /reject` with `rejection_reason` shorter than 10 chars → `422`
- [ ] `Document.rejection_reason` column populated on reject
- [ ] `require_roles` comparison is case-insensitive
- [ ] HIPAA audit log entry written for both approve and reject transitions

---

## Dependencies

| Dependency | Notes |
|---|---|
| `TASK-001` | `DocumentStatus`, `DocumentApproveRequest`, `DocumentRejectRequest` schemas |
| `TASK-003` | `get_document_or_404` service function |
| `US-025` | JWT authentication and `User.role` claim already implemented |
