"""Pydantic response schemas for AgentTask API endpoints.

US-021 Scenario 2: Response must include id, agent_type, status, start_time,
completed_time, sla_threshold_minutes, sla_breached.
US-023: Response includes checklist field with generated items as structured JSON array.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.config.sla_loader import load_sla_config


class AgentTaskResponse(BaseModel):
    """Response schema for a single AgentTask.

    All seven fields required by US-021 Scenario 2 are present.
    `sla_threshold_minutes` is backfilled from SLAConfig if NULL in DB
    (handles tasks created before TASK-002 migration).
    
    US-023: Includes `checklist` and `checklist_generated_type` fields for
    coordinator tasks with AI-generated or template handoff checklists.
    """

    id: UUID
    agent_type: str
    status: str
    start_time: datetime = Field(alias="created_at")
    completed_time: datetime | None = Field(None, alias="completed_at")
    sla_threshold_minutes: int | None
    sla_breached: bool
    
    # US-023: AI-generated or template handoff checklist fields
    checklist: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "AI-generated or template handoff checklist items. "
            "Present on coordinator tasks for encounters with ADT events."
        ),
    )
    checklist_generated_type: str | None = Field(
        default=None,
        description="Source of checklist: 'LLM' or 'TEMPLATE' (fallback).",
    )
    
    # US-026: Document completeness fields for DOCUMENTATION tasks
    document_id: UUID | None = Field(
        default=None,
        description="Document ID for DOCUMENTATION tasks (US-026).",
    )
    generation_type: str | None = Field(
        default=None,
        description="Document generation type: 'AI' or 'TEMPLATE' (US-026).",
    )
    completeness_status: str | None = Field(
        default=None,
        description="Document completeness status: 'COMPLETE' or 'INCOMPLETE' (US-026).",
    )
    missing_fields: list[str] = Field(
        default_factory=list,
        description="List of missing required fields for INCOMPLETE documents (US-026).",
    )

    # Structured agent output/results surfaced in the task monitor UI
    output: dict[str, Any] | None = Field(
        default=None,
        description="Structured agent output: bed assignment, document id, risk score, etc.",
    )

    model_config = {"populate_by_name": True, "from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _extract_checklist_from_metadata(cls, data: Any) -> Any:
        """Extract checklist fields from metadata JSONB if present.
        
        When serializing from ORM, the metadata field contains a dict with
        checklist data. This validator extracts it to top-level fields.
        """
        if isinstance(data, dict):
            metadata = data.get("metadata") or {}
            if isinstance(metadata, dict):
                # Extract checklist fields from metadata
                if "checklist" in metadata:
                    data["checklist"] = metadata.get("checklist")
                if "generated_type" in metadata:
                    data["checklist_generated_type"] = metadata.get("generated_type")
        return data

    @model_validator(mode="after")
    def _backfill_sla_threshold(self) -> "AgentTaskResponse":
        """Backfill sla_threshold_minutes from SLAConfig if not yet set in DB."""
        if self.sla_threshold_minutes is None:
            config = load_sla_config()
            self.sla_threshold_minutes = config.threshold_for(
                (self.agent_type or "").upper()
            )
        return self


class AgentTaskListResponse(BaseModel):
    """Paginated list of AgentTask records for an encounter."""

    encounter_id: UUID
    tasks: list[AgentTaskResponse]
    total: int


class DocumentationTaskDetail(BaseModel):
    """
    Detail block for the DOCUMENTATION agent task entry in the encounter tasks response.

    Fields added by US-026:
      - completeness_status: "COMPLETE", "INCOMPLETE", or None (not yet validated).
      - missing_fields: list of absent required field names. Empty list when COMPLETE.
    """
    document_id: str | None = None
    generation_type: str | None = None
    completeness_status: str | None = None      # US-026
    missing_fields: list[str] = Field(default_factory=list)  # US-026


class EncounterTaskEntry(BaseModel):
    """Single task entry in the encounter tasks list."""
    task_type: str          # e.g. "DOCUMENTATION", "MEDICATION_RECONCILIATION"
    status: str             # e.g. "COMPLETE", "IN_PROGRESS", "PENDING"
    details: DocumentationTaskDetail | None = None
