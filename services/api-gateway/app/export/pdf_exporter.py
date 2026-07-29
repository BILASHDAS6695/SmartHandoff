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
from typing import Any

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


def build_pdf(
    kpi_data: list[Any],
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

    for chart_image in chart_images:
        if chart_image.png_bytes:
            # Embed the chart PNG
            chart_buf = io.BytesIO(chart_image.png_bytes)
            flowables.append(RLImage(chart_buf, width=6.5 * cm, height=2.5 * cm))
            flowables.append(Paragraph(chart_image.title, chart_caption_style))
            flowables.append(Spacer(1, 8))

    # ── Build the PDF ────────────────────────────────────────────────────────
    doc.build(flowables)
    buf.seek(0)
    return buf.read()


def _build_kpi_table(kpi_data: list[Any]) -> Table:
    """Build the KPI summary table flowable.

    Args:
        kpi_data: De-identified KPI data points.

    Returns:
        A reportlab Table flowable.
    """
    if not kpi_data:
        table_data = [_TABLE_HEADERS]
    else:
        table_data = [_TABLE_HEADERS]
        for i, point in enumerate(kpi_data):
            row = [
                str(getattr(point, "date", "")),
                str(getattr(point, "unit_name", "")),
                f"{getattr(point, 'avg_los_hours', 0):.1f}",
                str(getattr(point, "discharge_count", 0)),
                f"{getattr(point, 'readmission_rate', 0) * 100:.1f}%",
                f"{getattr(point, 'medication_reconciliation_rate', 0) * 100:.1f}%",
                f"{getattr(point, 'handoff_completion_rate', 0) * 100:.1f}%",
                f"{getattr(point, 'agent_success_rate', 0) * 100:.1f}%",
            ]
            table_data.append(row)

    table = Table(table_data, colWidths=[1.2 * cm for _ in range(len(_TABLE_HEADERS))])

    # Apply styling
    table.setStyle(
        TableStyle(
            [
                # Header row styling
                ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                # Grid and borders
                ("GRID", (0, 0), (-1, -1), 0.5, _BORDER),
                ("FONTSIZE", (0, 1), (-1, -1), 7),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ROW_ALT_BG]),
                ("PADDING", (0, 1), (-1, -1), 3),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )

    return table
