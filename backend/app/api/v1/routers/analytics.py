"""Analytics resource router — RBAC-protected endpoints."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.auth.jwt import TokenClaims
from app.core.auth.rbac import require_permission

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("")
async def list_analytics(
    current_user: Annotated[TokenClaims, Depends(require_permission("analytics", "list"))],
) -> dict:
    """List analytics reports — requires analytics:list permission."""
    return {"reports": [], "user": current_user.sub}


@router.get("/{report}")
async def get_analytics_report(
    report: str,
    current_user: Annotated[TokenClaims, Depends(require_permission("analytics", "read"))],
) -> dict:
    """Get an analytics report — requires analytics:read permission."""
    return {"report": report, "user": current_user.sub}
