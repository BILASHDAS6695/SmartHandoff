---
id: TASK-006
title: "Implement `DocumentRepository.create_discharge_document()` — Encrypted ORM Write"
user_story: US-025
epic: EP-004
sprint: 2
layer: Backend — Data / ORM
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [US-006, TASK-001, TASK-004]
---

# TASK-006: Implement `DocumentRepository.create_discharge_document()` — Encrypted ORM Write

> **Story:** US-025 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Backend — Data / ORM | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

After generating the discharge summary (TASK-004 or TASK-005 fallback), the `DocumentationAgent` calls `DocumentRepository.create_discharge_document()` to persist the structured summary as a `Document` ORM record. This task implements that repository method.

Key constraints (from DoD and ADR-007):
- `content` column: AES-256-GCM encrypted JSON of the full `DischargeSummarySchema` — uses the existing `EncryptedType` SQLAlchemy decorator from US-006
- `status` = `PENDING_REVIEW` — document enters the physician review queue
- `ai_assisted_label` = `True` — HIPAA AI-disclosure requirement
- `generation_type` column: persists `"AI"` or `"TEMPLATE"` string from `GenerationType` enum
- After DB commit, a SignalR push notification is emitted to the `encounter-{id}` group

The `Document` ORM model (`Document` table, `EncryptedType`) is already defined by US-006. This task adds the repository method only.

---

## Acceptance Criteria Addressed

| US-025 AC | Requirement |
|---|---|
| **Scenario 1** | `Document` record created with `status=PENDING_REVIEW` |
| **Scenario 2** | `generation_type=TEMPLATE` persisted for fallback documents |

---

## Implementation Steps

### 1. Update `db/repositories/document_repository.py`

Add `create_discharge_document()` to the existing `DocumentRepository` class:

```python
"""
DocumentRepository — async ORM repository for Document records.

Implements create, read, and status-transition operations for the Document
entity. All PHI content is encrypted at the ORM layer via EncryptedType
before database write (ADR-007).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from db.models.document import Document, DocumentStatus, DocumentType  # US-006
from agents.documentation.schemas import DischargeSummarySchema, GenerationType
from integrations.signalr_hub import SignalRHubClient

logger = logging.getLogger(__name__)


class DocumentRepository:
    """
    Async repository for Document ORM operations.

    Args:
        session: SQLAlchemy AsyncSession (injected per-request/per-event).
        signalr_client: SignalR hub client for real-time UI push notifications.
    """

    def __init__(self, session: AsyncSession, signalr_client: SignalRHubClient) -> None:
        self._session = session
        self._signalr = signalr_client

    async def create_discharge_document(
        self,
        encounter_id: str,
        summary: DischargeSummarySchema,
    ) -> Document:
        """
        Persist an AI-generated or template-generated discharge summary as a
        Document ORM record with status=PENDING_REVIEW.

        The summary JSON is stored encrypted via EncryptedType (AES-256-GCM).
        After a successful commit, a SignalR push is sent to the encounter group.

        Args:
            encounter_id: The FHIR/internal encounter identifier.
            summary: Validated DischargeSummarySchema (AI or template-generated).

        Returns:
            The persisted Document ORM instance.

        Raises:
            SQLAlchemyError: Propagated on DB write failure (caller handles retry via BaseAgent).
        """
        # Serialize summary to JSON; EncryptedType handles AES-256-GCM encryption at ORM layer
        summary_json = summary.model_dump_json()

        document = Document(
            encounter_id=encounter_id,
            document_type=DocumentType.DISCHARGE_SUMMARY,
            status=DocumentStatus.PENDING_REVIEW,          # Scenario 1 & 2
            ai_assisted_label=True,                        # HIPAA AI-disclosure
            generation_type=summary.generation_type.value, # "AI" or "TEMPLATE"
            content=summary_json,                          # Encrypted by EncryptedType column
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        self._session.add(document)
        await self._session.commit()
        await self._session.refresh(document)

        logger.info(
            "Document record created",
            extra={
                "document_id": str(document.id),
                "encounter_id": encounter_id,
                "status": document.status.value,
                "generation_type": document.generation_type,
            },
        )

        # Real-time push: notify physician dashboard that summary is ready for review
        await self._signalr.send_to_group(
            group=f"encounter-{encounter_id}",
            method="DocumentReady",
            payload={
                "document_id": str(document.id),
                "document_type": DocumentType.DISCHARGE_SUMMARY.value,
                "status": DocumentStatus.PENDING_REVIEW.value,
                "generation_type": document.generation_type,
            },
        )

        return document
```

### 2. Alembic Migration — Add `generation_type` Column to `documents` Table

If the `Document` model from US-006 does not already include `generation_type`, create a new Alembic migration:

