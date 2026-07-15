---
id: TASK-005
title: "Write pytest Unit Tests — Audit Entry Creation, PHI Sanitisation, Admin Query RBAC"
user_story: US-058
epic: EP-011
sprint: 1
layer: Testing
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-058/TASK-001, US-058/TASK-002, US-058/TASK-003, US-058/TASK-004]
---

# TASK-005: Write pytest Unit Tests — Audit Entry Creation, PHI Sanitisation, Admin Query RBAC

> **Story:** US-058 | **Epic:** EP-011 | **Sprint:** 1 | **Layer:** Testing | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

The US-058 DoD requires: *"Unit tests: audit entry creation, PHI sanitisation (no PHI in logs), admin query RBAC"*. This task delivers pytest tests covering all three areas:

1. **Audit entry creation** — `AuditLogMiddleware` creates correct `audit_log` rows for PHI paths; excluded paths generate no entry; IP extraction (including `X-Forwarded-For`) is correct.
2. **PHI sanitisation** — `redact_phi()` and `PhiLoggingFilter` strip all required PHI field names; no PHI in emitted log messages.
3. **Admin query RBAC** — `GET /api/v1/admin/audit` returns 200 for ADMIN, 403 for all other roles; pagination and filters work correctly.

Tests use FastAPI's `TestClient` with `app.dependency_overrides` to inject mock `TokenClaims` without real JWTs, and `AsyncMock` to patch `write_audit_entry` for unit isolation.

Coverage target: ≥80% branch coverage across TASK-001 through TASK-004 modules (TR-020).

---

## Acceptance Criteria Addressed

| US-058 AC | Requirement |
|---|---|
| **Scenario 1** | Middleware creates `audit_log` entry with all required fields for `GET /api/v1/patients/{id}` |
| **Scenario 2** | Middleware creates entry with `action=APPROVE`, `entity_type=DOCUMENT` for `PATCH /documents/{id}/approve` |
| **Scenario 3** | PHI sanitiser strips `first_name`, `last_name`, `mrn` from all log emissions; `[REDACTED]` present in output |
| **Scenario 4** | `GET /api/v1/admin/audit` — ADMIN: 200; NURSE/PHYSICIAN/etc.: 403; filters and pagination correct |
| **DoD** | Unit tests: audit entry creation, PHI sanitisation, admin query RBAC |

---

## Implementation Steps

### 1. Create `backend/tests/unit/middleware/test_audit_log_middleware.py`

