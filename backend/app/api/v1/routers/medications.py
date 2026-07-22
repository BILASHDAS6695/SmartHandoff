"""Medication resource router — RBAC-protected endpoints."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.auth.jwt import TokenClaims
from app.core.auth.rbac import require_permission

router = APIRouter(prefix="/medications", tags=["medications"])


@router.get("")
async def list_medications(
    current_user: Annotated[TokenClaims, Depends(require_permission("medication", "list"))],
) -> dict:
    """List medications — requires medication:list permission."""
    return {"medications": [], "user": current_user.sub}


@router.get("/{medication_id}")
async def get_medication(
    medication_id: uuid.UUID,
    current_user: Annotated[TokenClaims, Depends(require_permission("medication", "read"))],
) -> dict:
    """Get a single medication — requires medication:read permission."""
    return {"medication_id": str(medication_id), "user": current_user.sub}


@router.post("")
async def create_medication(
    current_user: Annotated[TokenClaims, Depends(require_permission("medication", "write"))],
) -> dict:
    """Create a medication — requires medication:write permission."""
    return {"created": True, "user": current_user.sub}


@router.patch("/{medication_id}")
async def update_medication(
    medication_id: uuid.UUID,
    current_user: Annotated[TokenClaims, Depends(require_permission("medication", "write"))],
) -> dict:
    """Update a medication — requires medication:write permission."""
    return {"medication_id": str(medication_id), "user": current_user.sub}
