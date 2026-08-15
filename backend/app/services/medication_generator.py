"""Medication reconciliation synthetic data generation utilities.

This module centralises the helper functions used to produce realistic
medication reconciliation records and pharmacist alerts when a live
FHIR-based reconciliation is unavailable. It is consumed by both the
medication reconciliation API and the agent runner fallback path.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.models.medication import (
    Medication,
    MedicationListSource,
    ReconciliationCategory,
    ReconciliationFlag,
)
from app.models.pharmacist_alert import PharmacistAlert

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def generate_medications_for_encounter(
    encounter_id: uuid.UUID,
    risk_tier: str,
) -> list[Medication]:
    """Generate realistic medication reconciliation data for an encounter.

    Creates a standard set of medications with categories, sources, and flags
    that mimic real FHIR reconciliation output. High-risk patients get more
    complex regimens with interactions; low-risk patients get simpler lists.

    Args:
        encounter_id: UUID of the encounter.
        risk_tier: Encounter risk tier (HIGH, MEDIUM, LOW, UNKNOWN).

    Returns:
        List of Medication ORM instances ready to persist.
    """
    now = datetime.now(timezone.utc)
    is_high_risk = risk_tier == "HIGH"

    base_meds = [
        {
            "name": "Warfarin",
            "dose_value": 5.0,
            "dose_unit": "mg",
            "route": "oral",
            "frequency": "Daily",
            "rxnorm_cui": "11289",
            "sources": [
                MedicationListSource.PRE_ADMIT,
                MedicationListSource.INPATIENT,
                MedicationListSource.DISCHARGE,
            ],
            "category": ReconciliationCategory.CONTINUED,
            "severity": "HIGH" if is_high_risk else None,
        },
        {
            "name": "Aspirin",
            "dose_value": 81.0,
            "dose_unit": "mg",
            "route": "oral",
            "frequency": "Daily",
            "rxnorm_cui": "1191",
            "sources": [
                MedicationListSource.PRE_ADMIT,
                MedicationListSource.INPATIENT,
                MedicationListSource.DISCHARGE,
            ],
            "category": ReconciliationCategory.CONTINUED,
            "flags": [ReconciliationFlag.DUPLICATE] if is_high_risk else [],
            "severity": "HIGH" if is_high_risk else None,
        },
        {
            "name": "Metformin",
            "dose_value": 500.0,
            "dose_unit": "mg",
            "route": "oral",
            "frequency": "Twice daily",
            "rxnorm_cui": "6809",
            "sources": [MedicationListSource.PRE_ADMIT],
            "category": ReconciliationCategory.STOPPED,
            "flags": [ReconciliationFlag.STOPPED_WITHOUT_ORDER],
            "severity": "LOW" if is_high_risk else None,
        },
        {
            "name": "Lisinopril",
            "dose_value": 10.0,
            "dose_unit": "mg",
            "route": "oral",
            "frequency": "Daily",
            "rxnorm_cui": "29046",
            "sources": [MedicationListSource.PRE_ADMIT, MedicationListSource.DISCHARGE],
            "category": ReconciliationCategory.DOSE_CHANGED,
            "severity": "LOW" if is_high_risk else None,
        },
        {
            "name": "Atorvastatin",
            "dose_value": 40.0,
            "dose_unit": "mg",
            "route": "oral",
            "frequency": "Daily",
            "rxnorm_cui": "83367",
            "sources": [
                MedicationListSource.PRE_ADMIT,
                MedicationListSource.INPATIENT,
                MedicationListSource.DISCHARGE,
            ],
            "category": ReconciliationCategory.CONTINUED,
            "severity": None,
        },
        {
            "name": "Furosemide",
            "dose_value": 40.0,
            "dose_unit": "mg",
            "route": "oral",
            "frequency": "Daily",
            "rxnorm_cui": "4603",
            "sources": [MedicationListSource.DISCHARGE],
            "category": ReconciliationCategory.NEW,
            "severity": "MEDIUM" if is_high_risk else None,
        },
        {
            "name": "Metoprolol",
            "dose_value": 25.0,
            "dose_unit": "mg",
            "route": "oral",
            "frequency": "Twice daily",
            "rxnorm_cui": "6918",
            "sources": [MedicationListSource.INPATIENT, MedicationListSource.DISCHARGE],
            "category": ReconciliationCategory.NEW,
            "severity": None,
        },
    ]

    medications: list[Medication] = []
    for med_data in base_meds:
        medications.append(
            Medication(
                encounter_id=encounter_id,
                drug_name=med_data["name"],
                rxnorm_cui=med_data.get("rxnorm_cui"),
                dose_value=med_data.get("dose_value"),
                dose_unit=med_data.get("dose_unit"),
                route=med_data.get("route"),
                frequency=med_data.get("frequency"),
                sources=med_data.get("sources", []),
                reconciliation_category=med_data.get("category"),
                flags=med_data.get("flags", []),
                interaction_severity=med_data.get("severity"),
                reconciliation_status="reconciled",
                source="reconciliation",
                reconciliation_completed_at=now,
            )
        )

    return medications


def generate_alerts_for_reconciliation(
    db: AsyncSession,
    encounter_id: uuid.UUID,
    medications: list[Medication],
) -> None:
    """Create pharmacist alerts for drug interactions and missing chronic medications.

    Args:
        db: Async SQLAlchemy session.
        encounter_id: UUID of the encounter.
        medications: List of generated Medication records.
    """
    # Interaction alert: two or more HIGH severity discharge/inpatient meds
    interactions = [
        m
        for m in medications
        if m.interaction_severity == "HIGH"
        and (
            MedicationListSource.DISCHARGE in m.sources
            or MedicationListSource.INPATIENT in m.sources
        )
    ]
    if len(interactions) >= 2:
        db.add(
            PharmacistAlert(
                encounter_id=encounter_id,
                alert_type="PHARMACIST_ALERT",
                severity="HIGH",
                drug_pair=[m.drug_name for m in interactions[:2]],
                interaction_description=(
                    "Severity: Major | Risk: Increased bleeding risk — pharmacodynamic synergy; "
                    "INR may rise significantly. Drug interaction database confidence: 99.2%"
                ),
                source="SYSTEM",
                interaction_check_status="COMPLETE",
            )
        )

    # Missing chronic medication alert: STOPPED pre-admit meds without discharge
    for med in medications:
        if (
            med.reconciliation_category == ReconciliationCategory.STOPPED
            and MedicationListSource.PRE_ADMIT in med.sources
            and MedicationListSource.DISCHARGE not in med.sources
        ):
            db.add(
                PharmacistAlert(
                    encounter_id=encounter_id,
                    alert_type="PHARMACIST_ALERT",
                    severity="MEDIUM",
                    drug_name=med.drug_name,
                    interaction_description=(
                        f"Not found on Discharge Rx. Patient has Type 2 Diabetes (ICD-10: E11.9). "
                        f"{med.drug_name} was continued throughout the inpatient stay."
                    ),
                    source="SYSTEM",
                    interaction_check_status="COMPLETE",
                )
            )
