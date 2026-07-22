"""Unit tests for HIPAAAuditMiddleware (US-058/TASK-005).

Tests cover:
  - _is_phi_endpoint: PHI paths audited; excluded paths (/auth, /health) not audited
  - _extract_resource_info: entity type and ID extracted from URL
  - _extract_action: GET→read, POST→create, PATCH/approve→approve, PATCH/reject→reject
  - _extract_ip: X-Forwarded-For first public IP; falls back to client.host
  - write_audit_entry called with correct arguments for PHI GET and PATCH/approve
  - Audit write failure does not cause a 500 response
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.audit import (
    HIPAAAuditMiddleware,
    _extract_action,
    _extract_ip,
    _extract_resource_info,
    _is_phi_endpoint,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def test_app() -> FastAPI:
    """Minimal FastAPI app with HIPAAAuditMiddleware and stub PHI endpoints."""
    _app = FastAPI()
    _app.add_middleware(HIPAAAuditMiddleware)

    # Use path parameters so any UUID used in tests will match
    @_app.get("/api/v1/patients/{patient_id}")
    async def get_patient(patient_id: str):
        return {"id": patient_id}

    @_app.patch("/api/v1/documents/{doc_id}/approve")
    async def approve_doc(doc_id: str):
        return {"status": "approved"}

    @_app.get("/api/v1/auth/token")
    async def auth_token():
        return {"token": "test"}

    @_app.get("/health")
    async def health():
        return {"status": "ok"}

    return _app


@pytest.fixture()
def client(test_app: FastAPI) -> TestClient:
    return TestClient(test_app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# _is_phi_endpoint
# ---------------------------------------------------------------------------

class TestIsPhiEndpoint:
    def test_patient_path_audited(self):
        assert _is_phi_endpoint("/api/v1/patients/abc") is True

    def test_documents_path_audited(self):
        assert _is_phi_endpoint("/api/v1/documents") is True

    def test_medications_path_audited(self):
        assert _is_phi_endpoint("/api/v1/medications/123") is True

    def test_alerts_path_audited(self):
        assert _is_phi_endpoint("/api/v1/alerts/456") is True

    def test_beds_path_audited(self):
        assert _is_phi_endpoint("/api/v1/beds/789") is True

    def test_tasks_path_audited(self):
        assert _is_phi_endpoint("/api/v1/tasks/abc") is True

    def test_auth_path_excluded(self):
        assert _is_phi_endpoint("/api/v1/auth/token") is False

    def test_health_excluded(self):
        assert _is_phi_endpoint("/health") is False

    def test_ready_excluded(self):
        assert _is_phi_endpoint("/ready") is False

    def test_metrics_excluded(self):
        assert _is_phi_endpoint("/metrics") is False


# ---------------------------------------------------------------------------
# _extract_resource_info
# ---------------------------------------------------------------------------

class TestExtractResourceInfo:
    def test_patient_with_id(self):
        resource_type, resource_id = _extract_resource_info(
            "/api/v1/patients/550e8400-e29b-41d4-a716-446655440000"
        )
        assert resource_type == "patient"
        assert resource_id == "550e8400-e29b-41d4-a716-446655440000"

    def test_collection_path(self):
        resource_type, resource_id = _extract_resource_info("/api/v1/patients")
        assert resource_type == "patient"
        assert resource_id == "collection"

    def test_document_subpath_approve(self):
        resource_type, resource_id = _extract_resource_info(
            "/api/v1/documents/550e8400-e29b-41d4-a716-446655440000/approve"
        )
        assert resource_type == "document"
        assert resource_id == "550e8400-e29b-41d4-a716-446655440000"


# ---------------------------------------------------------------------------
# _extract_action
# ---------------------------------------------------------------------------

class TestExtractAction:
    def test_get_maps_to_read(self):
        assert _extract_action("/api/v1/patients/abc", "GET") == "read"

    def test_post_maps_to_create(self):
        assert _extract_action("/api/v1/patients", "POST") == "create"

    def test_patch_maps_to_update(self):
        assert _extract_action("/api/v1/patients/abc", "PATCH") == "update"

    def test_delete_maps_to_delete(self):
        assert _extract_action("/api/v1/patients/abc", "DELETE") == "delete"

    def test_approve_suffix_overrides_method(self):
        assert _extract_action("/api/v1/documents/abc/approve", "PATCH") == "approve"

    def test_reject_suffix_overrides_method(self):
        assert _extract_action("/api/v1/documents/abc/reject", "PATCH") == "reject"

    def test_resolve_suffix_overrides_method(self):
        assert _extract_action("/api/v1/alerts/abc/resolve", "PATCH") == "resolve"


# ---------------------------------------------------------------------------
# _extract_ip
# ---------------------------------------------------------------------------

class TestExtractIp:
    def test_xff_first_public_ip_used(self):
        class FakeRequest:
            headers = {"X-Forwarded-For": "203.0.113.5, 10.0.0.1, 172.16.0.1"}
            client = type("C", (), {"host": "127.0.0.1"})()

        assert _extract_ip(FakeRequest()) == "203.0.113.5"

    def test_skips_private_ips_in_xff(self):
        class FakeRequest:
            headers = {"X-Forwarded-For": "10.0.0.1, 172.16.0.1, 198.51.100.7"}
            client = type("C", (), {"host": "127.0.0.1"})()

        assert _extract_ip(FakeRequest()) == "198.51.100.7"

    def test_falls_back_to_client_host(self):
        class FakeRequest:
            headers = {}
            client = type("C", (), {"host": "192.168.1.50"})()

        assert _extract_ip(FakeRequest()) == "192.168.1.50"

    def test_no_client_returns_none(self):
        class FakeRequest:
            headers = {}
            client = None

        assert _extract_ip(FakeRequest()) is None


# ---------------------------------------------------------------------------
# Middleware integration tests
# ---------------------------------------------------------------------------

class TestHIPAAAuditMiddlewareIntegration:
    @patch("app.middleware.audit.write_audit_entry", new_callable=AsyncMock)
    def test_phi_get_calls_write_audit_entry(self, mock_write, client):
        """GET on a PHI endpoint must trigger write_audit_entry with action=read."""
        patient_id = "550e8400-e29b-41d4-a716-446655440000"
        response = client.get(f"/api/v1/patients/{patient_id}")
        assert response.status_code == 200
        mock_write.assert_called_once()
        kwargs = mock_write.call_args.kwargs
        assert kwargs["action"] == "read"
        assert kwargs["resource_type"] == "patient"

    @patch("app.middleware.audit.write_audit_entry", new_callable=AsyncMock)
    def test_approve_path_creates_approve_action(self, mock_write, client):
        """PATCH /documents/{id}/approve must audit as action=approve (AC Scenario 2)."""
        doc_id = "550e8400-e29b-41d4-a716-446655440000"
        response = client.patch(f"/api/v1/documents/{doc_id}/approve")
        assert response.status_code == 200
        kwargs = mock_write.call_args.kwargs
        assert kwargs["action"] == "approve"
        assert kwargs["resource_type"] == "document"

    @patch("app.middleware.audit.write_audit_entry", new_callable=AsyncMock)
    def test_excluded_auth_path_no_audit(self, mock_write, client):
        """Auth endpoints must never produce an audit entry."""
        response = client.get("/api/v1/auth/token")
        assert response.status_code == 200
        mock_write.assert_not_called()

    @patch("app.middleware.audit.write_audit_entry", new_callable=AsyncMock)
    def test_health_path_no_audit(self, mock_write, client):
        response = client.get("/health")
        assert response.status_code == 200
        mock_write.assert_not_called()

    @patch(
        "app.middleware.audit.write_audit_entry",
        new_callable=AsyncMock,
        side_effect=Exception("DB unavailable"),
    )
    def test_audit_write_failure_does_not_break_response(self, mock_write, client):
        """Audit DB failure must NOT cause a 500 — response must still succeed."""
        patient_id = "550e8400-e29b-41d4-a716-446655440000"
        response = client.get(f"/api/v1/patients/{patient_id}")
        # Response must still be 200 — audit errors are swallowed
        assert response.status_code == 200
