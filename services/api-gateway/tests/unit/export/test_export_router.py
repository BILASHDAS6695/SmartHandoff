"""Unit tests for app/routers/analytics_export.py.

US-063 AC Scenario 4 — RBAC enforcement (403 for non-manager)
US-063 AC Scenario 1, 2 — date validation
"""
from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from app.routers.analytics_export import export_kpi_report, _validate_date_range


class TestValidateDateRange:
    """Tests for the _validate_date_range function."""

    def test_passes_for_valid_range(self):
        """Valid date range (from <= to) passes without raising."""
        _validate_date_range(
            datetime.date(2026, 1, 1),
            datetime.date(2026, 1, 31),
        )  # must not raise

    def test_passes_for_same_day_range(self):
        """Same day range (from == to) passes."""
        _validate_date_range(
            datetime.date(2026, 1, 1),
            datetime.date(2026, 1, 1),
        )  # must not raise

    def test_raises_for_inverted_range(self):
        """from > to raises 400 Bad Request."""
        with pytest.raises(HTTPException) as exc_info:
            _validate_date_range(
                datetime.date(2026, 2, 1),
                datetime.date(2026, 1, 1),
            )
        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert "from" in exc_info.value.detail.lower()

    def test_raises_for_range_exceeding_max_days(self):
        """Date range > 366 days raises 400 Bad Request."""
        with pytest.raises(HTTPException) as exc_info:
            _validate_date_range(
                datetime.date(2025, 1, 1),
                datetime.date(2026, 2, 2),  # 397 days
            )
        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert "366" in exc_info.value.detail

    def test_passes_for_exactly_366_days(self):
        """Exactly 366 days is accepted."""
        _validate_date_range(
            datetime.date(2025, 1, 1),
            datetime.date(2026, 1, 1),
        )  # must not raise


class TestExportRbac:
    """Tests for RBAC enforcement on the export endpoint."""

    def test_manager_role_passes_rbac(self, manager_token):
        """Manager role is allowed."""
        from app.routers.analytics_export import _require_manager_or_admin
        result = _require_manager_or_admin(manager_token)
        assert result == manager_token

    def test_admin_role_passes_rbac(self, admin_token):
        """Admin role is allowed."""
        from app.routers.analytics_export import _require_manager_or_admin
        result = _require_manager_or_admin(admin_token)
        assert result == admin_token

    def test_nurse_role_fails_rbac(self, nurse_token):
        """Nurse role is denied."""
        from app.routers.analytics_export import _require_manager_or_admin
        with pytest.raises(HTTPException) as exc_info:
            _require_manager_or_admin(nurse_token)
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
