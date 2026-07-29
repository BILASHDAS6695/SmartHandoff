"""Server-side Matplotlib chart renderer for KPI PDF reports.

Generates the same 5 KPI charts displayed on the Angular analytics dashboard
(US-061) as PNG byte streams for embedding in the PDF report (US-063).

No PHI: All charts are derived from aggregated KpiDataPoint records.
No disk I/O: Charts are generated entirely in-memory using BytesIO.

Charts produced:
    1. avg_los_hours       — Average LOS (hours) over time        [line]
    2. discharge_count     — Daily discharge count                 [bar]
    3. readmission_rate    — Readmission rate (%) over time        [line]
    4. medication_reconciliation_rate — Med reconciliation rate    [line]
    5. handoff_completion_rate        — Handoff completion rate    [line]

Design refs:
    design.md §4.1 — matplotlib for server-side chart PNG generation
    US-063 AC Scenario 2 — 5 chart images embedded in PDF
    US-063 Technical Notes — same KPI query as dashboard
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Sequence, Any

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# Use non-interactive Agg backend — safe for server environments without a display
matplotlib.use("Agg")

# Chart dimensions matching the dashboard viewport proportions
_FIGURE_WIDTH_IN = 9.0
_FIGURE_HEIGHT_IN = 3.5
_DPI = 150

# SmartHandoff brand colours (align with Angular Material theme in US-061)
_COLOUR_PRIMARY = "#1565C0"   # blue-800
_COLOUR_SECONDARY = "#00897B" # teal-600
_COLOUR_GRID = "#E0E0E0"


@dataclass(frozen=True)
class ChartImage:
    """In-memory PNG chart image for PDF embedding.

    Attributes:
        title:      Human-readable chart title for PDF caption.
        png_bytes:  Raw PNG bytes produced by matplotlib.
    """

    title: str
    png_bytes: bytes


def render_all_charts(kpi_data: Sequence[Any]) -> list[ChartImage]:
    """Generate all 5 KPI charts as in-memory PNG images.

    Args:
        kpi_data: Sequence of de-identified KPI data points ordered by date.

    Returns:
        List of 5 ChartImage instances in the order they appear in the PDF.
    """
    if not kpi_data:
        # Return empty charts for empty data
        return [
            ChartImage(title="Average Length of Stay (hours)", png_bytes=_create_empty_chart()),
            ChartImage(title="Daily Discharge Count", png_bytes=_create_empty_chart()),
            ChartImage(title="Readmission Rate (%)", png_bytes=_create_empty_chart()),
            ChartImage(title="Medication Reconciliation Rate (%)", png_bytes=_create_empty_chart()),
            ChartImage(title="Handoff Completion Rate (%)", png_bytes=_create_empty_chart()),
        ]

    dates = [getattr(point, "date", None) for point in kpi_data]

    return [
        _render_line_chart(
            dates=dates,
            values=[getattr(point, "avg_los_hours", 0) for point in kpi_data],
            title="Average Length of Stay (hours)",
            ylabel="Hours",
        ),
        _render_bar_chart(
            dates=dates,
            values=[getattr(point, "discharge_count", 0) for point in kpi_data],
            title="Daily Discharge Count",
            ylabel="Discharges",
        ),
        _render_line_chart(
            dates=dates,
            values=[getattr(point, "readmission_rate", 0) * 100 for point in kpi_data],
            title="Readmission Rate (%)",
            ylabel="Rate (%)",
        ),
        _render_line_chart(
            dates=dates,
            values=[getattr(point, "medication_reconciliation_rate", 0) * 100 for point in kpi_data],
            title="Medication Reconciliation Rate (%)",
            ylabel="Rate (%)",
            colour=_COLOUR_SECONDARY,
        ),
        _render_line_chart(
            dates=dates,
            values=[getattr(point, "handoff_completion_rate", 0) * 100 for point in kpi_data],
            title="Handoff Completion Rate (%)",
            ylabel="Rate (%)",
        ),
    ]


def _render_line_chart(
    dates: list,
    values: list[float],
    title: str,
    ylabel: str,
    colour: str = _COLOUR_PRIMARY,
) -> ChartImage:
    """Render a time-series line chart and return PNG bytes.

    Args:
        dates:   X-axis date values.
        values:  Y-axis metric values aligned with dates.
        title:   Chart title used as both figure title and ChartImage.title.
        ylabel:  Y-axis label.
        colour:  Line colour hex string.

    Returns:
        ChartImage with title and in-memory PNG bytes.
    """
    fig, ax = plt.subplots(figsize=(_FIGURE_WIDTH_IN, _FIGURE_HEIGHT_IN), dpi=_DPI)
    ax.plot(dates, values, color=colour, linewidth=1.8, marker="o", markersize=3)
    _apply_chart_styling(ax, title, ylabel)
    return _export_to_chart_image(fig, title)


def _render_bar_chart(
    dates: list,
    values: list[int],
    title: str,
    ylabel: str,
) -> ChartImage:
    """Render a bar chart and return PNG bytes.

    Args:
        dates:  X-axis date values.
        values: Y-axis integer count values.
        title:  Chart title.
        ylabel: Y-axis label.

    Returns:
        ChartImage with title and in-memory PNG bytes.
    """
    fig, ax = plt.subplots(figsize=(_FIGURE_WIDTH_IN, _FIGURE_HEIGHT_IN), dpi=_DPI)
    ax.bar(dates, values, color=_COLOUR_PRIMARY, alpha=0.75, width=0.7)
    _apply_chart_styling(ax, title, ylabel)
    return _export_to_chart_image(fig, title)


def _apply_chart_styling(ax: plt.Axes, title: str, ylabel: str) -> None:
    """Apply consistent SmartHandoff styling to a matplotlib Axes object.

    Args:
        ax:     Axes to style.
        title:  Title string displayed above the chart.
        ylabel: Y-axis label.
    """
    ax.set_title(title, fontsize=11, fontweight="bold", pad=8)
    ax.set_ylabel(ylabel, fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=12))
    ax.yaxis.grid(True, color=_COLOUR_GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=8)
    plt.tight_layout()


def _export_to_chart_image(fig: plt.Figure, title: str) -> ChartImage:
    """Save a matplotlib figure to an in-memory PNG buffer.

    Args:
        fig:   Matplotlib figure to save.
        title: Chart title for ChartImage metadata.

    Returns:
        ChartImage with the PNG bytes.
    """
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return ChartImage(title=title, png_bytes=buf.read())


def _create_empty_chart() -> bytes:
    """Create a blank chart PNG for empty data."""
    fig, ax = plt.subplots(figsize=(_FIGURE_WIDTH_IN, _FIGURE_HEIGHT_IN), dpi=_DPI)
    ax.text(0.5, 0.5, "No data available", ha="center", va="center", transform=ax.transAxes)
    ax.set_xticks([])
    ax.set_yticks([])
    return _export_to_chart_image(fig, "Empty").png_bytes
