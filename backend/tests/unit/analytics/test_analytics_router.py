"""Unit tests for GET /api/v1/analytics/kpis RBAC and date range defaults.

US-061 AC Scenario 4 — 403 for NURSE; 200 for MANAGER and ADMIN
US-061 AC Scenario 1 — 30-day default date range applied when params absent
US-061 AC Scenario 2 — explicit from/to params respected; from > to → 400
"""
from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.auth.jwt import TokenClaims
from app.main import app

# Fixture: a valid KpiResponse returned by KpiQueryService in all happy-path tests
_KPI_RESPONSE_FIXTURE = {
    "from_date": datetime.date(2026, 6, 17),
    "to_date": datetime.date(2026, 7, 17),
    "unit": None,
    "data": [],
    "total_rows": 0,
}


def _make_claims(role: str, units: list[str] | None = None) -> TokenClaims:
    """Create a TokenClaims object for testing."""
    return TokenClaims(
        sub="test-user-id",
        role=role,
        units=units or ["ICU", "WARD-A"],
        email="test@example.com",
        iat=int(datetime.datetime.now(datetime.timezone.utc).timestamp()),
        exp=int(
            (
                datetime.datetime.now(datetime.timezone.utc)
                + datetime.timedelta(hours=8)
            ).timestamp()
        ),
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestKpiRbac:
    def test_get_kpis_200_for_manager(self, client: TestClient) -> None:
        """MANAGER role can access /api/v1/analytics/kpis."""
        with (
            patch(
                "app.api.v1.routers.analytics.get_current_user",
                return_value=_make_claims("MANAGER"),
            ),
            patch(
                "app.api.v1.routers.analytics.get_read_db",
                new_callable=AsyncMock,
            ) as mock_session,
        ):
            mock_service = AsyncMock()
            mock_service.get_kpis = AsyncMock(return_value=_KPI_RESPONSE_FIXTURE)
            with patch(
                "app.api.v1.routers.analytics.KpiQueryService",
                return_value=mock_service,
            ):
                response = client.get("/api/v1/analytics/kpis")
        assert response.status_code == 200

    def test_get_kpis_200_for_admin(self, client: TestClient) -> None:
        """ADMIN role can access /api/v1/analytics/kpis."""
        with (
            patch(
                "app.api.v1.routers.analytics.get_current_user",
                return_value=_make_claims("ADMIN"),
            ),
            patch(
                "app.api.v1.routers.analytics.get_read_db",
                new_callable=AsyncMock,
            ) as mock_session,
        ):
            mock_service = AsyncMock()
            mock_service.get_kpis = AsyncMock(return_value=_KPI_RESPONSE_FIXTURE)
            with patch(
                "app.api.v1.routers.analytics.KpiQueryService",
                return_value=mock_service,
            ):
                response = client.get("/api/v1/analytics/kpis")
        assert response.status_code == 200

    @pytest.mark.parametrize("role", ["NURSE", "PHYSICIAN", "PHARMACIST", "PATIENT"])
    def test_get_kpis_403_for_disallowed_roles(self, client: TestClient, role: str) -> None:
        """NURSE, PHYSICIAN, PHARMACIST, PATIENT roles cannot access the endpoint."""
        with patch(
            "app.api.v1.routers.analytics.get_current_user",
            return_value=_make_claims(role),
        ):
            response = client.get("/api/v1/analytics/kpis")
        assert response.status_code == 403


class TestKpiDateRangeDefaults:
    def test_get_kpis_defaults_to_30_day_range(self, client: TestClient) -> None:
        """When no from/to params provided, effective_from = today - 30 days."""
        captured_from: list[datetime.date] = []

        async def _capture_get_kpis(
            self_inner, from_date, to_date, unit, accessible_units
        ):
            captured_from.append(from_date)
            return _KPI_RESPONSE_FIXTURE

        with (
            patch(
                "app.api.v1.routers.analytics.get_current_user",
                return_value=_make_claims("MANAGER"),
            ),
            patch(
                "app.api.v1.routers.analytics.get_read_db",
                new_callable=AsyncMock,
            ),
        ):
            mock_service = MagicMock()
            mock_service.get_kpis = _capture_get_kpis
            with patch(
                "app.api.v1.routers.analytics.KpiQueryService",
                return_value=mock_service,
            ):
                response = client.get("/api/v1/analytics/kpis")

        assert response.status_code == 200
        assert len(captured_from) == 1
        today = datetime.date.today()
        expected_from = today - datetime.timedelta(days=30)
        assert captured_from[0] == expected_from

    def test_get_kpis_respects_explicit_from_to(self, client: TestClient) -> None:
        """Explicit from/to params are forwarded to KpiQueryService unchanged."""
        captured: dict = {}

        async def _capture(self_inner, from_date, to_date, unit, accessible_units):
            captured["from"] = from_date
            captured["to"] = to_date
            return _KPI_RESPONSE_FIXTURE

        with (
            patch(
                "app.api.v1.routers.analytics.get_current_user",
                return_value=_make_claims("MANAGER"),
            ),
            patch(
                "app.api.v1.routers.analytics.get_read_db",
                new_callable=AsyncMock,
            ),
        ):
            mock_service = MagicMock()
            mock_service.get_kpis = _capture
            with patch(
                "app.api.v1.routers.analytics.KpiQueryService",
                return_value=mock_service,
            ):
                response = client.get("/api/v1/analytics/kpis?from=2026-07-01&to=2026-07-07")

        assert response.status_code == 200
        assert captured["from"] == datetime.date(2026, 7, 1)
        assert captured["to"] == datetime.date(2026, 7, 7)

    def test_get_kpis_400_when_from_after_to(self, client: TestClient) -> None:
        """from > to must return 400 Bad Request."""
        with patch(
            "app.api.v1.routers.analytics.get_current_user",
            return_value=_make_claims("MANAGER"),
        ):
            response = client.get("/api/v1/analytics/kpis?from=2026-07-15&to=2026-07-01")
        assert response.status_code == 400
        assert "from" in response.json()["detail"].lower()
