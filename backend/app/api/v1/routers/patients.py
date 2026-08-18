"""Patient resource router — RBAC-protected endpoints."""
from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.jwt import TokenClaims
from app.core.auth.rbac import require_permission
from app.db.deps import get_write_db
from app.db.encryption import _decrypt
from app.models.bed import Bed
from app.models.encounter import Encounter, EncounterStatus
from app.models.patient import Patient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/patients", tags=["patients"])


def _safe_decrypt(ciphertext: str | None) -> str:
    """Decrypt PHI, falling back to plaintext if the value was stored unencrypted."""
    if not ciphertext:
        return ""
    try:
        return _decrypt(ciphertext).decode("utf-8")
    except Exception:
        logger.warning("Failed to decrypt PHI value; treating as plaintext.")
        return ciphertext


@router.get("")
async def list_patients(
    current_user: Annotated[TokenClaims, Depends(require_permission("patient", "list"))],
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    unit: str = Query(""),
    search: str = Query(""),
    status: str = Query(""),
    unique: bool = Query(False, description="Return one row per unique patient instead of one row per encounter."),
    # NOTE: Uses get_write_db for local dev — both read and write point to same database
    db: AsyncSession = Depends(get_write_db),
) -> dict:
    """List patients — requires patient:list permission.

    By default returns encounter-level rows (room_number, current_unit, status).
    Set ``unique=true`` to return one de-duplicated row per patient with a count
    of active encounters and the most recent encounter status.
    """
    try:
        logger.info(
            f"Fetching patients: page={page}, page_size={page_size}, unit={unit}, "
            f"search={search}, status={status}, unique={unique}"
        )

        if unique:
            return await _list_unique_patients(db, page, page_size, search)

        return await _list_encounter_patients(db, page, page_size, unit, search, status)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error fetching patients: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch patients: {str(e)}")


