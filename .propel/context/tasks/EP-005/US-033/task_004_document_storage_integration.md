---
id: TASK-004
title: "Document Storage Integration — medications_section in Patient Instructions"
user_story: US-033
epic: EP-005
sprint: 2
layer: Backend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-033/TASK-003]
---

# TASK-004: Document Storage Integration — `medications_section` in Patient Instructions

> **Story:** US-033 | **Epic:** EP-005 | **Sprint:** 2 | **Layer:** Backend | **Est:** 2 h  
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-033 AC Scenario 3 requires that the generated medication summary is stored on the `Document` record as part of the patient discharge instructions. The `document` table stores discharge documents produced by the Documentation Agent (EP-002). The `medications_section` field is a JSONB column (if not already present, an Alembic migration is required) that persists the serialised `MedicationSummaryOutput`.

When the Documentation Agent finalises a discharge document, it reads `medications_section` to embed the plain-language medication summary in the patient instructions PDF/HTML.

**Design references:**
- US-033 AC Scenario 3 — `medications_section` of the patient discharge instructions document
- design.md §6 — Data Architecture: `document` table with JSONB content fields
- design.md §4.1 — SQLAlchemy 2.x async ORM; Alembic for migrations

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| AC Scenario 3 | Summary stored in `document.medications_section` (JSONB); linked to discharge instructions |

---

## Implementation Steps

### 1. Check `Document` ORM model in `backend/app/models/document.py`

Verify that a `medications_section` column exists. If not, add:

```python
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB

# Within the Document model class:
medications_section: Mapped[dict | None] = mapped_column(
    JSONB,
    nullable=True,
    default=None,
    comment="Patient-readable medication change summary (MedicationSummaryOutput schema)",
)
```

### 2. Generate Alembic migration (only if column is absent)

```bash
cd backend
alembic revision --autogenerate -m "add_medications_section_to_document"
```

Verify the generated migration adds only the `medications_section` JSONB column:

```python
# Expected migration content (verify before applying):
def upgrade() -> None:
    op.add_column(
        "document",
        sa.Column(
            "medications_section",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Patient-readable medication change summary (MedicationSummaryOutput schema)",
        ),
    )

def downgrade() -> None:
    op.drop_column("document", "medications_section")
```

### 3. Implement `MedicationSummaryWriter` service

Create `backend/app/agents/medication_reconciliation/summary/writer.py`:

```python
"""Persists the generated MedicationSummaryOutput to the Document record.

Writes the summary into ``document.medications_section`` (JSONB) so that
the Documentation Agent can embed it in the patient discharge instructions.

Design refs:
    US-033 AC Scenario 3  — summary stored in Document.medications_section
    design.md §6          — Document table; JSONB content fields
    design.md §4.1        — SQLAlchemy 2.x async ORM; no N+1 writes
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.agents.medication_reconciliation.summary.schema import MedicationSummaryOutput

logger = logging.getLogger(__name__)


class MedicationSummaryWriter:
    """Writes a MedicationSummaryOutput to the Document record.

    Args:
        db: Async SQLAlchemy session (write session — primary DB).
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def write(
        self,
        document_id: int,
        summary: MedicationSummaryOutput,
    ) -> None:
        """Persist the medication summary to the document record.

        Args:
            document_id: Primary key of the ``Document`` record to update.
            summary: Validated ``MedicationSummaryOutput`` to store.

        Raises:
            ValueError: If no Document with ``document_id`` is found.
        """
        result = await self._db.execute(
            select(Document).where(Document.id == document_id)
        )
        document = result.scalar_one_or_none()
        if document is None:
            raise ValueError(
                f"Document id={document_id} not found — cannot write medications_section"
            )

        document.medications_section = summary.model_dump()
        await self._db.flush()
        logger.info(
            "medications_section written: document_id=%d categories=%s",
            document_id,
            list(summary.model_dump().keys()),
        )
```

### 4. Wire into the Medication Reconciliation Agent event handler

In `backend/app/agents/medication_reconciliation/agent.py` (or the Pub/Sub consumer), after `MedicationSummaryGenerator.generate()` completes, call `MedicationSummaryWriter.write()`:

```python
summary = await self._summary_generator.generate(reconciliation_result)
await self._summary_writer.write(
    document_id=encounter.discharge_document_id,
    summary=summary,
)
```

---

## File Checklist

| File | Action |
|------|--------|
| `backend/app/models/document.py` | Update — add `medications_section: Mapped[dict \| None]` column if absent |
| `backend/alembic/versions/<timestamp>_add_medications_section_to_document.py` | Create via `alembic revision --autogenerate` |
| `backend/app/agents/medication_reconciliation/summary/writer.py` | Create |
| `backend/app/agents/medication_reconciliation/agent.py` | Update — wire `MedicationSummaryWriter` call |

---

## Validation

- [ ] `MedicationSummaryWriter.write()` persists `summary.model_dump()` to `medications_section`
- [ ] `MedicationSummaryWriter.write()` raises `ValueError` for unknown `document_id`
- [ ] `await db.flush()` called after update (no commit — caller owns transaction)
- [ ] Alembic `upgrade` adds JSONB column; `downgrade` removes it cleanly
- [ ] No PHI written to `medications_section` beyond what `MedicationSummaryOutput` defines (drug names and instructions only — not patient identifiers)
- [ ] No N+1 queries — single `SELECT` + single `flush()` per call

---

## Definition of Done

- [ ] `writer.py` implemented and peer-reviewed
- [ ] Alembic migration reviewed and applied to dev environment
- [ ] `alembic downgrade -1` tested and reverts cleanly
- [ ] Unit tests written in TASK-006
