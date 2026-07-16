---
id: TASK-026-005
title: "Update Review Queue API to Exclude INCOMPLETE Documents and Expose Completeness Fields in Tasks API"
user_story: US-026
epic: EP-004
sprint: 2
layer: Backend — API
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [US-025, TASK-026-003]
---

# TASK-026-005: Update Review Queue API to Exclude INCOMPLETE Documents and Expose Completeness Fields in Tasks API

> **Story:** US-026 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Backend — API | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

Two API changes are required:

1. **Review queue filter** — `GET /api/v1/documents?queue=review` must only return documents with `completeness_status=COMPLETE` (Scenario 2). Documents with `completeness_status=INCOMPLETE` or `NULL` must be excluded from the physician review queue.

2. **Tasks API** — `GET /api/v1/encounters/{id}/tasks` must include `completeness_status` and `missing_fields` on the `DOCUMENTATION` task entry (Scenario 4).

Both are query-layer changes only — no new endpoints, no business logic duplication.

---

## Acceptance Criteria Addressed

| US-026 AC | Requirement |
|---|---|
| **Scenario 2** | `INCOMPLETE` documents NOT returned in review queue API |
| **Scenario 4** | `GET /api/v1/encounters/{id}/tasks` response includes `completeness_status` and `missing_fields` |

---

## Implementation Steps

### 1. Update `DocumentRepository.get_review_queue()` query

Locate the existing method that returns documents for the physician review queue and add a `completeness_status=COMPLETE` filter:

```python
# backend/db/repositories/document_repository.py

async def get_review_queue(self, limit: int = 50, offset: int = 0) -> list[Document]:
    """
    Return documents ready for physician review.

    Filters:
      - status = PENDING_REVIEW
      - completeness_status = COMPLETE   ← US-026: exclude INCOMPLETE documents

    Args:
        limit: Maximum number of records to return (pagination).
        offset: Number of records to skip (pagination).

    Returns:
        List of Document ORM instances ready for physician review.
    """
    result = await self._session.execute(
        select(Document)
        .where(
            Document.status == DocumentStatus.PENDING_REVIEW,
            Document.completeness_status == CompletenessStatus.COMPLETE.value,  # US-026
        )
        .order_by(Document.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())
```

> **Note:** Documents where `completeness_status IS NULL` (pre-migration rows) are also excluded. This is intentional — they have not been validated and must not reach physicians.

### 2. Update `EncounterTaskResponse` Pydantic schema

Locate the Pydantic response schema used by `GET /api/v1/encounters/{id}/tasks` and add the completeness fields to the documentation task section:

```python
# backend/api/schemas/encounter_schemas.py  (or equivalent response models file)

from typing import List, Optional


class DocumentationTaskDetail(BaseModel):
    """
    Detail block for the DOCUMENTATION agent task entry in the encounter tasks response.

    Fields added by US-026:
      - completeness_status: "COMPLETE", "INCOMPLETE", or None (not yet validated).
      - missing_fields: list of absent required field names. Empty list when COMPLETE.
    """
    document_id: Optional[str] = None
    generation_type: Optional[str] = None
    completeness_status: Optional[str] = None      # US-026
    missing_fields: List[str] = []                 # US-026


class EncounterTaskEntry(BaseModel):
    """Single task entry in the encounter tasks list."""
    task_type: str          # e.g. "DOCUMENTATION", "MEDICATION_RECONCILIATION"
    status: str             # e.g. "COMPLETE", "IN_PROGRESS", "PENDING"
    details: Optional[DocumentationTaskDetail] = None
```

### 3. Update tasks query to populate completeness fields

In the encounter tasks router/service, JOIN or subquery the `document` table to retrieve `completeness_status` and `missing_fields` for the `DOCUMENTATION` task:

```python
# backend/api/routers/encounters.py (or tasks service)

@router.get("/encounters/{encounter_id}/tasks", response_model=list[EncounterTaskEntry])
async def get_encounter_tasks(
    encounter_id: str,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(require_authenticated_user),
) -> list[EncounterTaskEntry]:
    """
    Return agent task statuses for an encounter.

    The DOCUMENTATION task entry includes completeness_status and missing_fields
    populated from the most recent Document record for this encounter (US-026 Scenario 4).
    """
    tasks = await TaskRepository(session).get_encounter_tasks(encounter_id)
    documents = await DocumentRepository(session, signalr_client=None).get_by_encounter(encounter_id)

    # Build DOCUMENTATION task detail from the latest document record
    latest_doc = max(documents, key=lambda d: d.created_at, default=None) if documents else None

    result: list[EncounterTaskEntry] = []
    for task in tasks:
        entry = EncounterTaskEntry(task_type=task.task_type, status=task.status)

        if task.task_type == "DOCUMENTATION" and latest_doc:
            entry.details = DocumentationTaskDetail(
                document_id=str(latest_doc.id),
                generation_type=latest_doc.generation_type,
                completeness_status=latest_doc.completeness_status,   # US-026
                missing_fields=latest_doc.missing_fields or [],        # US-026
            )
        result.append(entry)

    return result
```

---

## File Targets

| Action | Path |
|--------|------|
| **Update** | `backend/db/repositories/document_repository.py` |
| **Update** | `backend/api/schemas/encounter_schemas.py` (or equivalent) |
| **Update** | `backend/api/routers/encounters.py` (or equivalent tasks router) |

---

## Definition of Done

- [ ] `get_review_queue()` query filters `completeness_status = 'COMPLETE'` — INCOMPLETE docs absent from result
- [ ] `GET /api/v1/encounters/{id}/tasks` response includes `completeness_status` and `missing_fields` on the DOCUMENTATION task
- [ ] `missing_fields` defaults to `[]` (not `null`) in the API response when no document exists yet
- [ ] OpenAPI schema updated (FastAPI auto-generates from Pydantic models — verify `http://localhost:8000/docs`)
- [ ] No N+1 query — document lookup is a single SELECT per encounter, not one per task

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| US-025 | Story | `Document` ORM and `DocumentRepository` base must exist |
| TASK-026-003 | Task | `completeness_status` and `missing_fields` columns on `Document` table |
