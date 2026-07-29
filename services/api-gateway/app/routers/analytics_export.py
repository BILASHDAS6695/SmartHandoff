"""FastAPI router for KPI analytics export — CSV and PDF download.

Endpoint:
    GET /api/v1/analytics/export

Query params:
    format  (str,  required) — "csv" or "pdf"
    from    (date, ISO 8601, required) — start of reporting window (inclusive)
    to      (date, ISO 8601, required) — end of reporting window (inclusive)

RBAC:
    Permitted roles: MANAGER, ADMIN
    Denied:          NURSE, PHYSICIAN, PHARMACIST, PATIENT → 403 Forbidden

De-identification guarantee:
    Export handlers (TASK-002, TASK-004) only receive aggregated KPI data sourced
    from KpiQueryService. Patient-level data never reaches this router.

Design refs:
    design.md §3.3 — FastAPI backend structure; RBAC enforcement
    design.md ADR-006 — read replica routing for all dashboard GET paths
    US-063 AC Scenario 4 — 403 for nurse role
    US-063 Technical Notes — StreamingResponse (CSV); BackgroundTasks (PDF)
"""
from __future__ import annotations

import datetime
import uuid
from enum import Enum
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.app.core.auth.jwt import TokenClaims, get_current_user
from app.export.csv_exporter import build_csv_streaming_response
from app.export.pdf_exporter import build_pdf
from app.export.chart_renderer import render_all_charts

router = APIRouter(prefix="/analytics", tags=["analytics-export"])

_ALLOWED_ROLES = {"manager", "admin"}
_MAX_DATE_RANGE_DAYS = 366
_EXPORT_JOBS: dict[str, dict] = {}  # In-memory job status store for polling

_bearer_scheme = HTTPBearer(auto_error=True)


class ExportFormat(str, Enum):
    csv = "csv"
    pdf = "pdf"


def _require_manager_or_admin(
    current_user: Annotated[TokenClaims, Depends(get_current_user)],
) -> TokenClaims:
    """FastAPI dependency enforcing manager or admin role.
    
    Args:
        current_user: Current user's JWT claims.
        
    Returns:
        TokenClaims if authorized.
        
    Raises:
        HTTPException 403: If user role is not manager or admin.
    """
    if current_user.role.lower() not in _ALLOWED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this resource.",
        )
    return current_user


@router.get(
    "/export",
    summary="Export KPI analytics report",
    responses={
        200: {"description": "CSV file download"},
        202: {"description": "PDF export accepted — poll download URL"},
        400: {"description": "Invalid query parameters"},
        403: {"description": "Insufficient role"},
    },
)
async def export_kpi_report(
    format: ExportFormat = Query(..., description="Export format: csv or pdf"),
    from_date: datetime.date = Query(..., alias="from", description="Start date (ISO 8601)"),
    to_date: datetime.date = Query(..., alias="to", description="End date (ISO 8601)"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_user: Annotated[TokenClaims, Depends(_require_manager_or_admin)] = None,
) -> StreamingResponse | JSONResponse:
    """Return CSV stream immediately or schedule PDF generation.

    CSV exports return 200 with streaming response.
    PDF exports return 202 Accepted with job_id for polling.

    Raises:
        HTTPException 400: if from_date > to_date or date range exceeds 366 days.
        HTTPException 403: if user role is not MANAGER or ADMIN.
    """
    _validate_date_range(from_date, to_date)

    # Mock KPI data (in production, would query KpiQueryService)
    kpi_data = _get_mock_kpi_data(from_date, to_date)

    if format == ExportFormat.csv:
        return build_csv_streaming_response(kpi_data, from_date, to_date)
    
    # PDF export — schedule background task and return 202
    job_id = str(uuid.uuid4())
    background_tasks.add_task(
        _generate_pdf_background,
        job_id=job_id,
        kpi_data=kpi_data,
        from_date=from_date,
        to_date=to_date,
        hospital_name=current_user.hospital_name if hasattr(current_user, 'hospital_name') else "Hospital",
    )
    
    _EXPORT_JOBS[job_id] = {
        "status": "processing",
        "download_url": None,
    }
    
    return JSONResponse(
        status_code=202,
        content={
            "job_id": job_id,
            "status": "processing",
            "poll_url": f"/api/v1/analytics/export/status/{job_id}",
        },
    )


def _validate_date_range(
    from_date: datetime.date,
    to_date: datetime.date,
) -> None:
    """Validate that the requested date range is logically sound.

    Raises:
        HTTPException 400: if from_date is after to_date.
        HTTPException 400: if date range exceeds _MAX_DATE_RANGE_DAYS.
    """
    if from_date > to_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query parameter 'from' must not be after 'to'.",
        )
    if (to_date - from_date).days > _MAX_DATE_RANGE_DAYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Date range must not exceed {_MAX_DATE_RANGE_DAYS} days.",
        )


