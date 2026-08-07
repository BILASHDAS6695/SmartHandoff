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


class EncounterCreateRequest(BaseModel):
    """Request body for creating a new encounter."""

    patient_id: uuid.UUID = Field(..., description="UUID of the linked patient")
    status: EncounterStatusEnum = Field(default=EncounterStatusEnum.REGISTERED)
    unit: str | None = Field(default=None, description="Current unit assignment")
    risk_tier: str = Field(default="UNKNOWN")


class EncounterUpdateRequest(BaseModel):
    """Request body for updating an existing encounter."""

    status: EncounterStatusEnum | None = Field(default=None)
    unit: str | None = Field(default=None)
    risk_tier: str | None = Field(default=None)


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
