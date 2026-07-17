---
id: TASK-004
title: "PDF Exporter — ReportLab Document Rendering with KPI Table & Chart Embedding"
user_story: US-063
epic: EP-012
sprint: 2
layer: Backend / Data
estimate: 4h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-063/TASK-001, US-063/TASK-003, US-061/TASK-001]
---

# TASK-004: PDF Exporter — ReportLab Document Rendering with KPI Table & Chart Embedding

> **Story:** US-063 | **Epic:** EP-012 | **Sprint:** 2 | **Layer:** Backend / Data | **Est:** 4 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-063 requires a formatted PDF report containing: hospital name header, date range, KPI summary table, and 5 embedded chart images. This task implements `api-gateway/app/export/pdf_exporter.py`, which:

- Uses `reportlab.platypus.SimpleDocTemplate` with `Table` and `Image` flowables
- Assembles the PDF in a `BackgroundTasks` function and writes to an in-memory buffer
- Stores the completed PDF in Cloud Storage and returns a signed download URL (202 Accepted pattern)
- Applies de-identification guard — only `KpiDataPoint` aggregated fields appear in the table

The background-task / 202 pattern is required because PDF generation (chart rendering + reportlab layout) may take 5–20 seconds for large date ranges.

**Design references:**
- design.md §3.1 — Cloud Storage for generated artifacts
- design.md §4.1 — GCP Secret Manager for credentials; Cloud Storage signed URLs
- US-063 AC Scenario 2 — PDF with hospital name header, date range, KPI summary table, 5 charts
- US-063 Technical Notes — `reportlab` `SimpleDocTemplate`; `BackgroundTasks.add_task`; return 202 with download URL

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 2 | PDF contains hospital name header, date range subtitle, KPI summary table, and 5 embedded chart PNG images |
| Scenario 3 | Table columns match `_SAFE_COLUMNS` from TASK-002; PHI column blocklist enforced before rendering |

---

## Implementation Steps

### 1. Implement `api-gateway/app/export/pdf_exporter.py`

