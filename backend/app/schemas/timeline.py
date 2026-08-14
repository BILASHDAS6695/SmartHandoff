"""Pydantic schemas for the encounter realtime timeline API."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class TimelineEvent(BaseModel):
    """A single event in the encounter timeline.

    The timeline aggregates heterogeneous encounter-related records (ADT events,
    agent tasks, documents, pharmacist alerts, medication reconciliation,
    audit actions) into a chronologically sorted, human-readable feed.
    """

    event_type: str = Field(
        ...,
        description=(
            "Category of timeline event: admission, transfer, discharge, "
            "agent_task, document, alert, medication, system, cancellation, "
            "approval, rejection, resolution, encounter_created."
        ),
    )
    title: str = Field(..., description="Short human-readable title.")
    description: str | None = Field(default=None, description="Optional detail text.")
    timestamp: datetime | None = Field(
        default=None, description="UTC timestamp when the event occurred."
    )
    status: str | None = Field(
        default=None, description="Status of the underlying resource, if applicable."
    )
    resource_type: str | None = Field(
        default=None,
        description="Backend resource type, e.g. AgentTask, Document, PharmacistAlert.",
    )
    resource_id: UUID | None = Field(
        default=None, description="UUID of the underlying resource."
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional structured context, e.g. severity, agent_type, document_type.",
    )

    model_config = {"from_attributes": True}


class EncounterTimelineResponse(BaseModel):
    """Response envelope for GET /api/v1/encounters/{id}/timeline."""

    encounter_id: UUID
    events: list[TimelineEvent]
    total: int
