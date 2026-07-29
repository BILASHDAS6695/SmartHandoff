"""Unit tests for the export date resolver.

Design refs:
    US-062 AC Scenario 1 — export covers previous day
    US-062 AC Scenario 3 — same date on re-run (idempotent)
"""
from __future__ import annotations

import datetime
import sys

import pytest

# Add the parent directory to the path so we can import app modules
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent))

from app.date_utils import get_target_date


class TestGetTargetDate:
    """Test cases for export date resolution."""

    def test_returns_yesterday_utc_by_default(self, monkeypatch):
        """Default behavior should return yesterday in UTC."""
        # Clear the override env var
        import app.config as cfg
        monkeypatch.setattr(cfg.Config, "EXPORT_DATE_OVERRIDE", None)

        result = get_target_date()
        yesterday = (
            datetime.datetime.now(tz=datetime.timezone.utc).date()
            - datetime.timedelta(days=1)
        )
        assert result == yesterday

    def test_respects_export_date_override(self, monkeypatch):
        """EXPORT_DATE_OVERRIDE env var should override the default."""
        import app.config as cfg
        monkeypatch.setattr(cfg.Config, "EXPORT_DATE_OVERRIDE", "2026-01-15")

        result = get_target_date()
        assert result == datetime.date(2026, 1, 15)

    def test_raises_on_invalid_override_format(self, monkeypatch):
        """Invalid EXPORT_DATE_OVERRIDE format should raise ValueError."""
        import app.config as cfg
        monkeypatch.setattr(cfg.Config, "EXPORT_DATE_OVERRIDE", "15-01-2026")

        with pytest.raises(ValueError, match="EXPORT_DATE_OVERRIDE must be YYYY-MM-DD"):
            get_target_date()

    def test_iso_format_parsing(self, monkeypatch):
        """Valid ISO format (YYYY-MM-DD) should parse correctly."""
        import app.config as cfg
        monkeypatch.setattr(cfg.Config, "EXPORT_DATE_OVERRIDE", "2026-12-31")

        result = get_target_date()
        assert result == datetime.date(2026, 12, 31)