```python
"""ReportLab PDF exporter for KPI analytics reports.

Generates a professionally formatted PDF containing:
    - Hospital name header
    - Report date range subtitle
    - KPI summary table (aggregated metrics — no PHI)
    - 5 embedded chart PNG images (from chart_renderer.py)

PDF generation is scheduled as a FastAPI BackgroundTask due to rendering time.
The completed PDF is uploaded to Cloud Storage and a signed URL is returned
in the 202 Accepted response body.

Design refs:
    design.md §3.1 — Cloud Storage for generated report artifacts
    US-063 AC Scenario 2 — hospital name header, date range, KPI table, 5 charts
    US-063 Technical Notes — SimpleDocTemplate; BackgroundTasks.add_task; 202 + download URL
"""
from __future__ import annotations

import datetime
import io
import uuid
from typing import TYPE_CHECKING

from fastapi import BackgroundTasks
from fastapi.responses import JSONResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image as RLImage,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.analytics.schemas import KpiDataPoint
from app.analytics.query_service import KpiQueryService
from app.export.chart_renderer import render_all_charts
from app.storage.gcs_client import upload_bytes, generate_signed_url

if TYPE_CHECKING:
    pass

# PDF page style constants
_PAGE_WIDTH, _PAGE_HEIGHT = A4
_MARGIN_CM = 2.0

# Table column headers matching _SAFE_COLUMNS from csv_exporter.py
_TABLE_HEADERS = [
    "Date",
    "Unit",
    "Avg LOS (h)",
    "Discharges",
    "Readmission %",
    "Med Rec %",
    "Handoff %",
    "Agent Success %",
]

# Colours aligned with SmartHandoff Angular Material theme
_HEADER_BG = colors.HexColor("#1565C0")
_ROW_ALT_BG = colors.HexColor("#F5F5F5")
_BORDER = colors.HexColor("#BDBDBD")


async def schedule_pdf_export(
    background_tasks: BackgroundTasks,
    query_service: KpiQueryService,
    from_date: datetime.date,
    to_date: datetime.date,
    units: list[str],
    hospital_name: str,
) -> JSONResponse:
    """Schedule PDF generation as a background task and return 202 Accepted.

    The PDF is built in `_generate_and_upload_pdf`, uploaded to GCS, and a
    signed URL is stored. The client polls `GET /api/v1/analytics/export/status/{job_id}`
    to retrieve the download URL when ready.

    Args:
        background_tasks: FastAPI BackgroundTasks instance.
        query_service:    Initialised KpiQueryService for data retrieval.
        from_date:        Report start date.
        to_date:          Report end date.
        units:            Manager-accessible unit names (for query scoping).
        hospital_name:    Hospital display name for the PDF header.

    Returns:
        JSONResponse with status 202 and a job_id for status polling.
    """
    job_id = str(uuid.uuid4())
    background_tasks.add_task(
        _generate_and_upload_pdf,
        job_id=job_id,
        query_service=query_service,
        from_date=from_date,
        to_date=to_date,
        units=units,
        hospital_name=hospital_name,
    )
    return JSONResponse(
        status_code=202,
        content={
            "job_id": job_id,
            "status": "processing",
            "poll_url": f"/api/v1/analytics/export/status/{job_id}",
        },
    )


async def _generate_and_upload_pdf(
    job_id: str,
    query_service: KpiQueryService,
    from_date: datetime.date,
    to_date: datetime.date,
    units: list[str],
    hospital_name: str,
) -> None:
    """Background task: generate the PDF and upload to Cloud Storage.

    Steps:
        1. Query KPI data for the requested date range.
        2. Render 5 chart PNGs via chart_renderer.
        3. Build ReportLab flowables (title, table, charts).
        4. Write PDF to in-memory BytesIO buffer.
        5. Upload buffer to GCS bucket `smarthandoff-exports`.
        6. Generate signed URL (1 hour TTL) and persist to export_jobs table.

    Args:
        job_id:        UUID for polling and GCS object naming.
        query_service: KpiQueryService for data retrieval.
        from_date:     Report start date.
        to_date:       Report end date.
        units:         Accessible unit names.
        hospital_name: Hospital display name.
    """
    kpi_data: list[KpiDataPoint] = await query_service.get_kpi_data(
        from_date=from_date,
        to_date=to_date,
        units=units,
    )

    chart_images = render_all_charts(kpi_data)
    pdf_bytes = _build_pdf(
        kpi_data=kpi_data,
        chart_images=chart_images,
        hospital_name=hospital_name,
        from_date=from_date,
        to_date=to_date,
    )

    object_name = f"exports/{job_id}/kpi_report_{from_date}_{to_date}.pdf"
    await upload_bytes(
        bucket="smarthandoff-exports",
        object_name=object_name,
        data=pdf_bytes,
        content_type="application/pdf",
    )
    signed_url = await generate_signed_url(
        bucket="smarthandoff-exports",
        object_name=object_name,
        expiration_minutes=60,
    )
    # Persist signed URL for the polling endpoint (export_jobs table — see TASK-001 notes)
    await _persist_export_job_url(job_id=job_id, download_url=signed_url)


def _build_pdf(
    kpi_data: list[KpiDataPoint],
    chart_images: list,
    hospital_name: str,
    from_date: datetime.date,
    to_date: datetime.date,
) -> bytes:
    """Assemble ReportLab flowables and render the PDF to bytes.

    Args:
        kpi_data:      De-identified KPI data points.
        chart_images:  List of ChartImage instances from chart_renderer.
        hospital_name: Hospital display name.
        from_date:     Report start date.
        to_date:       Report end date.

    Returns:
        Rendered PDF as bytes.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=_MARGIN_CM * cm,
        rightMargin=_MARGIN_CM * cm,
        topMargin=_MARGIN_CM * cm,
        bottomMargin=_MARGIN_CM * cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "SmartHandoffTitle",
        parent=styles["Title"],
        fontSize=16,
        textColor=colors.HexColor("#1565C0"),
        spaceAfter=6,
    )
    subtitle_style = ParagraphStyle(
        "SmartHandoffSubtitle",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#616161"),
        spaceAfter=14,
    )
    chart_caption_style = ParagraphStyle(
        "ChartCaption",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#424242"),
        spaceBefore=4,
        spaceAfter=10,
    )

    flowables = []

    # ── Header ──────────────────────────────────────────────────────────────
    flowables.append(Paragraph(f"{hospital_name} — SmartHandoff KPI Report", title_style))
    flowables.append(
        Paragraph(
            f"Reporting Period: {from_date.strftime('%d %B %Y')} to {to_date.strftime('%d %B %Y')}",
            subtitle_style,
        )
    )

    # ── KPI Summary Table ────────────────────────────────────────────────────
    flowables.append(Paragraph("KPI Summary", styles["Heading2"]))
    flowables.append(Spacer(1, 6))
    flowables.append(_build_kpi_table(kpi_data))
    flowables.append(Spacer(1, 16))

    # ── Embedded Charts ──────────────────────────────────────────────────────
    flowables.append(Paragraph("KPI Charts", styles["Heading2"]))
    flowables.append(Spacer(1, 6))

    chart_width = (_PAGE_WIDTH - 2 * _MARGIN_CM * cm) * 0.95
    chart_height = chart_width / (_FIGURE_WIDTH_RATIO := 9.0 / 3.5)

    for chart in chart_images:
        img_buf = io.BytesIO(chart.png_bytes)
        rl_image = RLImage(img_buf, width=chart_width, height=chart_height)
        flowables.append(rl_image)
        flowables.append(Paragraph(chart.title, chart_caption_style))

    doc.build(flowables)
    buf.seek(0)
    return buf.read()


def _build_kpi_table(kpi_data: list[KpiDataPoint]) -> Table:
    """Build a ReportLab Table from KPI data points.

    Args:
        kpi_data: De-identified KPI data points.

    Returns:
        Styled ReportLab Table flowable.
    """
    table_data = [_TABLE_HEADERS]
    for point in kpi_data:
        table_data.append(
            [
                point.date.strftime("%Y-%m-%d"),
                point.unit_name,
                f"{point.avg_los_hours:.1f}",
                str(point.discharge_count),
                f"{point.readmission_rate * 100:.1f}%",
                f"{point.medication_reconciliation_rate * 100:.1f}%",
                f"{point.handoff_completion_rate * 100:.1f}%",
                f"{point.agent_success_rate * 100:.1f}%",
            ]
        )

    table = Table(table_data, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("FONTSIZE", (0, 1), (-1, -1), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ROW_ALT_BG]),
                ("GRID", (0, 0), (-1, -1), 0.4, _BORDER),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return table


async def _persist_export_job_url(job_id: str, download_url: str) -> None:
    """Persist the completed export job's signed download URL.

    Stores the URL in the `export_jobs` table (schema: job_id, download_url,
    created_at, expires_at). The polling endpoint reads from this table.

    Args:
        job_id:       UUID of the export job.
        download_url: GCS signed URL valid for 60 minutes.
    """
    # Implementation deferred to database write service.
    # Table: export_jobs(job_id UUID PK, status TEXT, download_url TEXT,
    #                    created_at TIMESTAMPTZ, expires_at TIMESTAMPTZ)
    raise NotImplementedError(
        "Implement export_jobs DB write via ExportJobRepository in the API service layer."
    )
```