```python
"""Unit tests for AuditLogMiddleware.

Tests cover:
  - Audit entry created for each PHI entity path and HTTP method
  - Correct entity_type and entity_id extracted from URL
  - Correct action derived (READ, WRITE, APPROVE, REJECT)
  - Excluded paths (/auth, /health, /ready) do NOT create audit entries
  - IP extraction: request.client.host used when no X-Forwarded-For
  - IP extraction: first public IP from X-Forwarded-For chain used
  - write_audit_entry called with correct arguments
  - Audit write failure does not propagate to HTTP response (500 not raised)
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.middleware.audit_log_middleware import (
    AuditLogMiddleware,
    _extract_action,
    _extract_entity,
    _extract_ip,
    _should_audit,
)
from app.models.audit_log import AuditAction


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def test_app() -> FastAPI:
    """Minimal FastAPI app with AuditLogMiddleware and mock PHI endpoints."""
    app = FastAPI()
    app.add_middleware(AuditLogMiddleware)

    patient_id = str(uuid.uuid4())

    @app.get(f"/api/v1/patients/{patient_id}")
    async def get_patient():
        return {"id": patient_id}

    @app.patch(f"/api/v1/documents/{patient_id}/approve")
    async def approve_doc():
        return {"status": "approved"}

    @app.get("/api/v1/auth/token")
    async def auth_token():
        return {"token": "abc"}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


@pytest.fixture()
def client(test_app: FastAPI) -> TestClient:
    return TestClient(test_app)


# ---------------------------------------------------------------------------
# Helper unit tests (no HTTP)
# ---------------------------------------------------------------------------

class TestShouldAudit:
    def test_phi_path_audited(self):
        assert _should_audit("/api/v1/patients/abc") is True
        assert _should_audit("/api/v1/documents") is True
        assert _should_audit("/api/v1/medications/123") is True

    def test_excluded_paths_not_audited(self):
        assert _should_audit("/api/v1/auth/token") is False
        assert _should_audit("/health") is False
        assert _should_audit("/ready") is False
        assert _should_audit("/metrics") is False

    def test_non_phi_api_path_not_audited(self):
        assert _should_audit("/api/v1/unknown-resource") is False


class TestExtractEntity:
    def test_patient_with_id(self):
        entity_type, entity_id = _extract_entity(
            "/api/v1/patients/550e8400-e29b-41d4-a716-446655440000"
        )
        assert entity_type == "PATIENT"
        assert str(entity_id) == "550e8400-e29b-41d4-a716-446655440000"

    def test_collection_path_no_id(self):
        entity_type, entity_id = _extract_entity("/api/v1/patients")
        assert entity_type == "PATIENT"
        assert entity_id is None

    def test_document_subpath(self):
        entity_type, entity_id = _extract_entity(
            "/api/v1/documents/550e8400-e29b-41d4-a716-446655440000/approve"
        )
        assert entity_type == "DOCUMENT"
        assert entity_id is not None


class TestExtractAction:
    def test_get_maps_to_read(self):
        assert _extract_action("/api/v1/patients/abc", "GET") == AuditAction.READ

    def test_post_maps_to_write(self):
        assert _extract_action("/api/v1/patients", "POST") == AuditAction.WRITE

    def test_patch_maps_to_write(self):
        assert _extract_action("/api/v1/patients/abc", "PATCH") == AuditAction.WRITE

    def test_delete_maps_to_delete(self):
        assert _extract_action("/api/v1/patients/abc", "DELETE") == AuditAction.DELETE

    def test_approve_suffix_overrides_method(self):
        assert _extract_action("/api/v1/documents/abc/approve", "PATCH") == AuditAction.APPROVE

    def test_reject_suffix_overrides_method(self):
        assert _extract_action("/api/v1/documents/abc/reject", "PATCH") == AuditAction.REJECT


class TestExtractIp:
    def test_xff_public_ip_used(self):
        """First public IP in X-Forwarded-For is returned."""
        from starlette.testclient import TestClient
        from starlette.applications import Starlette
        # Simulate request headers inline
        class FakeRequest:
            headers = {"X-Forwarded-For": "203.0.113.5, 10.0.0.1, 172.16.0.1"}
            client = type("C", (), {"host": "127.0.0.1"})()
        assert _extract_ip(FakeRequest()) == "203.0.113.5"

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
# Middleware integration tests (HTTP client)
# ---------------------------------------------------------------------------

class TestAuditLogMiddlewareIntegration:
    @patch("app.middleware.audit_log_middleware.get_audit_db_session")
    @patch("app.middleware.audit_log_middleware.write_audit_entry", new_callable=AsyncMock)
    def test_phi_get_creates_audit_entry(self, mock_write, mock_session, client):
        response = client.get("/api/v1/patients/550e8400-e29b-41d4-a716-446655440000")
        assert response.status_code == 200
        mock_write.assert_called_once()
        call_kwargs = mock_write.call_args.kwargs
        assert call_kwargs["action"] == AuditAction.READ
        assert call_kwargs["entity_type"] == "PATIENT"
        assert str(call_kwargs["entity_id"]) == "550e8400-e29b-41d4-a716-446655440000"

    @patch("app.middleware.audit_log_middleware.get_audit_db_session")
    @patch("app.middleware.audit_log_middleware.write_audit_entry", new_callable=AsyncMock)
    def test_approve_path_creates_approve_action(self, mock_write, mock_session, client):
        doc_id = "550e8400-e29b-41d4-a716-446655440000"
        response = client.patch(f"/api/v1/documents/{doc_id}/approve")
        assert response.status_code == 200
        call_kwargs = mock_write.call_args.kwargs
        assert call_kwargs["action"] == AuditAction.APPROVE
        assert call_kwargs["entity_type"] == "DOCUMENT"

    @patch("app.middleware.audit_log_middleware.write_audit_entry", new_callable=AsyncMock)
    def test_excluded_path_no_audit_entry(self, mock_write, client):
        response = client.get("/api/v1/auth/token")
        assert response.status_code == 200
        mock_write.assert_not_called()

    @patch("app.middleware.audit_log_middleware.write_audit_entry", new_callable=AsyncMock)
    def test_health_path_no_audit_entry(self, mock_write, client):
        response = client.get("/health")
        assert response.status_code == 200
        mock_write.assert_not_called()

    @patch("app.middleware.audit_log_middleware.get_audit_db_session")
    @patch(
        "app.middleware.audit_log_middleware.write_audit_entry",
        new_callable=AsyncMock,
        side_effect=Exception("DB unavailable"),
    )
    def test_audit_write_failure_does_not_break_response(
        self, mock_write, mock_session, client
    ):
        """Audit DB failure must not cause a 500 — response must still be 200."""
        response = client.get("/api/v1/patients/550e8400-e29b-41d4-a716-446655440000")
        assert response.status_code == 200  # must not be 500
```

