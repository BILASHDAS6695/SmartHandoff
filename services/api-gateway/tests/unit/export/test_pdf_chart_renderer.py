"""Unit tests for app/export/chart_renderer.py.

US-063 AC Scenario 2 — 5 chart images embedded in the PDF
"""
from __future__ import annotations

import pytest

from app.export.chart_renderer import ChartImage, render_all_charts

_PNG_MAGIC = b"\x89PNG"
_EXPECTED_CHART_COUNT = 5


class TestRenderAllCharts:
    """Tests for the render_all_charts function."""

    def test_returns_five_chart_images(self, kpi_fixture):
        """render_all_charts returns exactly 5 ChartImage instances."""
        charts = render_all_charts(kpi_fixture)
        assert len(charts) == _EXPECTED_CHART_COUNT

    def test_all_charts_are_chart_image_instances(self, kpi_fixture):
        """All returned objects are ChartImage instances."""
        charts = render_all_charts(kpi_fixture)
        for chart in charts:
            assert isinstance(chart, ChartImage)

    def test_all_png_bytes_start_with_png_magic(self, kpi_fixture):
        """All PNG bytes start with the PNG magic header."""
        charts = render_all_charts(kpi_fixture)
        for chart in charts:
            assert chart.png_bytes[:4] == _PNG_MAGIC, (
                f"Chart '{chart.title}' does not have PNG magic bytes"
            )

    def test_each_chart_has_non_empty_title(self, kpi_fixture):
        """All charts have non-empty title strings."""
        charts = render_all_charts(kpi_fixture)
        for chart in charts:
            assert chart.title
            assert len(chart.title) > 0

    def test_empty_data_returns_five_empty_charts(self):
        """Empty KPI data returns 5 ChartImage instances (no error)."""
        charts = render_all_charts([])
        assert len(charts) == _EXPECTED_CHART_COUNT
        for chart in charts:
            assert isinstance(chart, ChartImage)
            assert chart.png_bytes[:4] == _PNG_MAGIC
