---
id: TASK-026-003
title: "Add `completeness_status` and `missing_fields` Columns to `Document` Model + Alembic Migration"
user_story: US-026
epic: EP-004
sprint: 2
layer: Backend — Data / ORM
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [US-025, US-006]
---

# TASK-026-003: Add `completeness_status` and `missing_fields` Columns to `Document` Model + Alembic Migration

> **Story:** US-026 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Backend — Data / ORM | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

The `Document` ORM model (established in US-006) must be extended with two new columns to persist the outcome of the `CompletenessValidator` (TASK-026-002):

- `completeness_status` — `VARCHAR(20)`: either `"COMPLETE"` or `"INCOMPLETE"`. Defaults to `NULL` until the validator runs.
- `missing_fields` — `JSONB`: ordered list of missing field names. Defaults to `[]`.

An Alembic migration adds both columns in a backwards-compatible manner: existing rows get `NULL` / `[]` defaults, preserving the ability to roll back without data loss (DR-001).

---

## Acceptance Criteria Addressed

| US-026 AC | Requirement |
|---|---|
| **Scenario 1** | `Document.completeness_status = "COMPLETE"` after validator runs on complete doc |
| **Scenario 2** | `Document.completeness_status = "INCOMPLETE"`, `Document.missing_fields = ["follow_up_instructions"]` |
| **Scenario 4** | Tasks API can read `completeness_status` and `missing_fields` from the `Document` row |

---

## Implementation Steps

### 1. Update `backend/db/models/document.py`

Add two new columns to the existing `Document` SQLAlchemy model:

```python
# backend/db/models/document.py
# --- ADD AFTER existing column definitions (e.g. after `generation_type`) ---

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB

# Completeness validation result (populated by CompletenessValidator post-generation)
completeness_status: Mapped[Optional[str]] = mapped_column(
    String(20),
    nullable=True,
    default=None,
    comment="COMPLETE or INCOMPLETE — set by CompletenessValidator after document generation",
)

missing_fields: Mapped[Optional[list]] = mapped_column(
    JSONB,
    nullable=True,
    default=list,
    server_default="'[]'::jsonb",
    comment="Ordered list of field names absent from the document. Empty list when COMPLETE.",
)
```

> **Note:** Do NOT modify any existing columns. Append-only change to preserve rollback safety (DR-001).

### 2. Generate Alembic Migration

Run from the `backend/` directory:

```bash
alembic revision --autogenerate -m "add_completeness_columns_to_document"
```

The generated migration script should contain an `upgrade()` like:

```python
def upgrade() -> None:
    op.add_column(
        "document",
        sa.Column(
            "completeness_status",
            sa.String(length=20),
            nullable=True,
            comment="COMPLETE or INCOMPLETE — set by CompletenessValidator after document generation",
        ),
    )
    op.add_column(
        "document",
        sa.Column(
            "missing_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            server_default=sa.text("'[]'::jsonb"),
            comment="Ordered list of field names absent from the document. Empty list when COMPLETE.",
        ),
    )


def downgrade() -> None:
    op.drop_column("document", "missing_fields")
    op.drop_column("document", "completeness_status")
```

Verify the generated migration matches the above before committing.

### 3. Update `DocumentRepository` — add `update_completeness()` method

Add a new method to `DocumentRepository` (from US-025 / TASK-025-006) that writes the validator result back to the persisted `Document` row:

```python
# backend/db/repositories/document_repository.py

from agents.documentation.completeness_validator import CompletenessResult, CompletenessStatus
from db.models.document import Document, DocumentStatus


async def update_completeness(
    self,
    document: Document,
    result: CompletenessResult,
) -> Document:
    """
    Persist the CompletenessValidator result onto an existing Document row.

    Sets:
      - document.completeness_status to result.status.value ("COMPLETE" or "INCOMPLETE")
      - document.missing_fields to result.missing_fields
      - document.status remains PENDING_REVIEW if COMPLETE;
        reverted to DRAFT if INCOMPLETE (US-026 Scenario 2)

    Args:
        document: The Document ORM instance returned by create_discharge_document().
        result:   CompletenessResult from CompletenessValidator.validate().

    Returns:
        Updated Document instance after commit.
    """
    document.completeness_status = result.status.value
    document.missing_fields = result.missing_fields

    if result.status == CompletenessStatus.INCOMPLETE:
        # Hold the document in DRAFT — not visible in the physician review queue
        document.status = DocumentStatus.DRAFT

    self._session.add(document)
    await self._session.commit()
    await self._session.refresh(document)

    logger.info(
        "DocumentRepository.update_completeness: document_id=%s completeness_status=%s missing_fields=%s",
        document.id,
        document.completeness_status,
        document.missing_fields,
    )
    return document
```

---

## File Targets

| Action | Path |
|--------|------|
| **Update** | `backend/db/models/document.py` |
| **Create** | `backend/alembic/versions/<hash>_add_completeness_columns_to_document.py` |
| **Update** | `backend/db/repositories/document_repository.py` |

---

## Definition of Done

- [ ] `Document.completeness_status` (`String(20)`, nullable) added to ORM model
- [ ] `Document.missing_fields` (`JSONB`, server_default `[]`) added to ORM model
- [ ] Alembic migration file generated and reviewed — `upgrade()` and `downgrade()` both present
- [ ] `DocumentRepository.update_completeness()` method implemented
- [ ] INCOMPLETE documents have `status` reverted to `DRAFT` inside `update_completeness()`
- [ ] No existing column definitions modified (append-only migration)

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| US-006 | Story | `Document` ORM model base must exist |
| US-025 / TASK-025-006 | Task | `DocumentRepository` class must exist before adding the new method |
| TASK-026-002 | Task | `CompletenessResult` type imported by `update_completeness()` |
