"""Shared fixtures for US-063 export unit tests."""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest


@dataclass
class KpiDataPoint:
    """Mock KpiDataPoint for testing."""
    date: datetime.date
    unit_name: str
    avg_los_hours: float
    discharge_count: int
    readmission_rate: float
    medication_reconciliation_rate: float
    handoff_completion_rate: float
    agent_success_rate: float


@pytest.fixture()
def kpi_fixture() -> list[KpiDataPoint]:
    """Fixture: 5 de-identified KPI data points (safe schema)."""
    base = datetime.date(2026, 1, 1)
    return [
        KpiDataPoint(
            date=base + datetime.timedelta(days=i),
            unit_name=f"Unit-{i % 3 + 1}",
            avg_los_hours=24.0 + i * 0.5,
            discharge_count=10 + i,
            readmission_rate=0.05 + i * 0.001,
            medication_reconciliation_rate=0.90 - i * 0.001,
            handoff_completion_rate=0.85 + i * 0.002,
            agent_success_rate=0.92 + i * 0.001,
        )
        for i in range(5)
    ]


@pytest.fixture()
def manager_token() -> MagicMock:
    """Fixture: TokenClaims with role=MANAGER."""
    claims = MagicMock()
    claims.role = "manager"
    claims.units = ["Unit-1", "Unit-2"]
    claims.hospital_name = "General Hospital"
    return claims


@pytest.fixture()
def nurse_token() -> MagicMock:
    """Fixture: TokenClaims with role=NURSE."""
    claims = MagicMock()
    claims.role = "nurse"
    claims.units = ["Unit-1"]
    claims.hospital_name = "General Hospital"
    return claims


@pytest.fixture()
def admin_token() -> MagicMock:
    """Fixture: TokenClaims with role=ADMIN."""
    claims = MagicMock()
    claims.role = "admin"
    claims.units = ["Unit-1", "Unit-2", "Unit-3"]
    claims.hospital_name = "General Hospital"
    return claims


@pytest.fixture()
def mock_query_service(kpi_fixture) -> AsyncMock:
    """Fixture: mock KpiQueryService."""
    svc = AsyncMock()
    svc.get_kpi_data.return_value = kpi_fixture
    return svc
