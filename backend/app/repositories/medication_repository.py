"""Read queries for medication reconciliation results.

Provides database access for the medication reconciliation API endpoint
(US-030/TASK-005). All queries are read-only and use the read replica
session when called from GET endpoints.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.encounter import Encounter
from app.models.medication import Medication


async def get_reconciliation_results(
    encounter_id: UUID,
    session: AsyncSession,
) -> list[Medication]:
    """Return all Medication records for an encounter, ordered by category then name.
    
    Results are ordered by reconciliation_category (nulls last) then drug name
    for consistent presentation in the API response.
    
    Args:
        encounter_id: The encounter UUID to query medications for.
        session: Active async SQLAlchemy session (read or write).
    
    Returns:
        List of Medication ORM instances. Empty list if no records found.
        Caller interprets empty list with no completed timestamp as "pending".
    """
    stmt = (
        select(Medication)
        .where(Medication.encounter_id == encounter_id)
        .order_by(
            Medication.reconciliation_category.nullslast(),
            Medication.drug_name,
        )
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_reconciliation_completed_at(
    encounter_id: UUID,
    session: AsyncSession,
) -> datetime | None:
    """Return reconciliation completion timestamp for the encounter if available.
    
    Queries for any medication record with a non-null reconciliation_completed_at
    timestamp. Returns the first match found (all medications for an encounter
    should have the same completion timestamp when reconciliation finishes).
    
    Args:
        encounter_id: The encounter UUID to check completion status for.
        session: Active async SQLAlchemy session (read or write).
    
    Returns:
        datetime object if reconciliation completed, None if pending or not started.
    """
    stmt = (
        select(Medication.reconciliation_completed_at)
        .where(
            Medication.encounter_id == encounter_id,
            Medication.reconciliation_completed_at.isnot(None),
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_all_medications(
    session: AsyncSession,
) -> list[Medication]:
    """Return all Medication records across all encounters.

    Ordered by encounter_id then drug name for stable presentation.

    Args:
        session: Active async SQLAlchemy session (read or write).

    Returns:
        List of Medication ORM instances.
    """
    stmt = (
        select(Medication)
        .order_by(
            Medication.encounter_id,
            Medication.drug_name,
        )
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_medication_history_for_patient(
    current_encounter_id: UUID,
    patient_id: UUID,
    session: AsyncSession,
    limit: int = 10,
) -> list[tuple[Encounter, list[Medication]]]:
    """Return medication reconciliation results for prior encounters of a patient.

    Results are grouped by encounter and ordered by most-recent encounter first.
    The current encounter is excluded so the caller can compare it against history.

    Args:
        current_encounter_id: The encounter being viewed (excluded from history).
        patient_id: Patient UUID whose history is being queried.
        session: Active async SQLAlchemy session (read or write).
        limit: Maximum number of prior encounters to return.

    Returns:
        List of (Encounter, [Medication]) tuples for prior encounters.
    """
    stmt = (
        select(Medication, Encounter)
        .join(Encounter, Medication.encounter_id == Encounter.id)
        .where(
            Encounter.patient_id == patient_id,
            Encounter.id != current_encounter_id,
            Encounter.deleted_at.is_(None),
        )
        .order_by(Encounter.created_at.desc(), Medication.drug_name)
    )
    result = await session.execute(stmt)

    encounters_map: dict[UUID, tuple[Encounter, list[Medication]]] = {}
    for med, enc in result.all():
        if enc.id not in encounters_map:
            encounters_map[enc.id] = (enc, [])
        encounters_map[enc.id][1].append(med)

    ordered = sorted(
        encounters_map.values(),
        key=lambda pair: pair[0].created_at or datetime.min,
        reverse=True,
    )
    return ordered[:limit]
