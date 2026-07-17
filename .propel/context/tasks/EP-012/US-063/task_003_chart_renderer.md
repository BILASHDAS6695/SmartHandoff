---
id: TASK-003
title: "Chart Renderer — Server-Side Matplotlib KPI Chart PNG Generation"
user_story: US-063
epic: EP-012
sprint: 2
layer: Backend / Data
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-063/TASK-001, US-061/TASK-001]
---

# TASK-003: Chart Renderer — Server-Side Matplotlib KPI Chart PNG Generation

> **Story:** US-063 | **Epic:** EP-012 | **Sprint:** 2 | **Layer:** Backend / Data | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-063 requires 5 chart images embedded in the PDF report. The charts must match those shown on the Angular analytics dashboard (US-061). This task implements `api-gateway/app/export/chart_renderer.py`, which:

- Accepts `list[KpiDataPoint]` for a given date range
- Generates the same 5 KPI charts as the dashboard using `matplotlib`
- Returns each chart as a PNG `bytes` object in memory (no disk writes; no temporary files)
- Provides a `render_all_charts()` entry point that returns a `list[ChartImage]` for consumption by the PDF exporter (TASK-004)

The 5 charts (matching the dashboard from US-061/TASK-005):
1. Average LOS (hours) over time — line chart
2. Daily discharge count — bar chart
3. Readmission rate (%) over time — line chart
4. Medication reconciliation rate (%) over time — line chart
5. Handoff completion rate (%) over time — line chart

**Design references:**
- design.md §4.1 — `matplotlib` server-side chart generation for PDF embedding
- US-063 Technical Notes — Chart PNGs: generate via `matplotlib` on the server using the same KPI query as the dashboard
- US-063 AC Scenario 2 — PDF contains 5 chart images embedded in the report

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 2 | `render_all_charts()` returns 5 `ChartImage` objects with non-empty PNG bytes |

---

## Implementation Steps

### 1. Implement `api-gateway/app/export/chart_renderer.py`

```python
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
from typing import Sequence

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from app.analytics.schemas import KpiDataPoint

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


def render_all_charts(kpi_data: Sequence[KpiDataPoint]) -> list[ChartImage]:
    """Generate all 5 KPI charts as in-memory PNG images.

    Args:
        kpi_data: Sequence of de-identified KPI data points ordered by date.

    Returns:
        List of 5 ChartImage instances in the order they appear in the PDF.
    """
    dates = [point.date for point in kpi_data]

    return [
        _render_line_chart(
            dates=dates,
            values=[point.avg_los_hours for point in kpi_data],
            title="Average Length of Stay (hours)",
            ylabel="Hours",
        ),
        _render_bar_chart(
            dates=dates,
            values=[point.discharge_count for point in kpi_data],
            title="Daily Discharge Count",
            ylabel="Discharges",
        ),
        _render_line_chart(
            dates=dates,
            values=[point.readmission_rate * 100 for point in kpi_data],
            title="Readmission Rate (%)",
            ylabel="Rate (%)",
        ),
        _render_line_chart(
            dates=dates,
            values=[point.medication_reconciliation_rate * 100 for point in kpi_data],
            title="Medication Reconciliation Rate (%)",
            ylabel="Rate (%)",
            colour=_COLOUR_SECONDARY,
        ),
        _render_line_chart(
            dates=dates,
            values=[point.handoff_completion_rate * 100 for point in kpi_data],
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
```

### 2. Add `matplotlib` to backend dependencies

```bash
# api-gateway/requirements.txt — add if not already present
echo "matplotlib>=3.9.0" >> api-gateway/requirements.txt
```

---

## Validation Checklist

- [ ] `render_all_charts(kpi_data)` returns a list of exactly 5 `ChartImage` instances
- [ ] Each `ChartImage.png_bytes` is non-empty and begins with the PNG magic bytes `\x89PNG`
- [ ] `ChartImage.title` strings match the 5 expected chart titles
- [ ] Empty `kpi_data` list → 5 `ChartImage` instances with blank charts (no exception raised)
- [ ] No temporary files written to disk during chart generation
- [ ] `matplotlib.get_backend()` returns `"agg"` (non-interactive backend confirmed)
- [ ] PNG dimensions at 150 DPI: width ≈ 1350 px, height ≈ 525 px (verify with `PIL.Image.open(BytesIO(png_bytes)).size`)
