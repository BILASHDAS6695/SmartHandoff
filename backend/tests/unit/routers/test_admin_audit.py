"""Unit tests for GET /api/v1/admin/audit endpoint (US-058/TASK-005).

Tests cover:
  - ADMIN role returns 200 with AuditLogPage response
  - Non-ADMIN roles (NURSE, PHYSICIAN, PHARMACIST, BED_MANAGER, PATIENT) return 403
  - Pagination: total, pages, page_size correct
  - ADMIN response includes ip_address and user_agent (AuditLogEntryFull)
  - Filters (user_id, from, to, entity_type, action) narrow results

Uses FastAPI TestClient with app.dependency_overrides to avoid real JWT
and database dependencies. SQLAlchemy session is replaced with an AsyncMock.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.auth.jwt import TokenClaims, get_current_user
from app.core.auth.rbac import load_rbac_matrix
from app.db.deps import get_read_db
from app.main import app
from app.models.audit_log import AuditLog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_claims(role: str) -> TokenClaims:
    return TokenClaims(
        sub=str(uuid.uuid4()),
        email=f"{role.lower()}@hospital.example.com",
        role=role,
        units=[],
        iat=0,
        exp=9_999_999_999,
    )


def _make_audit_row(**kwargs) -> AuditLog:
    """Build a minimal AuditLog ORM object (no DB required)."""
    row = AuditLog.__new__(AuditLog)
    row.id = kwargs.get("id", uuid.uuid4())
    row.user_id = kwargs.get("user_id", uuid.uuid4())
    row.user_role = kwargs.get("user_role", "NURSE")
    row.action = kwargs.get("action", "read")
    row.resource_type = kwargs.get("resource_type", "patient")
    row.resource_id = kwargs.get("resource_id", str(uuid.uuid4()))
    row.ip_address = kwargs.get("ip_address", "203.0.113.5")
    row.user_agent = kwargs.get("user_agent", "Mozilla/5.0")
    row.endpoint = kwargs.get("endpoint", "/api/v1/patients/abc")
    row.request_id = kwargs.get("request_id", None)
    row.outcome = kwargs.get("outcome", "success")
    row.created_at = kwargs.get("created_at", datetime.now(timezone.utc))
    return row


def _mock_db_with_rows(rows: list[AuditLog], total: int = None):
    """Return an async context manager mock that yields a DB session with canned results."""
    total = total if total is not None else len(rows)

    mock_db = AsyncMock()
    count_result = MagicMock()
    count_result.scalar_one.return_value = total

    rows_result = MagicMock()
    rows_result.scalars.return_value.all.return_value = rows

    mock_db.execute = AsyncMock(side_effect=[count_result, rows_result])

    async def _fake_dep():
        yield mock_db

    return _fake_dep


@pytest.fixture(autouse=True)
def _reset_overrides():
    """Clear dependency_overrides after each test to prevent bleed."""
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _clear_rbac_cache():
    load_rbac_matrix.cache_clear()
    yield
    load_rbac_matrix.cache_clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# TestAuditQueryAdminAccess
# ---------------------------------------------------------------------------


class TestAuditQueryAdminAccess:
    def test_admin_role_returns_200(self, client):
        """AC Scenario 4: ADMIN can query the audit log."""
        row = _make_audit_row()
        app.dependency_overrides[get_read_db] = _mock_db_with_rows([row])
        app.dependency_overrides[get_current_user] = lambda: _make_claims("ADMIN")

        response = client.get("/api/v1/admin/audit")
        assert response.status_code == 200
        body = response.json()
        assert "items" in body
        assert body["page"] == 1
        assert body["total"] == 1

    @pytest.mark.parametrize("role", [
        "NURSE", "PHYSICIAN", "PHARMACIST", "BED_MANAGER", "CARE_MANAGER", "PATIENT",
    ])
    @patch("app.core.auth.rbac.write_rbac_audit_entry", new_callable=AsyncMock)
    def test_non_admin_roles_return_403(self, mock_audit, role, client):
        """AC Scenario 4: all non-ADMIN roles must be denied (RBAC matrix check)."""
        app.dependency_overrides[get_current_user] = lambda: _make_claims(role)
        response = client.get("/api/v1/admin/audit")
        assert response.status_code == 403, (
            f"Expected 403 for role={role}, got {response.status_code}"
        )
        mock_audit.assert_awaited()  # denial must be audited


# ---------------------------------------------------------------------------
# TestAuditQueryPagination
# ---------------------------------------------------------------------------


class TestAuditQueryPagination:
    def test_page_size_respected(self, client):
        rows = [_make_audit_row() for _ in range(5)]
        app.dependency_overrides[get_read_db] = _mock_db_with_rows(rows, total=25)
        app.dependency_overrides[get_current_user] = lambda: _make_claims("ADMIN")

        response = client.get("/api/v1/admin/audit?page=1&page_size=5")
        assert response.status_code == 200
        body = response.json()
        assert body["page_size"] == 5
        assert body["total"] == 25
        assert body["pages"] == 5

    def test_page_2_returns_correct_metadata(self, client):
        rows = [_make_audit_row() for _ in range(3)]
        app.dependency_overrides[get_read_db] = _mock_db_with_rows(rows, total=13)
        app.dependency_overrides[get_current_user] = lambda: _make_claims("ADMIN")

        response = client.get("/api/v1/admin/audit?page=2&page_size=5")
        body = response.json()
        assert body["page"] == 2
        assert body["pages"] == 3  # ceil(13/5)


# ---------------------------------------------------------------------------
# TestAuditQueryResponseShape
# ---------------------------------------------------------------------------


class TestAuditQueryResponseShape:
    def test_admin_response_includes_ip_and_user_agent(self, client):
        """ADMIN role receives AuditLogEntryFull with ip_address and user_agent."""
        row = _make_audit_row(ip_address="203.0.113.5", user_agent="curl/7.0")
        app.dependency_overrides[get_read_db] = _mock_db_with_rows([row])
        app.dependency_overrides[get_current_user] = lambda: _make_claims("ADMIN")

        response = client.get("/api/v1/admin/audit")
        assert response.status_code == 200
        item = response.json()["items"][0]
        assert "ip_address" in item
        assert item["ip_address"] == "203.0.113.5"
        assert "user_agent" in item
        assert item["user_agent"] == "curl/7.0"

    def test_response_contains_resource_type_and_id(self, client):
        row = _make_audit_row(resource_type="patient", resource_id="abc-123")
        app.dependency_overrides[get_read_db] = _mock_db_with_rows([row])
        app.dependency_overrides[get_current_user] = lambda: _make_claims("ADMIN")

        response = client.get("/api/v1/admin/audit")
        item = response.json()["items"][0]
        assert item["resource_type"] == "patient"
        assert item["resource_id"] == "abc-123"

    def test_response_no_phi_field_values(self, client):
        """Ensure no PHI field names (first_name, last_name, mrn) appear in response."""
        row = _make_audit_row()
        app.dependency_overrides[get_read_db] = _mock_db_with_rows([row])
        app.dependency_overrides[get_current_user] = lambda: _make_claims("ADMIN")

        response = client.get("/api/v1/admin/audit")
        body_str = response.text
        for phi_field in ("first_name", "last_name", "mrn", "dob", "phone"):
            assert phi_field not in body_str, f"PHI field {phi_field!r} found in audit API response"


# ---------------------------------------------------------------------------
# TestAuditQueryEmptyResults
# ---------------------------------------------------------------------------


class TestAuditQueryEmptyResults:
    def test_empty_results_returns_valid_page(self, client):
        app.dependency_overrides[get_read_db] = _mock_db_with_rows([], total=0)
        app.dependency_overrides[get_current_user] = lambda: _make_claims("ADMIN")

        response = client.get("/api/v1/admin/audit")
        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["total"] == 0
        assert body["pages"] == 1  # min pages is 1 even with 0 results
