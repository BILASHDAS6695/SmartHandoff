---
id: TASK-005
title: "Define ORM Models — `AdtEvent`, `Medication`, `AgentTask`, `Document`, `AuditLog`, `ChatbotTranscript`"
user_story: US-006
epic: EP-DATA
sprint: 1
layer: Backend
estimate: 4h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [TASK-002, TASK-003, TASK-004]
---

# TASK-005: Define ORM Models — `AdtEvent`, `Medication`, `AgentTask`, `Document`, `AuditLog`, `ChatbotTranscript`

> **Story:** US-006 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Backend | **Est:** 4 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

This task completes the full set of 10 ORM models required by US-006 DoD. Each of the six remaining models serves a distinct domain role:

| Model | Purpose | Key Constraint |
|---|---|---|
| `AdtEvent` | Records every HL7 ADT message received | `source_message_id` unique (DR-022) |
| `Medication` | Patient medication list per encounter (reconciliation) | FK to encounter |
| `AgentTask` | Tracks AI agent task state and results | FK to encounter |
| `Document` | AI-generated clinical documents (discharge summaries, instructions) | PHI content encrypted (DR-002) |
| `AuditLog` | Immutable PHI access log | Append-only; no DELETE/UPDATE permitted (DR-003) |
| `ChatbotTranscript` | Patient-chatbot conversation messages | PHI encrypted; linked to encounter (DR-016) |

The `AuditLog` model is intentionally write-only from the application layer — its immutability is enforced by the PostgreSQL Row Security Policy added in TASK-007 migration `0002_audit_log_rls`.

---

## Acceptance Criteria Addressed

| US-006 AC | Requirement |
|---|---|
| **Scenario 3** | MRN unique constraint: `AdtEvent.source_message_id` unique constraint prevents duplicate HL7 message processing (DR-022) |
| **DoD** | ORM models defined for `adt_event`, `medication`, `agent_task`, `document`, `audit_log`, `chatbot_transcript` |

---

## Implementation Steps

### 1. Author `backend/app/models/adt_event.py`

```python
"""AdtEvent ORM model — records each HL7 ADT message received by the HL7 Listener.

DR-022: `source_message_id` (MSH-10 field) carries a unique constraint to
prevent duplicate event processing on MLLP retransmissions.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.encounter import Encounter


class AdtEvent(Base, TimestampMixin):
    """HL7 ADT event record.

    One row per received HL7 message. Idempotency enforced by the unique
    constraint on `source_message_id` (MSH-10). Duplicate messages are
    ACK'd by the HL7 Listener and silently discarded (AIR-001, DR-022).
    """

    __tablename__ = "adt_event"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    encounter_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("encounter.id", ondelete="CASCADE"),
        nullable=False,
    )

    # HL7 MSH-10 message control ID — unique per EHR message (DR-022)
    source_message_id: Mapped[str] = mapped_column(
        sa.String(128),
        nullable=False,
        unique=True,
        comment="HL7 MSH-10 message control ID; unique constraint prevents duplicate processing",
    )

    # HL7 event type (e.g., "A01", "A02", "A03", "A13")
    event_type: Mapped[str] = mapped_column(
        sa.String(8),
        nullable=False,
        comment="HL7 ADT event type from MSH-9.2 (e.g., A01=Admit, A03=Discharge)",
    )

    event_timestamp: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        comment="Message timestamp from HL7 MSH-7",
    )

    sending_facility: Mapped[str | None] = mapped_column(
        sa.String(64),
        nullable=True,
        comment="HL7 MSH-4 sending facility identifier",
    )

    raw_message_path: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        comment="Cloud Storage path to archived raw HL7 message (AIR-003)",
    )

    processing_status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="received",
        comment="One of: received, processing, processed, failed",
    )

    encounter: Mapped["Encounter"] = relationship(
        "Encounter",
        back_populates="adt_events",
        lazy="select",
    )

    __table_args__ = (
        sa.Index("ix_adt_event_source_message_id", "source_message_id", unique=True),
        sa.Index("ix_adt_event_encounter_id", "encounter_id"),
        sa.Index("ix_adt_event_type_timestamp", "event_type", "event_timestamp"),
    )
```

### 2. Author `backend/app/models/medication.py`

```python
"""Medication ORM model — patient medication list per encounter.

Used by the Medication Reconciliation Agent (FR-030–FR-035).
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.encounter import Encounter


class Medication(Base, TimestampMixin):
    """A medication record associated with a patient encounter.

    Populated by the Medication Reconciliation Agent from FHIR
    MedicationRequest resources. Interaction severity set by RxNav API (AIR-050).
    """

    __tablename__ = "medication"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    encounter_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("encounter.id", ondelete="CASCADE"),
        nullable=False,
    )

    drug_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    rxcui: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        comment="RxNorm Concept Unique Identifier for drug interaction lookups (AIR-050)",
    )
    dose: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    route: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    frequency: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

    source: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="admission",
        comment="One of: admission, discharge, home — reconciliation list source",
    )

    interaction_severity: Mapped[str | None] = mapped_column(
        sa.String(16),
        nullable=True,
        comment="One of: HIGH, MEDIUM, LOW — from RxNav interaction check (AIR-051)",
    )

    reconciliation_status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="pending",
        comment="One of: pending, reconciled, flagged, incomplete",
    )

    encounter: Mapped["Encounter"] = relationship(
        "Encounter",
        back_populates="medications",
        lazy="select",
    )

    __table_args__ = (
        sa.Index("ix_medication_encounter_id", "encounter_id"),
        sa.Index("ix_medication_rxcui", "rxcui"),
        sa.Index("ix_medication_severity", "interaction_severity"),
    )
```

