"""Pydantic request/response schemas for the SignalR hub broadcast endpoint.

US-022 DoD: POST /api/v1/signalr/task-updated
Group naming convention: encounter-{id}, unit-{unitId}, role-{roleName}
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


# Matches the AgentTask status enum from US-020/US-021.
AgentTaskStatus = Literal[
    "PENDING", "IN_PROGRESS", "COMPLETED", "FAILED", "ESCALATED", "PENDING_APPROVAL", "CANCELLED"
]


class TaskUpdatedPayload(BaseModel):
    """Payload sent by agents after each status transition.

    Fields forwarded verbatim inside the SignalR `task_updated` event data.
    US-022 Scenario 1: status field captures IN_PROGRESS → COMPLETED transitions.
    """

    task_id: UUID = Field(..., description="AgentTask primary key")
    encounter_id: UUID = Field(..., description="Parent encounter; maps to group encounter-{id}")
    unit_id: str = Field(..., description="Hospital unit; maps to group unit-{unitId}")
    role_name: str = Field(..., description="Target clinical role; maps to group role-{roleName}")
    agent_type: str = Field(..., description="Agent that changed state, e.g. DOCUMENTATION")
    previous_status: AgentTaskStatus
    new_status: AgentTaskStatus
    updated_at: datetime = Field(..., description="Timestamp of DB write — used for latency tracking")


class BedStatusChangedPayload(BaseModel):
    """Payload sent when a bed's status is manually updated.

    Emitted by PATCH /api/v1/beds/{id}/status and by the bed-suggestion
    assignment flow so the bed board refreshes in real time.
    """

    bed_id: str = Field(..., description="UUID of the bed record")
    bed_number: str = Field(..., description="Human-readable bed identifier")
    patient_unit: str = Field(..., description="Unit the bed belongs to")
    status: str = Field(..., description="New bed status")
    encounter_id: str | None = Field(None, description="Assigned encounter UUID if any")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class BedSuggestionPayload(BaseModel):
    """Payload sent when the Bed Management Agent creates a ranked suggestion.

    Delivered to bed-manager clients via the role-bed_manager group so the
    ED boarding alert appears in real time without a page refresh.
    """

    task_id: str
    encounter_id: str
    patient_name: str
    current_unit: str | None = None
    acuity: str
    minutes_waiting: int | None = None
    best_bed_id: str
    best_bed_number: str
    best_bed_unit: str
    suggestions: list[dict] = []
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class BoardingAlertPayload(BaseModel):
    """In-app notification payload for ED boarding alerts (SignalR).

    Mirrors the Pub/Sub payload used by BoardingAlertPublisher but adds
    display fields for the notification tray and bed board alert banner.
    """

    alert_id: str
    encounter_id: str
    patient_name: str | None = None
    patient_unit: str
    minutes_elapsed: int
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "HIGH"
    title: str
    message: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class BroadcastRequest(BaseModel):
    """Internal broadcast request forwarded to Azure SignalR REST API.

    target: SignalR event name received by Angular HubConnection.on('task_updated', ...)
    arguments: single-element list containing the serialised TaskUpdatedPayload.
    """

    target: str = "task_updated"
    arguments: list[dict]