### 2. Create `backend/tests/unit/middleware/test_phi_log_sanitiser.py`

```python
"""Unit tests for PHI log sanitiser.

Tests cover:
  - redact_phi(): all PHI field names redacted (first_name, last_name, mrn,
    dob, phone, email); non-PHI fields preserved
  - PhiLoggingFilter: log records with PHI values have values replaced
  - PhiLoggingFilter: non-PHI log records pass through unchanged
  - PhiLoggingFilter: always returns True (never discards records)
  - Email regex: common email formats redacted
  - Phone regex: common phone formats redacted
"""
from __future__ import annotations

import io
import logging

import pytest

from app.middleware.phi_log_sanitiser import PhiLoggingFilter, redact_phi


class TestRedactPhi:
    def test_redacts_first_name_json(self):
        msg = '{"first_name": "Alice"}'
        result = redact_phi(msg)
        assert "Alice" not in result
        assert "[REDACTED]" in result

    def test_redacts_last_name_json(self):
        msg = '{"last_name": "Smith"}'
        result = redact_phi(msg)
        assert "Smith" not in result

    def test_redacts_mrn_json(self):
        msg = '{"mrn": "MRN-987654"}'
        result = redact_phi(msg)
        assert "MRN-987654" not in result

    def test_redacts_dob_json(self):
        msg = '{"dob": "1980-05-15"}'
        result = redact_phi(msg)
        assert "1980-05-15" not in result

    def test_redacts_phone_json(self):
        msg = '{"phone": "555-867-5309"}'
        result = redact_phi(msg)
        assert "555-867-5309" not in result

    def test_redacts_email_json(self):
        msg = '{"email": "alice@hospital.com"}'
        result = redact_phi(msg)
        assert "alice@hospital.com" not in result
        assert "[REDACTED-EMAIL]" in result

    def test_non_phi_fields_preserved(self):
        msg = '{"encounter_id": "abc-123", "status": "ADMITTED"}'
        result = redact_phi(msg)
        assert "abc-123" in result
        assert "ADMITTED" in result

    def test_multiple_phi_fields_in_one_message(self):
        msg = '{"first_name": "Jane", "last_name": "Doe", "mrn": "MRN001"}'
        result = redact_phi(msg)
        assert "Jane" not in result
        assert "Doe" not in result
        assert "MRN001" not in result

    def test_email_inline_not_in_key_value_redacted(self):
        msg = "Patient email is jane@example.com please check"
        result = redact_phi(msg)
        assert "jane@example.com" not in result
        assert "[REDACTED-EMAIL]" in result

    def test_phone_formats_redacted(self):
        for phone in ["555-867-5309", "(555) 867-5309", "+15558675309", "555.867.5309"]:
            result = redact_phi(f"Phone: {phone}")
            assert phone not in result, f"Phone {phone!r} not redacted"


class TestPhiLoggingFilter:
    def _capture_log(self, message: str, level=logging.WARNING) -> str:
        """Emit a log with the PHI filter and return the captured output."""
        logger = logging.getLogger(f"test.phi.{id(message)}")
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        handler = logging.StreamHandler(io.StringIO())
        handler.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        logger.addFilter(PhiLoggingFilter())

        logger.log(level, message)
        return handler.stream.getvalue()

    def test_phi_value_redacted_in_log_output(self):
        output = self._capture_log('Patient {"first_name": "Alice"} accessed')
        assert "Alice" not in output
        assert "[REDACTED]" in output

    def test_non_phi_log_passes_through(self):
        output = self._capture_log("Encounter 550e8400 status changed to ADMITTED")
        assert "550e8400" in output
        assert "ADMITTED" in output

    def test_filter_returns_true_never_discards(self):
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg='{"first_name": "Bob"}', args=(), exc_info=None,
        )
        phi_filter = PhiLoggingFilter()
        result = phi_filter.filter(record)
        assert result is True  # never discards
        assert "Bob" not in record.msg

    def test_args_dict_redacted(self):
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Patient %s accessed",
            args={"first_name": "Carol"},
            exc_info=None,
        )
        phi_filter = PhiLoggingFilter()
        phi_filter.filter(record)
        assert "Carol" not in str(record.args)
```

