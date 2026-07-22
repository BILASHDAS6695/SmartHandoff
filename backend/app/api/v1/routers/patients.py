"""Patient resource router — RBAC-protected endpoints."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.auth.jwt import TokenClaims
from app.core.auth.rbac import require_permission

router = APIRouter(prefix="/patients", tags=["patients"])


@router.get("")
async def list_patients(
    current_user: Annotated[TokenClaims, Depends(require_permission("patient", "list"))],
) -> dict:
    """List all patients — requires patient:list permission."""
    # TODO: implement patient list query
    return {"patients": [], "user": current_user.sub}


@router.get("/{patient_id}")
async def get_patient(
    patient_id: uuid.UUID,
    current_user: Annotated[TokenClaims, Depends(require_permission("patient", "read"))],
) -> dict:
    """Get a single patient — requires patient:read permission."""
    # TODO: implement patient detail query
    return {"patient_id": str(patient_id), "user": current_user.sub}


@router.patch("/{patient_id}")
async def update_patient(
    patient_id: uuid.UUID,
    current_user: Annotated[TokenClaims, Depends(require_permission("patient", "write"))],
) -> dict:
    """Update a patient — requires patient:write permission."""
    # TODO: implement patient update
    return {"patient_id": str(patient_id), "user": current_user.sub}
