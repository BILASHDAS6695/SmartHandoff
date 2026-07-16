---
id: TASK-005
title: "Add `translations` JSONB Column to `Document` Model — Alembic Migration"
user_story: US-027
epic: EP-004
sprint: 2
layer: Backend — Data / ORM
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [TASK-001, US-025 TASK-006]
---

# TASK-005: Add `translations` JSONB Column to `Document` Model — Alembic Migration

> **Story:** US-027 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Backend — Data / ORM | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-027 DoD requires `Document.translations` JSONB field to store per-language patient instruction content and quality metadata from TASK-004. The `Document` ORM model was established in US-006 and extended in US-025 (TASK-006). This task adds the `translations` JSONB column and a companion `metadata` JSONB column (for `language_fallback` and `requested_language` flags from Scenario 4) via a new Alembic migration.

The `translations` column stores the serialised `PatientInstructionsDocument.translations` dict. The `metadata` column stores document-level flags including `language_fallback` and `requested_language`.

---

## Acceptance Criteria Addressed

| US-027 AC | Requirement |
|---|---|
| **Scenario 3** | `Document.translations` stores per-language content |
| **Scenario 4** | `Document.metadata` records `language_fallback=true` and `requested_language=ja` |

---

## Implementation Steps

### 1. Update `db/models/document.py`

Add `translations` and `metadata` JSONB columns to the existing `Document` SQLAlchemy model:

```python
# In db/models/document.py — add to existing Document model columns

from sqlalchemy import Column, String, Boolean, DateTime, Text, JSON
from sqlalchemy.dialects.postgresql import JSONB

# ... existing columns ...

# US-027: Per-language patient instructions (PatientInstructionsDocument.translations)
translations = Column(
    JSONB,
    nullable=True,
    default=None,
    comment=(
        "Per-language patient instruction content keyed by BCP-47 code. "
        "JSON schema: Dict[str, TranslationEntry]. Populated by PatientInstructionsGenerator."
    ),
)

# US-027: Document-level metadata flags including language_fallback and requested_language
# Also used by future agents for document-type-specific metadata
document_metadata = Column(
    "metadata",
    JSONB,
    nullable=True,
    default=None,
    comment=(
        "Arbitrary document metadata dict. "
        "Keys for US-027: language_fallback (bool), requested_language (str | null)."
    ),
)
```

> **Note:** Column is named `document_metadata` in Python to avoid conflict with SQLAlchemy's reserved `metadata` attribute on `DeclarativeBase`. The DB column name is `metadata`.

### 2. Create Alembic migration

Create `backend/alembic/versions/<timestamp>_us027_add_document_translations.py`:

```python
"""us027: add translations and metadata JSONB columns to document table

Revision ID: us027_translations
Revises: <previous_revision_id>  # Replace with actual previous revision ID
Create Date: 2026-07-16
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic
revision = "us027_translations"
down_revision = "<previous_revision_id>"  # Replace with actual previous revision ID
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document",
        sa.Column(
            "translations",
            JSONB,
            nullable=True,
            comment="Per-language patient instruction content keyed by BCP-47 code.",
        ),
    )
    op.add_column(
        "document",
        sa.Column(
            "metadata",
            JSONB,
            nullable=True,
            comment="Document-level metadata flags (language_fallback, requested_language, etc.).",
        ),
    )


def downgrade() -> None:
    op.drop_column("document", "metadata")
    op.drop_column("document", "translations")
```

### 3. Update `DocumentRepository` — add `save_patient_instructions()` method

In `backend/db/repositories/document_repository.py`, add:

```python
async def save_patient_instructions(
    self,
    document_id: int,
    instructions_doc: "PatientInstructionsDocument",
) -> None:
    """
    Persist patient instructions translations and language metadata to the Document record.

    Updates `translations` JSONB and `metadata` JSONB fields on the existing Document.
    The Document record must already exist (created by DocumentationAgent, US-025).

    Args:
        document_id: Primary key of the existing Document record.
        instructions_doc: Fully-populated PatientInstructionsDocument from TASK-003/TASK-004.

    Raises:
        ValueError: If the Document record does not exist.
    """
    async with self._session_factory() as session:
        document = await session.get(Document, document_id)
        if document is None:
            raise ValueError(f"Document {document_id} not found.")

        document.translations = instructions_doc.translations_as_dict()
        document.document_metadata = {
            "language_fallback": instructions_doc.language_fallback,
            "requested_language": instructions_doc.requested_language,
            "primary_language": instructions_doc.primary_language,
            "primary_fk_grade": instructions_doc.primary_flesch_kincaid_grade,
        }

        await session.commit()
        logger.info(
            "Patient instructions saved for document %d (primary_lang=%s, fallback=%s).",
            document_id,
            instructions_doc.primary_language,
            instructions_doc.language_fallback,
        )
```

### 4. Add `translations_as_dict()` helper to `PatientInstructionsDocument`

In `backend/agents/documentation/patient_instructions_schemas.py`, add to `PatientInstructionsDocument`:

```python
def translations_as_dict(self) -> dict:
    """
    Serialise translations to a plain dict suitable for JSONB storage.

    Uses Pydantic model_dump() to ensure all nested models are serialised.
    """
    return {
        lang_code: entry.model_dump()
        for lang_code, entry in self.translations.items()
    }
```

---

## File Locations

| File | Path |
|---|---|
| `document.py` (update) | `backend/db/models/document.py` |
| Alembic migration | `backend/alembic/versions/<timestamp>_us027_add_document_translations.py` |
| `document_repository.py` (update) | `backend/db/repositories/document_repository.py` |
| `patient_instructions_schemas.py` (update) | `backend/agents/documentation/patient_instructions_schemas.py` |

---

## Validation Checklist

- [ ] `Document` model has `translations` JSONB column (nullable)
- [ ] `Document` model has `metadata` JSONB column named `document_metadata` in Python, `metadata` in DB
- [ ] Alembic `upgrade()` adds both columns; `downgrade()` removes both
- [ ] `save_patient_instructions()` raises `ValueError` for non-existent document ID
- [ ] `save_patient_instructions()` persists `language_fallback` and `requested_language` in `document_metadata`
- [ ] `translations_as_dict()` uses `model_dump()` (not deprecated `.dict()`)
- [ ] Migration can be run on dev database without errors

---

## Dependencies

| Dependency | Notes |
|---|---|
| `TASK-001` | `PatientInstructionsDocument` schema; adds `translations_as_dict()` |
| `US-025 TASK-006` | Existing `DocumentRepository` and `Document` model to extend |
| `alembic` | Already in project requirements |
| `sqlalchemy.dialects.postgresql.JSONB` | Already used in project |