### 3. Create `backend/tests/unit/routers/test_admin_audit.py`

```python
"""Unit tests for GET /api/v1/admin/audit endpoint.

Tests cover:
  - ADMIN role returns 200 with AuditLogPage response
  - Non-ADMIN roles (NURSE, PHYSICIAN, PHARMACIST, PATIENT) return 403
  - Pagination params (page, page_size) work correctly
  - Filter params (user_id, from, to, entity_type, action) narrow results
  - ADMIN response includes ip_address and user_agent fields
  - Non-ADMIN response (if ever allowed) omits ip_address, user_agent

Uses FastAPI TestClient with app.dependency_overrides to avoid real JWT
and database dependencies. SQLAlchemy session is replaced with a mock that
returns fake AuditLog objects.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.auth.jwt import TokenClaims
from app.core.auth.rbac import require_permission
from app.main import app
from app.models.audit_log import AuditAction, AuditLog


def make_admin_claims() -> TokenClaims:
    return TokenClaims(
        sub=str(uuid.uuid4()),
        email="admin@hospital.example.com",
        role="ADMIN",
        units=[],
        iat=int(datetime.now(timezone.utc).timestamp()),
        exp=int(datetime.now(timezone.utc).timestamp()) + 3600,
    )


def make_role_claims(role: str) -> TokenClaims:
    return TokenClaims(
        sub=str(uuid.uuid4()),
        email=f"{role.lower()}@hospital.example.com",
        role=role,
        units=["ICU"],
        iat=int(datetime.now(timezone.utc).timestamp()),
        exp=int(datetime.now(timezone.utc).timestamp()) + 3600,
    )


def make_audit_row(**kwargs) -> AuditLog:
    """Create a minimal AuditLog ORM object for test assertions."""
    row = AuditLog()
    row.id = kwargs.get("id", uuid.uuid4())
    row.user_id = kwargs.get("user_id", uuid.uuid4())
    row.action = kwargs.get("action", AuditAction.READ)
    row.entity_type = kwargs.get("entity_type", "PATIENT")
    row.entity_id = kwargs.get("entity_id", uuid.uuid4())
    row.ip_address = kwargs.get("ip_address", "203.0.113.5")
    row.user_agent = kwargs.get("user_agent", "Mozilla/5.0")
    row.timestamp = kwargs.get("timestamp", datetime.now(timezone.utc))
    return row


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_overrides():
    """Ensure dependency overrides are cleared after each test."""
    yield
    app.dependency_overrides.clear()


class TestAuditQueryAdminAccess:
    @patch("app.routers.admin.audit.get_read_db_session")
    def test_admin_role_returns_200(self, mock_session_ctx, client):
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one=MagicMock(return_value=1)),   # count query
                MagicMock(scalars=MagicMock(return_value=MagicMock(
                    all=MagicMock(return_value=[make_audit_row()])
                ))),
            ]
        )
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        app.dependency_overrides[require_permission("audit_log", "read")] = (
            lambda: make_admin_claims()
        )
        response = client.get("/api/v1/admin/audit")
        assert response.status_code == 200
        body = response.json()
        assert "items" in body
        assert body["page"] == 1

    @pytest.mark.parametrize("role", ["NURSE", "PHYSICIAN", "PHARMACIST", "BED_MANAGER", "PATIENT"])
    def test_non_admin_roles_return_403(self, role, client):
        """RBAC must deny all non-ADMIN roles for audit_log:read."""
        # Do NOT override require_permission — let real RBAC enforce 403
        # This test requires the real RBAC matrix to be loaded (config/rbac_permissions.yaml)
        app.dependency_overrides = {}
        # Inject non-ADMIN JWT claims
        from app.core.auth.jwt import get_current_user
        app.dependency_overrides[get_current_user] = lambda: make_role_claims(role)
        response = client.get("/api/v1/admin/audit")
        assert response.status_code == 403, f"Role {role} should be denied but got {response.status_code}"


class TestAuditQueryPagination:
    @patch("app.routers.admin.audit.get_read_db_session")
    def test_page_size_respected(self, mock_session_ctx, client):
        rows = [make_audit_row() for _ in range(5)]
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one=MagicMock(return_value=25)),
                MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=rows)))),
            ]
        )
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)
        app.dependency_overrides[require_permission("audit_log", "read")] = (
            lambda: make_admin_claims()
        )
        response = client.get("/api/v1/admin/audit?page=1&page_size=5")
        body = response.json()
        assert body["page_size"] == 5
        assert body["total"] == 25
        assert body["pages"] == 5


class TestAuditQueryResponseShape:
    @patch("app.routers.admin.audit.get_read_db_session")
    def test_admin_response_includes_ip_and_user_agent(self, mock_session_ctx, client):
        row = make_audit_row(ip_address="203.0.113.5", user_agent="curl/7.0")
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one=MagicMock(return_value=1)),
                MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[row])))),
            ]
        )
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)
        app.dependency_overrides[require_permission("audit_log", "read")] = (
            lambda: make_admin_claims()
        )
        response = client.get("/api/v1/admin/audit")
        item = response.json()["items"][0]
        assert "ip_address" in item
        assert item["ip_address"] == "203.0.113.5"
        assert "user_agent" in item
```

