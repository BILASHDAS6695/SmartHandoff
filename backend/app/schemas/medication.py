"""Pydantic schemas for medication reconciliation API responses.

Used by US-030 Medication Reconciliation Agent endpoints.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.medication import (
    ReconciliationCategory,
    ReconciliationFlag,
    MedicationListSource,
)


class MedicationReconciliationResult(BaseModel):
    """Per-drug reconciliation result returned by the API.
    
    Represents a single medication with its reconciliation status,
    which FHIR lists it appears on, and any flags raised during
    the reconciliation process.
    """

    id: UUID = Field(
        ...,
        description="Unique identifier for this medication record",
    )
    
    name: str = Field(
        ...,
        description="Display drug name from FHIR",
    )
    
    rxnorm_cui: Optional[str] = Field(
        default=None,
        description="RxNorm Concept Unique Identifier from RxNav API",
    )
    
    reconciliation_category: Optional[ReconciliationCategory] = Field(
        default=None,
        description="Reconciliation outcome: CONTINUED | NEW | STOPPED | DOSE_CHANGED",
    )
    
    pre_admit: bool = Field(
        ...,
        description="True if drug was on pre-admission list",
    )
    
    inpatient: bool = Field(
        ...,
        description="True if drug was on inpatient list",
    )
    
    discharge: bool = Field(
        ...,
        description="True if drug is on discharge list",
    )
    
    flags: list[ReconciliationFlag] = Field(
        default_factory=list,
        description="Alert flags: DUPLICATE | STOPPED_WITHOUT_ORDER",
    )
    
    dose: Optional[str] = Field(
        default=None,
        description="Human-readable dose string e.g. 500mg",
    )
    
    route: Optional[str] = Field(
        default=None,
        description="Administration route e.g. oral, IV",
    )
    
    frequency: Optional[str] = Field(
        default=None,
        description="Dosing frequency e.g. twice daily, BID",
    )
    
    interaction_severity: Optional[str] = Field(
        default=None,
        description="RxNav interaction severity: HIGH | MEDIUM | LOW (AIR-051)",
    )

    model_config = {"from_attributes": True}


class MedicationReconciliationResponse(BaseModel):
    """Full reconciliation response for an encounter.
    
    Returned by GET /api/v1/encounters/{id}/medications/reconciliation
    Contains all medications for the encounter with their reconciliation
    status and metadata.
    """

    encounter_id: UUID = Field(
        ...,
        description="Encounter ID for which reconciliation was performed",
    )
    
    total_medications: int = Field(
        ...,
        description="Total number of medications in the reconciliation",
        ge=0,
    )
    
    reconciliation_completed_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp when reconciliation was completed",
    )

    reconciliation_completed_by: Optional[str] = Field(
        default=None,
        description="User ID who completed the reconciliation",
    )
    
    medications: list[MedicationReconciliationResult] = Field(
        default_factory=list,
        description="List of reconciled medications with details",
    )

    model_config = {"from_attributes": True}