### 3. Author `backend/app/models/agent_task.py`

```python
"""AgentTask ORM model — tracks AI agent task lifecycle and results.

DR-012: Agent task records retained 2 years.
One task row is created per agent execution per encounter.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.encounter import Encounter


class AgentTask(Base, TimestampMixin):
    """Agent task execution record.

    Created by the Coordinator Agent for each agent type triggered by
    an ADT event. Status transitions: queued → running → completed / failed.
    """

    __tablename__ = "agent_task"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    encounter_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("encounter.id", ondelete="CASCADE"),
        nullable=False,
    )

    agent_type: Mapped[str] = mapped_column(
        sa.String(64),
        nullable=False,
        comment=(
            "One of: coordinator, documentation, medication_reconciliation, "
            "bed_management, follow_up_care, patient_communication"
        ),
    )

    status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="queued",
        comment="One of: queued, running, completed, failed, pending_approval",
    )

    started_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    # Idempotency: prevents duplicate agent triggers for the same encounter + agent
    pubsub_message_id: Mapped[str | None] = mapped_column(
        sa.String(128),
        nullable=True,
        comment="Pub/Sub message ID; used for idempotency check before processing (AR-008)",
    )

    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default="0"
    )

    encounter: Mapped["Encounter"] = relationship(
        "Encounter",
        back_populates="agent_tasks",
        lazy="select",
    )

    __table_args__ = (
        sa.Index("ix_agent_task_encounter_agent", "encounter_id", "agent_type"),
        sa.Index("ix_agent_task_status", "status"),
        sa.UniqueConstraint(
            "encounter_id",
            "agent_type",
            "pubsub_message_id",
            name="uq_agent_task_idempotency",
        ),
    )
```

### 4. Author `backend/app/models/document.py`

```python
"""Document ORM model — AI-generated clinical documents.

DR-013: Document content (PHI) encrypted at rest via EncryptedString (US-007).
DR-013: Retained 7 years with encounter.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.encryption import EncryptedString
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.encounter import Encounter


class Document(Base, TimestampMixin):
    """AI-generated clinical document (discharge summary, patient instructions, etc.).

    `content` is encrypted via EncryptedString TypeDecorator (US-007).
    Human approval is required before status transitions to 'approved' (FR-020).
    """

    __tablename__ = "document"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    encounter_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("encounter.id", ondelete="RESTRICT"),
        nullable=False,
    )

    document_type: Mapped[str] = mapped_column(
        sa.String(64),
        nullable=False,
        comment=(
            "One of: discharge_summary, patient_instructions, "
            "medication_reconciliation, follow_up_plan"
        ),
    )

    # PHI content encrypted via US-007 EncryptedString (DR-002, DR-013)
    content: Mapped[str] = mapped_column(
        EncryptedString,
        nullable=False,
        comment="Document body — AES-256-GCM encrypted (US-007)",
    )

    language_code: Mapped[str] = mapped_column(
        sa.String(8),
        nullable=False,
        server_default="en",
        comment="Document language (FR-022): en, es, fr, zh, pt",
    )

    status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="draft",
        comment="One of: draft, pending_approval, approved, rejected",
    )

    generation_type: Mapped[str] = mapped_column(
        sa.String(16),
        nullable=False,
        server_default="LLM",
        comment="One of: LLM, TEMPLATE — TEMPLATE set on Vertex AI fallback (AIR-022)",
    )

    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("app_user.id", ondelete="SET NULL"),
        nullable=True,
    )

    encounter: Mapped["Encounter"] = relationship(
        "Encounter",
        back_populates="documents",
        lazy="select",
    )

    __table_args__ = (
        sa.Index("ix_document_encounter_type", "encounter_id", "document_type"),
        sa.Index("ix_document_status", "status"),
    )
```

### 5. Author `backend/app/models/audit_log.py`