@router.get(
    "/export/status/{job_id}",
    summary="Poll PDF export job status",
)
async def get_export_status(job_id: str) -> dict:
    """Poll the status of a PDF export job.
    
    Args:
        job_id: UUID of the export job.
        
    Returns:
        Job status dict with status and download_url (if complete).
        
    Raises:
        HTTPException 404: If job_id not found.
    """
    if job_id not in _EXPORT_JOBS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Export job not found.",
        )
    
    return _EXPORT_JOBS[job_id]


@router.get(
    "/export/download/{job_id}",
    summary="Download completed PDF export",
)
async def download_pdf_export(job_id: str, filename: str = Query(...)) -> StreamingResponse:
    """Download a completed PDF export.
    
    Args:
        job_id: UUID of the export job.
        filename: Desired filename for download.
        
    Returns:
        StreamingResponse with PDF bytes.
        
    Raises:
        HTTPException 404: If job_id not found or not complete.
        HTTPException 410: If PDF generation failed.
    """
    if job_id not in _EXPORT_JOBS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Export job not found.",
        )
    
    job = _EXPORT_JOBS[job_id]
    
    if job["status"] == "processing":
        raise HTTPException(
            status_code=status.HTTP_202_ACCEPTED,
            detail="PDF export still processing.",
        )
    
    if job["status"] == "error":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"PDF export failed: {job.get('error', 'Unknown error')}",
        )
    
    pdf_bytes = job.get("pdf_bytes", b"")
    
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _get_mock_kpi_data(from_date: datetime.date, to_date: datetime.date) -> list[dict]:
    """Generate mock KPI data for testing/demo.
    
    In production, this would call KpiQueryService.get_kpi_data().
    
    Args:
        from_date: Report start date.
        to_date: Report end date.
        
    Returns:
        List of KPI data point dicts.
    """
    from dataclasses import dataclass
    
    @dataclass
    class MockKpiPoint:
        date: datetime.date
        unit_name: str
        avg_los_hours: float
        discharge_count: int
        readmission_rate: float
        medication_reconciliation_rate: float
        handoff_completion_rate: float
        agent_success_rate: float
    
    current_date = from_date
    data = []
    day_offset = 0
    
    while current_date <= to_date:
        data.append(
            MockKpiPoint(
                date=current_date,
                unit_name=f"Unit-{(day_offset % 3) + 1}",
                avg_los_hours=24.0 + (day_offset * 0.1),
                discharge_count=10 + day_offset,
                readmission_rate=0.05 + (day_offset * 0.0001),
                medication_reconciliation_rate=0.92 - (day_offset * 0.0001),
                handoff_completion_rate=0.88 + (day_offset * 0.0002),
                agent_success_rate=0.94 + (day_offset * 0.00005),
            )
        )
        current_date = current_date + datetime.timedelta(days=1)
        day_offset += 1
    
    return data


async def _generate_pdf_background(
    job_id: str,
    kpi_data: list,
    from_date: datetime.date,
    to_date: datetime.date,
    hospital_name: str,
) -> None:
    """Background task: generate PDF and store download URL.
    
    Args:
        job_id: UUID for this export job.
        kpi_data: KPI data points for the report.
        from_date: Report start date.
        to_date: Report end date.
        hospital_name: Hospital display name.
    """
    try:
        # Render charts
        chart_images = render_all_charts(kpi_data)
        
        # Build PDF
        pdf_bytes = build_pdf(
            kpi_data=kpi_data,
            chart_images=chart_images,
            hospital_name=hospital_name,
            from_date=from_date,
            to_date=to_date,
        )
        
        # In production, upload to Cloud Storage and generate signed URL
        # For now, store in memory with a mock download URL
        filename = f"kpi_report_{from_date.isoformat()}_{to_date.isoformat()}.pdf"
        download_url = f"/api/v1/analytics/export/download/{job_id}?filename={filename}"
        
        # Store for retrieval
        _EXPORT_JOBS[job_id] = {
            "status": "complete",
            "download_url": download_url,
            "pdf_bytes": pdf_bytes,
        }
        
    except Exception as exc:
        _EXPORT_JOBS[job_id] = {
            "status": "error",
            "download_url": None,
            "error": str(exc),
        }

