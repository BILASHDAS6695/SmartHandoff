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
from app.models.encounter import Encounter
from app.models.patient import Patient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/patients", tags=["patients"])


@router.get("")
async def list_patients(
    current_user: Annotated[TokenClaims, Depends(require_permission("patient", "list"))],
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    unit: str = Query(""),
    search: str = Query(""),
    status: str = Query(""),
    # NOTE: Uses get_write_db for local dev — both read and write point to same database
    db: AsyncSession = Depends(get_write_db),
) -> dict:
    """List all patients with encounter-level data — requires patient:list permission.
    
    Returns encounter records (not patient records) to include room_number and admission_date.
    """
    try:
        logger.info(
            f"Fetching patients: page={page}, page_size={page_size}, unit={unit}, "
            f"search={search}, status={status}"
        )

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

        # Step 1: Get total count (accurate only when not using free-text search;
        # search results are filtered in memory after decryption).
        count_query = _base_filter(select(func.count(Encounter.id)))
        count_result = await db.execute(count_query)
        total = count_result.scalar() or 0
        logger.info(f"Total encounters: {total}")

        # Step 2: Fetch encounter data
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
                Encounter.created_at.label("admission_date"),
            )
            .outerjoin(Bed, Bed.current_encounter_id == Encounter.id)
        )

        # When searching by name/MRN we decrypt server-side and filter in memory,
        # so fetch the full result set and paginate after filtering.
        offset = 0
        if not search_term:
            offset = (page - 1) * page_size
            data_query = data_query.offset(offset).limit(page_size)
        data_query = data_query.order_by(Encounter.created_at.desc())

        logger.info(f"Executing data query with offset={offset}, limit={page_size}, search={search_term!r}")
        result = await db.execute(data_query)
        rows = result.all()
        logger.info(f"Fetched {len(rows)} rows")

        # Step 3: Convert rows to response format
        patient_items = []

        def _safe_decrypt(ciphertext: str | None) -> str:
            """Decrypt PHI, falling back to plaintext if the value was stored unencrypted."""
            if not ciphertext:
                return ""
            try:
                return _decrypt(ciphertext).decode("utf-8")
            except Exception:
                logger.warning("Failed to decrypt PHI value; treating as plaintext.")
                return ciphertext

        for row in rows:
            # Decrypt PHI on the server for accurate search matching (client only gets masked MRN)
            first_name = _safe_decrypt(row.first_name)
            last_name = _safe_decrypt(row.last_name)
            mrn_plain = _safe_decrypt(row.mrn_encrypted)

            # Mask MRN to last 4 digits for HIPAA compliance
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
                "risk_score": None,
                "admission_date": row.admission_date.isoformat() if row.admission_date else "",
                "status": row.status or "",
            })

        # Free-text search is performed server-side against decrypted PHI so
        # partial name/MRN matches work even though the columns are encrypted at rest.
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

        logger.info(f"Returning {len(patient_items)} patient items")
        return {
            "items": patient_items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        # Log the error and re-raise for proper HTTP error response
        logger.error(f"❌ Error fetching patients: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch patients: {str(e)}")


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
            "risk_score": None,
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
