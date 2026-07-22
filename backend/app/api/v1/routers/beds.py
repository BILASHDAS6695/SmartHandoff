"""Bed resource router — RBAC-protected endpoints."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.auth.jwt import TokenClaims
from app.core.auth.rbac import require_permission

router = APIRouter(prefix="/beds", tags=["beds"])


@router.get("")
async def list_beds(
    current_user: Annotated[TokenClaims, Depends(require_permission("bed", "list"))],
) -> dict:
    """List beds — requires bed:list permission (BED_MANAGER/ADMIN only)."""
    return {"beds": [], "user": current_user.sub}


@router.get("/{bed_id}")
async def get_bed(
    bed_id: uuid.UUID,
    current_user: Annotated[TokenClaims, Depends(require_permission("bed", "read"))],
) -> dict:
    """Get a single bed — requires bed:read permission."""
    return {"bed_id": str(bed_id), "user": current_user.sub}


@router.post("")
async def create_bed(
    current_user: Annotated[TokenClaims, Depends(require_permission("bed", "write"))],
) -> dict:
    """Create a bed — requires bed:write permission."""
    return {"created": True, "user": current_user.sub}


@router.patch("/{bed_id}")
async def update_bed(
    bed_id: uuid.UUID,
    current_user: Annotated[TokenClaims, Depends(require_permission("bed", "write"))],
) -> dict:
    """Update a bed — requires bed:write permission."""
    return {"bed_id": str(bed_id), "user": current_user.sub}
