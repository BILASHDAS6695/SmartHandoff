"""Document resource router — RBAC-protected endpoints."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.auth.jwt import TokenClaims
from app.core.auth.rbac import require_permission

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("")
async def list_documents(
    current_user: Annotated[TokenClaims, Depends(require_permission("document", "list"))],
) -> dict:
    """List documents — requires document:list permission."""
    return {"documents": [], "user": current_user.sub}


@router.get("/{document_id}")
async def get_document(
    document_id: uuid.UUID,
    current_user: Annotated[TokenClaims, Depends(require_permission("document", "read"))],
) -> dict:
    """Get a single document — requires document:read permission."""
    return {"document_id": str(document_id), "user": current_user.sub}


@router.post("")
async def create_document(
    current_user: Annotated[TokenClaims, Depends(require_permission("document", "write"))],
) -> dict:
    """Create a document — requires document:write permission."""
    return {"created": True, "user": current_user.sub}


@router.patch("/{document_id}/approve")
async def approve_document(
    document_id: uuid.UUID,
    current_user: Annotated[TokenClaims, Depends(require_permission("document", "approve"))],
) -> dict:
    """Approve a document — requires document:approve permission (PHYSICIAN/ADMIN only)."""
    return {"document_id": str(document_id), "approved": True, "user": current_user.sub}
