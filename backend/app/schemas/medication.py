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


class MedicationHistoryEncounter(BaseModel):
    """Medication reconciliation results for a single prior encounter."""

    encounter_id: UUID = Field(
        ...,
        description="Encounter UUID for this historical snapshot",
    )

    status: str = Field(
        ...,
        description="Encounter status at the time of the snapshot",
    )

    created_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp when the encounter was created",
    )

    total_medications: int = Field(
        ...,
        description="Number of medications reconciled for that encounter",
        ge=0,
    )

    medications: list[MedicationReconciliationResult] = Field(
        default_factory=list,
        description="List of reconciled medications for that encounter",
    )

    model_config = {"from_attributes": True}


class MedicationHistoryResponse(BaseModel):
    """Full medication history response for the current encounter's patient."""

    current_encounter_id: UUID = Field(
        ...,
        description="Encounter UUID whose history is being viewed",
    )

    patient_id: UUID = Field(
        ...,
        description="Patient UUID owning the encounter history",
    )

    history: list[MedicationHistoryEncounter] = Field(
        default_factory=list,
        description="Prior encounters with reconciled medications, most recent first",
    )

    model_config = {"from_attributes": True}


class MedicationAnalysisResponse(BaseModel):
    """AI-powered medication change analysis and readmission prediction."""

    encounter_id: UUID = Field(
        ...,
        description="Encounter UUID analysed",
    )

    summary: str = Field(
        ...,
        description="Plain-language summary of medication-related risks",
    )

    readmission_risk: str = Field(
        ...,
        description="Predicted 30-day readmission risk: HIGH | MEDIUM | LOW",
    )

    confidence: str = Field(
        ...,
        description="Confidence in the prediction: HIGH | MEDIUM | LOW",
    )

    safety_score: int = Field(
        ...,
        ge=0,
        le=100,
        description="Medication safety score where higher is safer (0-100)",
    )

    risks: list[str] = Field(
        default_factory=list,
        description="Identified medication risks",
    )

    recommendations: list[str] = Field(
        default_factory=list,
        description="Clinical recommendations based on the analysis",
    )

    predicted_issues: list[str] = Field(
        default_factory=list,
        description="Predicted adverse events or issues within 30 days",
    )

    model_config = {"from_attributes": True}