async def _list_unique_patients(
    db: AsyncSession,
    page: int,
    page_size: int,
    search: str,
) -> dict:
    """Return one row per unique patient with active-encounter metadata."""
    search_term = search.strip().lower()

    active_statuses = [
        EncounterStatus.REGISTERED.value,
        EncounterStatus.PRE_ADMISSION.value,
        EncounterStatus.ADMITTED.value,
        EncounterStatus.TRANSFERRED.value,
    ]

    # Aggregate encounter data per patient. Use a window function to pick the
    # most recent encounter row per patient so we can read its id, status, and
    # risk tier without using max(uuid), which PostgreSQL does not support.
    ranked_encounters = (
        select(
            Encounter.patient_id,
            Encounter.id.label("encounter_id"),
            Encounter.status.label("latest_status"),
            Encounter.risk_tier.label("latest_risk_tier"),
            Encounter.updated_at.label("latest_updated_at"),
            func.row_number()
            .over(partition_by=Encounter.patient_id, order_by=Encounter.updated_at.desc())
            .label("rn"),
            func.count(Encounter.id)
            .filter(Encounter.status.in_(active_statuses))
            .over(partition_by=Encounter.patient_id)
            .label("active_encounter_count"),
        )
        .where(Encounter.deleted_at.is_(None))
        .subquery()
    )

    latest_encounter = (
        select(
            ranked_encounters.c.patient_id,
            ranked_encounters.c.encounter_id.label("active_encounter_id"),
            ranked_encounters.c.latest_status,
            ranked_encounters.c.latest_risk_tier,
            ranked_encounters.c.active_encounter_count,
        )
        .where(ranked_encounters.c.rn == 1)
        .subquery()
    )

    data_query = (
        select(
            Patient.id.label("patient_id"),
            Patient.first_name,
            Patient.last_name,
            Patient.date_of_birth,
            Patient.mrn_encrypted,
            latest_encounter.c.active_encounter_count,
            latest_encounter.c.active_encounter_id,
            latest_encounter.c.latest_status,
            latest_encounter.c.latest_risk_tier,
        )
        .outerjoin(latest_encounter, latest_encounter.c.patient_id == Patient.id)
        .where(Patient.deleted_at.is_(None))
        .order_by(Patient.created_at.desc())
    )

    # Free-text search is performed in memory after decryption, so we fetch all
    # rows when a search term is provided and paginate afterwards.
    offset = 0
    if not search_term:
        offset = (page - 1) * page_size
        data_query = data_query.offset(offset).limit(page_size)

    result = await db.execute(data_query)
    rows = result.all()

    patient_items = []
    for row in rows:
        first_name = _safe_decrypt(row.first_name)
        last_name = _safe_decrypt(row.last_name)
        mrn_plain = _safe_decrypt(row.mrn_encrypted)
        mrn_masked = f"****{mrn_plain[-4:]}" if mrn_plain and len(mrn_plain) >= 4 else "****"

        patient_items.append({
            "patient_id": str(row.patient_id),
            "first_name": first_name,
            "last_name": last_name,
            "date_of_birth": _safe_decrypt(row.date_of_birth),
            "mrn_masked": mrn_masked,
            "active_encounter_count": row.active_encounter_count or 0,
            "active_encounter_id": str(row.active_encounter_id) if row.active_encounter_id else None,
            "latest_status": row.latest_status or "",
            "latest_risk_tier": (row.latest_risk_tier or "UNKNOWN").upper(),
        })

    if search_term:
        filtered_items = []
        for item in patient_items:
            full_name = f"{item.get('first_name', '')} {item.get('last_name', '')}".lower()
            mrn_display = item.get("mrn_masked", "").lower()
            if search_term in full_name or search_term in mrn_display:
                filtered_items.append(item)
        total = len(filtered_items)
        offset = (page - 1) * page_size
        patient_items = filtered_items[offset:offset + page_size]
    else:
        count_query = select(func.count(Patient.id)).where(Patient.deleted_at.is_(None))
        count_result = await db.execute(count_query)
        total = count_result.scalar() or 0

    return {
        "items": patient_items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def _list_encounter_patients(
    db: AsyncSession,
    page: int,
    page_size: int,
    unit: str,
    search: str,
    status: str,
) -> dict:
    """Return encounter-level rows (legacy behavior for /patients without unique=true)."""
    search_term = search.strip().lower()

    def _base_filter(query):
        query = (
            query.join(Patient, Encounter.patient_id == Patient.id)
            .where(Patient.deleted_at.is_(None))
            .where(Encounter.deleted_at.is_(None))
        )
        if unit:
            query = query.where(Encounter.unit == unit)
        if status:
            query = query.where(Encounter.status == status.upper())
        return query

    count_query = _base_filter(select(func.count(Encounter.id)))
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    data_query = _base_filter(
        select(
            Encounter.id.label("encounter_id"),
            Patient.id.label("patient_id"),
            Patient.first_name,
            Patient.last_name,
            Patient.date_of_birth,
            Patient.mrn_encrypted,
            Encounter.unit.label("current_unit"),
            Encounter.status.label("status"),
            Bed.bed_number.label("room_number"),
            Encounter.risk_tier,
            Encounter.risk_score,
            Encounter.created_at.label("admission_date"),
        )
        .outerjoin(Bed, Bed.current_encounter_id == Encounter.id)
    )

    offset = 0
    if not search_term:
        offset = (page - 1) * page_size
        data_query = data_query.offset(offset).limit(page_size)
    data_query = data_query.order_by(Encounter.updated_at.desc())

    result = await db.execute(data_query)
    rows = result.all()

    patient_items = []
    for row in rows:
        first_name = _safe_decrypt(row.first_name)
        last_name = _safe_decrypt(row.last_name)
        mrn_plain = _safe_decrypt(row.mrn_encrypted)
        mrn_masked = f"****{mrn_plain[-4:]}" if mrn_plain and len(mrn_plain) >= 4 else "****"

        patient_items.append({
            "encounter_id": str(row.encounter_id),
            "patient_id": str(row.patient_id),
            "first_name": first_name,
            "last_name": last_name,
            "date_of_birth": _safe_decrypt(row.date_of_birth),
            "current_unit": row.current_unit or "",
            "room_number": row.room_number or "",
            "mrn_masked": mrn_masked,
            "risk_tier": row.risk_tier or "UNKNOWN",
            "risk_score": row.risk_score,
            "admission_date": row.admission_date.isoformat() if row.admission_date else "",
            "status": row.status or "",
        })

    if search_term:
        filtered_items = []
        for item in patient_items:
            full_name = f"{item.get('first_name', '')} {item.get('last_name', '')}".lower()
            mrn_display = item.get("mrn_masked", "").lower()
            if search_term in full_name or search_term in mrn_display:
                filtered_items.append(item)
        total = len(filtered_items)
        offset = (page - 1) * page_size
        patient_items = filtered_items[offset:offset + page_size]

    return {
        "items": patient_items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{encounter_id}")
async def get_patient(
    encounter_id: uuid.UUID,
    current_user: Annotated[TokenClaims, Depends(require_permission("patient", "read"))],
    db: AsyncSession = Depends(get_write_db),
) -> dict:
    """Get a single encounter-level patient record — requires patient:read permission.

    The route parameter is the encounter id; returns patient + encounter details
    for the patient detail screen.
    """
    try:
        query = (
            select(
                Encounter.id.label("encounter_id"),
                Patient.id.label("patient_id"),
                Patient.first_name,
                Patient.last_name,
                Patient.date_of_birth,
                Patient.mrn_encrypted,
                Encounter.unit.label("current_unit"),
                Encounter.status.label("status"),
                Encounter.risk_tier,
                Encounter.risk_score,
                Bed.bed_number.label("room_number"),
                Encounter.created_at.label("admission_date"),
            )
            .join(Patient, Encounter.patient_id == Patient.id)
            .outerjoin(Bed, Bed.current_encounter_id == Encounter.id)
            .where(Encounter.id == encounter_id)
            .where(Patient.deleted_at.is_(None))
            .where(Encounter.deleted_at.is_(None))
        )

        result = await db.execute(query)
        row = result.one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Encounter not found")

        mrn = row.mrn_encrypted or ""
        mrn_masked = f"****{mrn[-4:]}" if mrn and len(str(mrn)) >= 4 else "****"

        return {
            "encounter_id": str(row.encounter_id),
            "patient_id": str(row.patient_id),
            "first_name": row.first_name or "",
            "last_name": row.last_name or "",
            "date_of_birth": row.date_of_birth or "",
            "current_unit": row.current_unit or "",
            "room_number": row.room_number or "",
            "mrn_masked": mrn_masked,
            "mrn": mrn_masked,
            "risk_tier": row.risk_tier or "UNKNOWN",
            "risk_score": row.risk_score,
            "status": row.status or "",
            "admission_date": row.admission_date.isoformat() if row.admission_date else "",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error fetching patient detail: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch patient detail: {str(e)}")


@router.patch("/{patient_id}")
async def update_patient(
    patient_id: uuid.UUID,
    current_user: Annotated[TokenClaims, Depends(require_permission("patient", "write"))],
) -> dict:
    """Update a patient — requires patient:write permission."""
    # TODO: implement patient update
    return {"patient_id": str(patient_id), "user": current_user.sub}
