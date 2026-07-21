"""Unit and integration tests for HIPAAAuditMiddleware.

Tests cover:
  - _is_phi_endpoint() helper logic
  - _extract_resource_info() helper logic
  - Middleware creates audit record for PHI endpoints
  - Middleware skips audit for excluded/non-PHI endpoints
  - Audit write failure does NOT surface as 5xx (fire-and-forget contract)

Integration tests use httpx.AsyncClient with the FastAPI test app.
Audit write side-effects are isolated via unittest.mock.patch on
_write_audit_record so tests are hermetic (no real DB required).
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.middleware.audit import (
    HIPAAAuditMiddleware,
    _extract_resource_info,
    _is_phi_endpoint,
)


# ── Minimal test FastAPI app ──────────────────────────────────────────────────

def _make_test_app(user_id: uuid.UUID | None = None, user_role: str | None = None) -> FastAPI:
    """Return a minimal FastAPI app with HIPAAAuditMiddleware registered."""
    test_app = FastAPI()
    test_app.add_middleware(HIPAAAuditMiddleware)

    @test_app.get("/api/v1/patients/{patient_id}")
    async def get_patient(request: Request, patient_id: str):
        request.state.user_id = user_id
        request.state.user_role = user_role
        return JSONResponse({"id": patient_id})

    @test_app.get("/health")
    async def health():
        return JSONResponse({"status": "ok"})

    @test_app.get("/api/v1/encounters/{encounter_id}")
    async def get_encounter(request: Request, encounter_id: str):
        request.state.user_id = user_id
        request.state.user_role = user_role
        return JSONResponse({"id": encounter_id})

    @test_app.get("/api/v1/non-phi")
    async def non_phi():
        return JSONResponse({"data": "public"})

    return test_app


# ── Unit tests for helper functions ──────────────────────────────────────────

class TestIsPhiEndpoint:
    def test_phi_path_patients(self):
        assert _is_phi_endpoint("/api/v1/patients/abc-123") is True

    def test_phi_path_encounters(self):
        assert _is_phi_endpoint("/api/v1/encounters") is True

    def test_phi_path_documents(self):
        assert _is_phi_endpoint("/api/v1/documents/xyz") is True

    def test_phi_path_admin_audit(self):
        assert _is_phi_endpoint("/api/v1/admin/audit") is True

    def test_excluded_health(self):
        assert _is_phi_endpoint("/health") is False

    def test_excluded_ready(self):
        assert _is_phi_endpoint("/ready") is False

    def test_excluded_metrics(self):
        assert _is_phi_endpoint("/metrics") is False

    def test_excluded_docs(self):
        assert _is_phi_endpoint("/docs") is False

    def test_excluded_openapi_json(self):
        assert _is_phi_endpoint("/openapi.json") is False

    def test_non_phi_path(self):
        assert _is_phi_endpoint("/api/v1/non-phi") is False


class TestExtractResourceInfo:
    def test_patients_with_id(self):
        resource_type, resource_id = _extract_resource_info(
            "/api/v1/patients/abc-123"
        )
        assert resource_type == "patient"
        assert resource_id == "abc-123"

    def test_encounters_collection(self):
        resource_type, resource_id = _extract_resource_info("/api/v1/encounters")
        assert resource_type == "encounter"
        assert resource_id == "collection"

    def test_nested_path(self):
        resource_type, resource_id = _extract_resource_info(
            "/api/v1/encounters/xyz-789/documents"
        )
        assert resource_type == "encounter"
        assert resource_id == "xyz-789"


# ── Middleware integration tests ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_middleware_creates_audit_log_entry_for_phi_endpoint():
    """Middleware calls _write_audit_record for PHI endpoints."""
    user_id = uuid.uuid4()
    app = _make_test_app(user_id=user_id, user_role="clinician")

    with patch(
        "app.middleware.audit._write_audit_record", new_callable=AsyncMock
    ) as mock_write:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            patient_id = uuid.uuid4()
            response = await client.get(f"/api/v1/patients/{patient_id}")

    assert response.status_code == 200
    mock_write.assert_called_once()
    call_kwargs = mock_write.call_args.kwargs
    assert call_kwargs["action"] == "read"
    assert call_kwargs["resource_type"] == "patient"
    assert call_kwargs["endpoint"] == f"/api/v1/patients/{patient_id}"


@pytest.mark.asyncio
async def test_middleware_does_not_audit_health_endpoint():
    """Middleware does NOT call _write_audit_record for /health."""
    app = _make_test_app()

    with patch(
        "app.middleware.audit._write_audit_record", new_callable=AsyncMock
    ) as mock_write:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health")

    assert response.status_code == 200
    mock_write.assert_not_called()


@pytest.mark.asyncio
async def test_middleware_does_not_audit_non_phi_endpoint():
    """Middleware does NOT call _write_audit_record for non-PHI paths."""
    app = _make_test_app()

    with patch(
        "app.middleware.audit._write_audit_record", new_callable=AsyncMock
    ) as mock_write:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/non-phi")

    assert response.status_code == 200
    mock_write.assert_not_called()


@pytest.mark.asyncio
async def test_middleware_audit_write_failure_does_not_fail_request():
    """Audit write failure (DB down) must NOT propagate as 5xx to the client."""
    app = _make_test_app(user_id=uuid.uuid4())

    async def _failing_write(**kwargs):
        raise RuntimeError("Simulated DB failure")

    with patch("app.middleware.audit._write_audit_record", side_effect=_failing_write):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/api/v1/patients/{uuid.uuid4()}")

    # The route must respond 200 even though audit write raised
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_middleware_records_correct_action_for_post():
    """POST requests map to 'create' action in the audit log."""
    app = FastAPI()
    app.add_middleware(HIPAAAuditMiddleware)

    @app.post("/api/v1/patients")
    async def create_patient(request: Request):
        request.state.user_id = uuid.uuid4()
        request.state.user_role = "admin"
        return JSONResponse({"id": str(uuid.uuid4())}, status_code=201)

    with patch(
        "app.middleware.audit._write_audit_record", new_callable=AsyncMock
    ) as mock_write:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/api/v1/patients", json={})

    assert response.status_code == 201
    mock_write.assert_called_once()
    assert mock_write.call_args.kwargs["action"] == "create"


@pytest.mark.asyncio
async def test_middleware_x_forwarded_for_is_used_for_ip():
    """Leftmost IP in X-Forwarded-For header is recorded as ip_address."""
    app = _make_test_app(user_id=uuid.uuid4())

    with patch(
        "app.middleware.audit._write_audit_record", new_callable=AsyncMock
    ) as mock_write:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                f"/api/v1/patients/{uuid.uuid4()}",
                headers={"x-forwarded-for": "1.2.3.4, 10.0.0.1, 172.16.0.1"},
            )

    assert response.status_code == 200
    assert mock_write.call_args.kwargs["ip_address"] == "1.2.3.4"