```python
"""AuditLog ORM model — immutable PHI access record.

DR-003: Append-only. PostgreSQL RLS (DENY DELETE/UPDATE) enforced by
migration 0002_audit_log_rls.py (TASK-007).
BR-023: 6-year retention minimum.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    """Immutable audit log entry.

    Written by the HIPAA Audit Logger middleware on every PHI access.
    The application DB user does NOT have DELETE or UPDATE privileges on
    this table — enforced by the Row Security Policy in migration 0002.

    NOTE: No `TimestampMixin` — `created_at` is set once at INSERT only.
    `updated_at` would be misleading for an append-only table.
    """

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )

    # Who accessed the data
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.UUID(as_uuid=True),
        nullable=True,
        comment="AppUser.id of the actor; NULL for system/agent actions",
    )
    user_role: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)

    # What was accessed
    resource_type: Mapped[str] = mapped_column(
        sa.String(64),
        nullable=False,
        comment="e.g., 'patient', 'encounter', 'document', 'medication'",
    )
    resource_id: Mapped[str] = mapped_column(
        sa.String(128),
        nullable=False,
        comment="String representation of the resource primary key",
    )
    action: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        comment="One of: read, create, update, delete, approve, export",
    )

    # Request context (no PHI in these fields — log sanitiser strips it)
    ip_address: Mapped[str | None] = mapped_column(sa.String(45), nullable=True)
    request_id: Mapped[str | None] = mapped_column(
        sa.String(128),
        nullable=True,
        comment="Distributed trace ID for correlation with Cloud Logging",
    )

    outcome: Mapped[str] = mapped_column(
        sa.String(16),
        nullable=False,
        server_default="success",
        comment="One of: success, denied, error",
    )

    __table_args__ = (
        sa.Index("ix_audit_log_user_id", "user_id"),
        sa.Index("ix_audit_log_resource", "resource_type", "resource_id"),
        sa.Index("ix_audit_log_created_at", "created_at"),
    )
```

### 6. Author `backend/app/models/chatbot_transcript.py`

```python
"""ChatbotTranscript ORM model — patient chatbot conversation messages.

DR-016: Encrypted and retained 7 years with encounter.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.encryption import EncryptedString
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    pass


class ChatbotTranscript(Base, TimestampMixin):
    """Single message in a patient–chatbot conversation.

    `message_content` is encrypted at rest (DR-016, US-007).
    Urgency detection flag set by the Patient Communication Agent (FR-063).
    """

    __tablename__ = "chatbot_transcript"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    encounter_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("encounter.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Message direction
    role: Mapped[str] = mapped_column(
        sa.String(16),
        nullable=False,
        comment="One of: patient, assistant — identifies message sender",
    )

    # PHI-containing content encrypted via US-007 (DR-016)
    message_content: Mapped[str] = mapped_column(
        EncryptedString,
        nullable=False,
        comment="Encrypted chatbot message body (DR-016)",
    )

    is_urgent: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.false(),
        comment="Set True by Patient Communication Agent on urgency detection (FR-063)",
    )

    escalated_at: Mapped[sa.DateTime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when urgency escalation was sent to care team",
    )

    __table_args__ = (
        sa.Index("ix_chatbot_encounter_id", "encounter_id"),
        sa.Index("ix_chatbot_urgent", "encounter_id", "is_urgent"),
    )
```

### 7. Update `backend/app/models/__init__.py`

```python
from app.models.adt_event import AdtEvent
from app.models.agent_task import AgentTask
from app.models.app_user import AppUser
from app.models.bed import Bed
from app.models.chatbot_transcript import ChatbotTranscript
from app.models.document import Document
from app.models.encounter import Encounter, EncounterStatus, RiskTier
from app.models.medication import Medication
from app.models.patient import Patient
from app.models.audit_log import AuditLog

__all__ = [
    "AdtEvent",
    "AgentTask",
    "AppUser",
    "AuditLog",
    "Bed",
    "ChatbotTranscript",
    "Document",
    "Encounter",
    "EncounterStatus",
    "Medication",
    "Patient",
    "RiskTier",
]
```

---

## Definition of Done

- [ ] `adt_event` model defines `source_message_id` with `unique=True` and `Index("ix_adt_event_source_message_id", unique=True)` (DR-022)
- [ ] `agent_task` model defines `UniqueConstraint("encounter_id", "agent_type", "pubsub_message_id")` for idempotency (AR-008)
- [ ] `document` model uses `EncryptedString` for `content` column (DR-013 / DR-002)
- [ ] `audit_log` model does NOT inherit `TimestampMixin` (no `updated_at` — append-only semantics)
- [ ] `chatbot_transcript` model uses `EncryptedString` for `message_content` (DR-016)
- [ ] `backend/app/models/__init__.py` exports all 10 models
- [ ] All FK relationships have explicit `ondelete` behavior (`CASCADE`, `RESTRICT`, or `SET NULL`)
- [ ] All models have at least one index beyond the primary key

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-002 | Preceding task | `Base`, `TimestampMixin` must exist |
| TASK-003 | Preceding task | `Patient` model (FK target for several models) |
| TASK-004 | Preceding task | `Encounter` model (FK target for all 6 models here) |
| US-007 | Story (parallel) | `EncryptedString` TypeDecorator; stub acceptable until US-007 merges |

---

## Files Modified

| File | Action |
|---|---|
| `backend/app/models/adt_event.py` | Create |
| `backend/app/models/medication.py` | Create |
| `backend/app/models/agent_task.py` | Create |
| `backend/app/models/document.py` | Create |
| `backend/app/models/audit_log.py` | Create |
| `backend/app/models/chatbot_transcript.py` | Create |
| `backend/app/models/__init__.py` | Update (all 10 models exported) |