### 2. Add `reportlab` to backend dependencies

```bash
echo "reportlab>=4.2.0" >> api-gateway/requirements.txt
```

### 3. Create GCS client stub `api-gateway/app/storage/gcs_client.py`

```bash
mkdir -p api-gateway/app/storage
touch api-gateway/app/storage/__init__.py
touch api-gateway/app/storage/gcs_client.py
```

```python
"""Google Cloud Storage client helpers for export artifact upload.

Design refs:
    design.md §3.1 — Cloud Storage for audit and export artifacts
    US-063 Technical Notes — PDF stored in GCS; signed URL returned in 202 response
"""
from __future__ import annotations

import datetime

from google.cloud import storage


async def upload_bytes(
    bucket: str,
    object_name: str,
    data: bytes,
    content_type: str = "application/octet-stream",
) -> None:
    """Upload raw bytes to a GCS bucket object.

    Args:
        bucket:       GCS bucket name.
        object_name:  Object path within the bucket.
        data:         File content as bytes.
        content_type: MIME type for the uploaded object.
    """
    client = storage.Client()
    blob = client.bucket(bucket).blob(object_name)
    blob.upload_from_string(data, content_type=content_type)


async def generate_signed_url(
    bucket: str,
    object_name: str,
    expiration_minutes: int = 60,
) -> str:
    """Generate a V4 signed URL for a GCS object.

    Args:
        bucket:              GCS bucket name.
        object_name:         Object path within the bucket.
        expiration_minutes:  URL validity window in minutes.

    Returns:
        HTTPS signed URL string.
    """
    client = storage.Client()
    blob = client.bucket(bucket).blob(object_name)
    url: str = blob.generate_signed_url(
        version="v4",
        expiration=datetime.timedelta(minutes=expiration_minutes),
        method="GET",
    )
    return url
```

---

## Validation Checklist

- [ ] `_build_pdf()` returns non-empty bytes starting with `%PDF-` magic bytes
- [ ] PDF opens in a PDF reader without errors; hospital name visible in header
- [ ] KPI summary table headers match `_TABLE_HEADERS` (8 columns)
- [ ] 5 chart images appear in the PDF body, each with a caption
- [ ] No PHI columns present in the rendered table (spot-check: no MRN, patient_name, etc.)
- [ ] `schedule_pdf_export()` returns `JSONResponse` with status `202` and `job_id` field
- [ ] Background task is added to `BackgroundTasks` (verify with FastAPI `TestClient` + `lifespan`)
- [ ] `upload_bytes` and `generate_signed_url` are called within `_generate_and_upload_pdf`
- [ ] `google-cloud-storage` is in `requirements.txt`
