"""Pydantic schemas for encounter API write requests and basic responses."""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class EncounterStatusEnum(str, Enum):
    """Allowed encounter lifecycle states for request validation."""

    REGISTERED = "REGISTERED"
    PRE_ADMISSION = "PRE_ADMISSION"
    ADMITTED = "ADMITTED"
    TRANSFERRED = "TRANSFERRED"
    DISCHARGED = "DISCHARGED"


class AdtEventType(str, Enum):
    """HL7 ADT event types that can trigger agent workflows."""

    A01 = "A01"  # Admit
    A02 = "A02"  # Transfer
    A03 = "A03"  # Discharge
    A04 = "A04"  # Registration
    A08 = "A08"  # Update
    A11 = "A11"  # Cancel admit
    A12 = "A12"  # Cancel transfer
    A13 = "A13"  # Cancel discharge


class EncounterCreateRequest(BaseModel):
    """Request body for creating a new encounter."""

    patient_id: uuid.UUID = Field(..., description="UUID of the linked patient")
    status: EncounterStatusEnum = Field(default=EncounterStatusEnum.REGISTERED)
    unit: str | None = Field(default=None, description="Current unit assignment")
    risk_tier: str = Field(default="UNKNOWN")
    event_type: AdtEventType | None = Field(
        default=None,
        description="HL7 ADT event type that triggered this encounter creation; drives agent task orchestration",
    )


class EncounterUpdateRequest(BaseModel):
    """Request body for updating an existing encounter."""

    status: EncounterStatusEnum | None = Field(default=None)
    unit: str | None = Field(default=None)
    risk_tier: str | None = Field(default=None)
    event_type: AdtEventType | None = Field(
        default=None,
        description="HL7 ADT event type that triggered this encounter update; drives agent task orchestration",
    )


class EncounterWriteResponse(BaseModel):
    """Encounter response payload after create or update."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    status: str
    unit: str | None
    risk_tier: str
    created_at: datetime
    updated_at: datetime
