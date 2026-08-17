"""Pydantic schemas for physician alert create/read/resolve operations.

Design refs:
    US-030 extension — Physician medication review alert surfaced after
    medication reconciliation runs for an encounter.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class PhysicianAlertCreate(BaseModel):
    """Request body for creating a physician alert."""

    alert_type: Literal["MEDICATION_REVIEW"] = "MEDICATION_REVIEW"
    severity: Literal["HIGH", "MEDIUM", "LOW"] = "MEDIUM"
    title: str = Field(..., max_length=255)
    message: str | None = Field(default=None, max_length=4000)
    patient_id: uuid.UUID | None = None
    metadata_: dict[str, Any] | None = Field(default=None, alias="metadata")

    model_config = {"populate_by_name": True}


class PhysicianAlertRead(PhysicianAlertCreate):
    """Response body for a physician alert."""

    id: uuid.UUID
    encounter_id: uuid.UUID
    status: str
    resolved_by_user_id: uuid.UUID | None = None
    resolved_at: datetime | None = None
    resolution_type: str | None = None
    resolution_note: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


class PhysicianAlertResolveRequest(BaseModel):
    """Request body for resolving a physician alert."""

    resolution_type: str = Field(
        ...,
        pattern="^(REVIEWED_ACCEPTABLE|MEDICATION_UPDATED|MEDICATION_ADDED|DISMISSED)$",
    )
    resolution_note: str | None = Field(default=None, max_length=2000)
