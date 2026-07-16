---
id: TASK-003
title: "Implement Patient Portal Documents Filter — Return Only `APPROVED` Documents"
user_story: US-029
epic: EP-004
sprint: 2
layer: Backend — API
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [TASK-001, US-028/TASK-004]
---

# TASK-003: Implement Patient Portal Documents Filter — Return Only `APPROVED` Documents

> **Story:** US-029 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Backend — API | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-029 Scenario 3 requires a dedicated patient portal endpoint that returns only
`APPROVED` documents for a given encounter. Documents with `status=PENDING_REVIEW`,
`DRAFT`, or `REJECTED` must be silently excluded — the portal should return an empty
list rather than an error when no approved documents exist yet.

This is a separate route from the staff-facing `GET /api/v1/documents` endpoint to:

- Enforce the APPROVED-only filter unconditionally (no query param override)
- Apply a patient-scoped RBAC check (patient role sees only their own encounter)
- Avoid leaking draft or rejected AI content to the patient

---

## Acceptance Criteria Addressed

| US-029 AC | Requirement |
|---|---|
| **Scenario 3** | `GET /api/v1/portal/documents?encounter_id={id}` excludes `PENDING_REVIEW` documents |
| **Scenario 3** | Only `APPROVED` documents are returned to the patient portal |
| **DoD** | Patient portal API: filter excludes documents with `status≠APPROVED` |

---

## Implementation Steps

### 1. Create `backend/api/routers/portal.py`

```python
"""
Patient portal API router.

Provides read-only endpoints scoped to the authenticated patient's own data.
All routes enforce:
  1. `patient` role JWT claim (403 for any other role)
  2. Encounter ownership check (patient may only access their own encounters)
  3. Document APPROVED-only filter (PENDING_REVIEW / DRAFT / REJECTED silently excluded)

US-029 Scenario 3: GET /api/v1/portal/documents?encounter_id={id}
"""
from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user, get_db_session, require_roles
from api.schemas.document_schemas import DocumentResponse, DocumentStatus
from models.document import Document
from models.encounter import Encounter
from models.user import User

router = APIRouter(prefix="/portal", tags=["Patient Portal"])


@router.get(
    "/documents",
    summary="Return APPROVED documents for an encounter — patient portal (US-029 Scenario 3)",
    response_model=List[DocumentResponse],
    status_code=status.HTTP_200_OK,
)
async def get_portal_documents(
    encounter_id: UUID = Query(..., description="Encounter UUID to retrieve documents for."),
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_roles("patient")),
) -> List[DocumentResponse]:
    """
    Return only APPROVED documents for the given encounter.

    US-029 Scenario 3: documents with status PENDING_REVIEW, DRAFT, or REJECTED
    are silently excluded.  Returns an empty list (not 404) when no approved
    documents exist yet.

    Ownership check: the authenticated patient must be the subject of the encounter.
    Returns 403 if the encounter belongs to a different patient.
    """
    # ── Ownership check: patient may only read their own encounter ─────────────
    encounter: Encounter | None = await db.get(Encounter, encounter_id)
    if encounter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Encounter {encounter_id} not found.",
        )
    if encounter.patient_user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: encounter does not belong to the authenticated patient.",
        )

    # ── APPROVED-only document query (US-029 Scenario 3) ─────────────────────
    stmt = (
        select(Document)
        .where(Document.encounter_id == encounter_id)
        .where(Document.status == DocumentStatus.APPROVED)   # hard filter — no override
        .order_by(Document.approved_at.desc())
    )
    result = await db.execute(stmt)
    documents: list[Document] = list(result.scalars().all())

    return [DocumentResponse.model_validate(doc) for doc in documents]
```

### 2. Register Portal Router in `backend/main.py`

```python
from api.routers.portal import router as portal_router

# Add after existing router registrations:
app.include_router(portal_router, prefix="/api/v1")
```

### 3. Add `patient_user_id` FK to Encounter Model (if not present)

The ownership check above requires `Encounter.patient_user_id`. Verify this FK exists on
the `Encounter` model from prior epics. If absent, add it:

```python
# In backend/models/encounter.py — add if not already present:
patient_user_id: Mapped[Optional[UUID]] = mapped_column(
    ForeignKey("app_user.id", ondelete="SET NULL"),
    nullable=True,
    index=True,
    comment="FK to the patient's app_user record for portal ownership checks.",
)
```

> **Note:** If `Encounter` already links to a `Patient` entity (not `app_user` directly),
> adjust the ownership predicate to traverse the patient → user join. Do not introduce a
> duplicate FK.

---

## File Targets

| Action | Path |
|--------|------|
| **Create** | `backend/api/routers/portal.py` |
| **Modify** | `backend/main.py` |
| **Verify / Modify** | `backend/models/encounter.py` (add `patient_user_id` if absent) |

---

## Definition of Done

- [ ] `GET /api/v1/portal/documents?encounter_id={id}` returns HTTP 200 with only `APPROVED` documents
- [ ] Response excludes any document where `status ≠ APPROVED` (PENDING_REVIEW, DRAFT, REJECTED)
- [ ] Empty list `[]` returned when no approved documents exist (not 404)
- [ ] Patient authenticated with `patient` JWT role; 403 returned for staff roles
- [ ] Encounter ownership enforced: 403 returned if encounter belongs to a different patient
- [ ] 404 returned if encounter does not exist
- [ ] Portal router registered on `/api/v1` prefix and visible in OpenAPI docs

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 | Story task | `DocumentStatus.APPROVED` and `Document.approved_at` column must exist |
| US-028/TASK-001 | Story task | `DocumentStatus` enum with `APPROVED` value |