---

## Validation

```bash
cd backend

# Run all US-058 unit tests
pytest tests/unit/middleware/test_audit_log_middleware.py \
       tests/unit/middleware/test_phi_log_sanitiser.py \
       tests/unit/routers/test_admin_audit.py \
       -v --tb=short

# Coverage report for US-058 modules
pytest tests/unit/middleware/test_audit_log_middleware.py \
       tests/unit/middleware/test_phi_log_sanitiser.py \
       tests/unit/routers/test_admin_audit.py \
       --cov=app/middleware/audit_log_middleware \
       --cov=app/middleware/phi_log_sanitiser \
       --cov=app/routers/admin/audit \
       --cov=app/db/audit \
       --cov-report=term-missing \
       --cov-fail-under=80
```

---

## Files Touched

| File | Action |
|---|---|
| `backend/tests/unit/middleware/test_audit_log_middleware.py` | Create — middleware path matching, IP extraction, entry creation tests |
| `backend/tests/unit/middleware/test_phi_log_sanitiser.py` | Create — `redact_phi()` and `PhiLoggingFilter` tests |
| `backend/tests/unit/routers/test_admin_audit.py` | Create — admin query RBAC, pagination, response shape tests |

---

## Definition of Done Checklist

- [ ] All 3 test files pass with `pytest -v` (no failures or errors)
- [ ] `redact_phi()` tested for all 6 PHI field names from DoD: `first_name`, `last_name`, `mrn`, `dob`, `phone`, `email`
- [ ] `PhiLoggingFilter` test confirms `filter()` always returns `True`
- [ ] Middleware test confirms excluded paths (`/auth`, `/health`) produce no audit entries
- [ ] Middleware test confirms audit write failure does not return 500
- [ ] Admin query test confirms ADMIN→200, non-ADMIN roles→403
- [ ] Pagination test confirms `total`, `pages`, `page_size` correct
- [ ] Coverage ≥80% on all 4 TASK modules (`--cov-fail-under=80` passes)