```python
# migrations/versions/xxxx_add_generation_type_to_documents.py
"""Add generation_type column to documents table

Revision ID: xxxx
Revises: <us006_revision_id>
Create Date: 2026-07-16
"""
from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "generation_type",
            sa.String(length=20),
            nullable=False,
            server_default="AI",
            comment="How the document was generated: AI or TEMPLATE",
        ),
    )

def downgrade() -> None:
    op.drop_column("documents", "generation_type")
```

> **Note:** If US-006 already includes `generation_type`, skip this migration. Verify before applying.

### 3. Update `db/models/document.py` — Add `generation_type` field

```python
# Add to existing Document model (US-006):
from sqlalchemy import Column, String

generation_type: Mapped[str] = mapped_column(
    String(20),
    nullable=False,
    default="AI",
    comment="GenerationType enum value: AI or TEMPLATE",
)
```

### 4. Unit Tests — `tests/db/repositories/test_document_repository.py`

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from db.repositories.document_repository import DocumentRepository
from agents.documentation.schemas import DischargeSummarySchema, GenerationType


MINIMAL_SUMMARY = DischargeSummarySchema(
    encounter_id="ENC-001",
    diagnosis_summary=[{"icd10_code": "E11.9", "description": "Type 2 diabetes", "is_primary": True}],
    medications_at_discharge=[{"drug_name": "metformin", "dose": "500 mg", "frequency": "twice daily", "route": "oral"}],
    follow_up_instructions=[{"instruction": "Follow up with PCP within 7 days"}],
    warning_signs=["Shortness of breath"],
    activity_restrictions=["No heavy lifting"],
    generation_type=GenerationType.AI,
)


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.fixture
def mock_signalr():
    client = MagicMock()
    client.send_to_group = AsyncMock()
    return client


@pytest.fixture
def repo(mock_session, mock_signalr):
    return DocumentRepository(session=mock_session, signalr_client=mock_signalr)


@pytest.mark.asyncio
async def test_create_discharge_document_sets_pending_review(repo, mock_session):
    await repo.create_discharge_document("ENC-001", MINIMAL_SUMMARY)
    added_doc = mock_session.add.call_args[0][0]
    assert added_doc.status.value == "PENDING_REVIEW"


@pytest.mark.asyncio
async def test_create_discharge_document_sets_ai_assisted_label(repo, mock_session):
    await repo.create_discharge_document("ENC-001", MINIMAL_SUMMARY)
    added_doc = mock_session.add.call_args[0][0]
    assert added_doc.ai_assisted_label is True


@pytest.mark.asyncio
async def test_create_discharge_document_sets_generation_type_ai(repo, mock_session):
    await repo.create_discharge_document("ENC-001", MINIMAL_SUMMARY)
    added_doc = mock_session.add.call_args[0][0]
    assert added_doc.generation_type == "AI"


@pytest.mark.asyncio
async def test_create_discharge_document_template_sets_generation_type_template(repo, mock_session):
    template_summary = MINIMAL_SUMMARY.model_copy(update={"generation_type": GenerationType.TEMPLATE})
    await repo.create_discharge_document("ENC-001", template_summary)
    added_doc = mock_session.add.call_args[0][0]
    assert added_doc.generation_type == "TEMPLATE"


@pytest.mark.asyncio
async def test_signalr_push_sent_after_commit(repo, mock_signalr):
    await repo.create_discharge_document("ENC-001", MINIMAL_SUMMARY)
    mock_signalr.send_to_group.assert_awaited_once()
    call_kwargs = mock_signalr.send_to_group.call_args.kwargs
    assert call_kwargs["group"] == "encounter-ENC-001"
    assert call_kwargs["method"] == "DocumentReady"
```

---

## File Targets

| Action | Path |
|--------|------|
| **Update** | `backend/db/repositories/document_repository.py` |
| **Update** | `backend/db/models/document.py` (if `generation_type` column missing) |
| **Create** | `backend/migrations/versions/xxxx_add_generation_type_to_documents.py` (if required) |
| **Create** | `backend/tests/db/repositories/test_document_repository.py` |

---

## Definition of Done

- [ ] `create_discharge_document()` persists `Document` with `status=PENDING_REVIEW`, `ai_assisted_label=True`, `generation_type` string
- [ ] `content` field encrypted via `EncryptedType` (AES-256-GCM) — verified by checking raw DB column is not plaintext
- [ ] `generation_type` column added to `documents` table (migration applied if needed)
- [ ] SignalR `DocumentReady` push sent to `encounter-{id}` group after commit
- [ ] All 5 unit tests pass

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| US-006 | Story | `Document` ORM model, `EncryptedType`, `DocumentStatus`, `DocumentType` enums required |
| TASK-001 | Task | `DischargeSummarySchema`, `GenerationType` used as input type |
| TASK-004 | Task | `DocumentationAgent.process()` calls this repository method |
| SignalRHubClient | Component | Existing SignalR hub client — not implemented here |
