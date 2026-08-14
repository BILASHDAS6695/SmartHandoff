"""
Pydantic schemas for Document API request/response contracts.

ChangeLogEntry is the canonical diff record format stored in
Document.metadata['change_log'] (JSONB). All fields are required to satisfy
HIPAA audit trail requirements (BR-001).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class DocumentStatus(str, Enum):
    """Document lifecycle states (FR-024, US-028 Scenario 3 & 4)."""

    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ChangeLogEntry(BaseModel):
    """
    Single auditable change record appended to Document.metadata['change_log'].

    Produced by the diff engine on every auto-save (debounced 2 s, Scenario 2).
    Immutable once written — append-only semantics enforced at ORM layer.
    """

    field: str = Field(
        ...,
        description="Top-level section key that was changed, e.g. 'medications_at_discharge'.",
    )
    old_value: Any = Field(
        ...,
        description="Previous field value (string or nested object) before the edit.",
    )
    new_value: Any = Field(
        ...,
        description="New field value after the edit.",
    )
    author_id: UUID = Field(
        ...,
        description="UUID of the authenticated user who made the change.",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the change was recorded.",
    )

    model_config = {"frozen": True}  # Immutable once created


class DocumentSaveDraftRequest(BaseModel):
    """
    Request body for PATCH /api/v1/documents/{id} (auto-save / save-draft).

    `diff` contains only the fields that changed in this edit cycle.
    The backend appends one ChangeLogEntry per key in `diff`.
    """

    content: dict = Field(
        ...,
        description="Full updated document content (structured sections as JSON object).",
    )
    diff: dict[str, dict[str, Any]] = Field(
        ...,
        description=(
            "Field-level diff map: {field_name: {old_value: ..., new_value: ...}}. "
            "One ChangeLogEntry is written per key."
        ),
    )


class DocumentApproveRequest(BaseModel):
    """Request body for PATCH /api/v1/documents/{id}/approve."""

    notes: Optional[str] = Field(
        default=None,
        description="Optional physician notes recorded at approval time.",
        max_length=1000,
    )


class DocumentRejectRequest(BaseModel):
    """Request body for PATCH /api/v1/documents/{id}/reject (Scenario 4 — all reviewers)."""

    rejection_reason: str = Field(
        ...,
        description="Mandatory reason for rejection. Stored in Document.metadata.",
        min_length=10,
        max_length=2000,
    )


class ChangeLogEntryResponse(BaseModel):
    """Serialised ChangeLogEntry for API responses (change log timeline)."""

    field: str
    old_value: Any
    new_value: Any
    author_id: UUID
    timestamp: datetime
    author_display_name: Optional[str] = None  # Joined from User table at query time


class DocumentResponse(BaseModel):
    """
    API response schema for a Document resource.

    Extends the base schema with US-029 provenance and approval fields.
    Used by approve endpoint and portal endpoint to surface document metadata.
    """

    id: UUID = Field(description="Document primary key")
    encounter_id: UUID = Field(description="Foreign key to encounter")
    document_type: str = Field(description="One of: discharge_summary, patient_instructions, etc.")
    content: dict | str = Field(description="Document structured content (decrypted) or raw text")
    language_code: str = Field(default="en", description="Document language (en, es, fr, zh, pt)")
    status: str = Field(description="Document status (draft, pending_approval, approved, rejected)")
    generation_type: str = Field(description="LLM or TEMPLATE")
    completeness_status: Optional[str] = Field(default=None, description="COMPLETE or INCOMPLETE")
    missing_fields: Optional[list] = Field(default=None, description="List of missing required fields")
    created_at: datetime = Field(description="UTC timestamp of document creation")
    updated_at: datetime = Field(description="UTC timestamp of last update")

    # ── US-029 provenance / approval fields ───────────────────────────────────
    ai_assisted_label: bool = Field(
        description="TRUE for all AI-generated documents (permanent provenance flag).",
    )
    approved_at: Optional[datetime] = Field(
        default=None,
        description="UTC timestamp of clinician approval; NULL for unapproved documents.",
    )
    reviewed_by_user_id: Optional[UUID] = Field(
        default=None,
        description="UUID of the approving clinician.",
    )
    reviewed_by_display_name: Optional[str] = Field(
        default=None,
        description="Resolved display name for the 'Approved by' footer.",
    )

    model_config = {"from_attributes": True}

    @field_validator("content", mode="before")
    @classmethod
    def _parse_json_content(cls, value: Any) -> Any:
        """Decrypting the ORM may return a JSON string or plain text; normalise when possible."""
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value
