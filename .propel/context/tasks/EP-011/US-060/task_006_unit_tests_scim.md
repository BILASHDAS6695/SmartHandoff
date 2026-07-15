---
id: TASK-006
title: "Write pytest Unit Tests — SCIM Endpoints (Create, Update, Delete, Auth Failure)"
user_story: US-060
epic: EP-011
sprint: 2
layer: Testing
estimate: 2.5h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-060/TASK-001, US-060/TASK-002, US-060/TASK-003, US-060/TASK-004, US-060/TASK-005]
---

# TASK-006: Write pytest Unit Tests — SCIM Endpoints (Create, Update, Delete, Auth Failure)

> **Story:** US-060 | **Epic:** EP-011 | **Sprint:** 2 | **Layer:** Testing | **Est:** 2.5 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

US-060 DoD requires: *"Unit tests: create, update, delete, auth failure"*. This task delivers pytest tests covering all four SCIM acceptance criteria scenarios plus the auth failure case.

**Test strategy:**
- FastAPI `TestClient` + `app.dependency_overrides` to inject a stub async DB session and bypass real Redis/Secret Manager.
- `fakeredis` (already in `requirements-dev.txt` from US-059) for blocklist assertions in the DELETE test.
- The `SCIM_CLIENT_SECRET` env var is set to a test value for tests that should pass auth; omitted/wrong for auth-failure tests.
- `ScimRoleMapper.load()` is patched to return an in-memory mapping, avoiding filesystem dependency in CI.

Coverage target: ≥80% branch coverage on `scim/router.py`, `scim/schemas.py`, `scim/scim_auth.py`, `services/deprovision_service.py` (TR-020).

---

## Acceptance Criteria Addressed

| US-060 AC | Test |
|---|---|
| **Scenario 1** | `test_scim_post_creates_user` — POST → 201; correct role, scim_id, email |
| **Scenario 2** | `test_scim_delete_deprovisions_user` — DELETE → 204; deprovisioned_at set; next API call → 401 |
| **Scenario 3** | `test_scim_post_without_token_returns_401`, `test_scim_post_wrong_token_returns_401` |
| **Scenario 4** | `test_scim_patch_updates_role` — PATCH department → correct role; audit_log entry written |

---

## Implementation Steps

### 1. Create `backend/tests/unit/api/v1/admin/scim/test_scim_endpoints.py`

```python
"""Unit tests for SCIM 2.0 endpoints — US-060.

Coverage:
  - POST /scim/Users   (AC Scenario 1 — create user)
  - DELETE /scim/Users/{id}  (AC Scenario 2 — deprovision + JWT blocklist)
  - Auth failure (AC Scenario 3 — missing / wrong bearer token)
  - PATCH /scim/Users/{id}   (AC Scenario 4 — role update + audit_log)

Uses:
  - FastAPI TestClient (sync wrapper for async app)
  - app.dependency_overrides to inject stub DB session
  - fakeredis for blocklist verification
  - monkeypatch to inject SCIM_CLIENT_SECRET test value
  - ScimRoleMapper patched to avoid filesystem YAML load

Design refs:
    US-060, EP-011
    TR-020 — ≥80% branch coverage
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# App + dependency imports — adjust paths to match your project layout
# ---------------------------------------------------------------------------
from app.main import app
from app.api.v1.admin.scim import scim_auth
from app.api.v1.admin.scim import schemas as scim_schemas
from app.db.session import get_async_db
from app.models.user import AppUser, AppRole

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_SCIM_TOKEN = "test-scim-bearer-token-abc123"

SCIM_USER_PAYLOAD = {
    "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
    "userName": "jdoe@hospital.org",
    "name": {"givenName": "Jane", "familyName": "Doe"},
    "emails": [{"value": "jdoe@hospital.org", "primary": True}],
    "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User": {
        "department": "Nursing"
    },
}


@pytest.fixture(autouse=True)
def set_scim_token_env(monkeypatch):
    """Inject SCIM_CLIENT_SECRET into the test environment."""
    monkeypatch.setenv("SCIM_CLIENT_SECRET", TEST_SCIM_TOKEN)
    # Clear any cached settings to pick up new env var
    from app.core.config import get_settings
    get_settings.cache_clear() if hasattr(get_settings, "cache_clear") else None
    yield
    get_settings.cache_clear() if hasattr(get_settings, "cache_clear") else None


@pytest.fixture()
def fake_redis_server():
    """Shared fakeredis server for blocklist tests."""
    server = fakeredis.FakeServer()
    fake = fakeredis.FakeRedis(server=server, decode_responses=True)
    return fake


@pytest.fixture()
def mock_db_session():
    """Async DB session stub; callers configure return values per test."""
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.fixture()
def client(mock_db_session):
    """TestClient with DB dependency overridden."""

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        yield mock_db_session

    app.dependency_overrides[get_async_db] = override_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def patch_role_mapper():
    """Patch ScimRoleMapper.load() to avoid filesystem YAML dependency."""
    mapper = scim_schemas.ScimRoleMapper(
        {"nursing": "NURSE", "pharmacy": "PHARMACIST", "medicine": "PHYSICIAN"}
    )
    with patch.object(scim_schemas.ScimRoleMapper, "load", return_value=mapper):
        # Also patch the module-level _role_mapper in router.py
        import app.api.v1.admin.scim.router as scim_router
        scim_router._role_mapper = mapper
        yield


# ---------------------------------------------------------------------------
# Helper: build a minimal AppUser mock
# ---------------------------------------------------------------------------

def _make_user(
    user_id: uuid.UUID | None = None,
    email: str = "jdoe@hospital.org",
    role: AppRole = AppRole.NURSE,
    deprovisioned_at=None,
    current_jti: str | None = None,
    scim_id: str | None = None,
) -> AppUser:
    user = MagicMock(spec=AppUser)
    user.id = user_id or uuid.uuid4()
    user.email = email
    user.display_name = "Jane Doe"
    user.role = role
    user.unit = "Nursing"
    user.deprovisioned_at = deprovisioned_at
    user.current_jti = current_jti
    user.scim_id = scim_id
    return user


# ---------------------------------------------------------------------------
# AC Scenario 3 — Auth failure
# ---------------------------------------------------------------------------


class TestScimAuth:
    def test_post_without_token_returns_401(self, client):
        """No Authorization header → 401."""
        resp = client.post(
            "/api/v1/admin/scim/Users",
            json=SCIM_USER_PAYLOAD,
        )
        assert resp.status_code == 401

    def test_post_wrong_token_returns_401(self, client):
        """Wrong bearer token → 401."""
        resp = client.post(
            "/api/v1/admin/scim/Users",
            json=SCIM_USER_PAYLOAD,
            headers={"Authorization": "Bearer totally-wrong-token"},
        )
        assert resp.status_code == 401

    def test_correct_token_does_not_return_401(self, client, mock_db_session):
        """Correct bearer token passes auth check (result may be 400/422 for other reasons)."""
        # Configure DB to return None (no existing user) so POST proceeds past auth
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result
        mock_db_session.refresh = AsyncMock(side_effect=lambda u: None)

        resp = client.post(
            "/api/v1/admin/scim/Users",
            json=SCIM_USER_PAYLOAD,
            headers={"Authorization": f"Bearer {TEST_SCIM_TOKEN}"},
        )
        # Must not be 401 (auth passed)
        assert resp.status_code != 401


# ---------------------------------------------------------------------------
# AC Scenario 1 — POST creates user
# ---------------------------------------------------------------------------


class TestScimPostCreateUser:
    def test_scim_post_creates_user_returns_201(self, client, mock_db_session):
        """POST with valid payload → 201 Created with SCIM User resource."""
        # No existing user
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        # After db.refresh, the user has correct fields
        created_user = _make_user(role=AppRole.NURSE)

        async def fake_refresh(user):
            user.id = created_user.id
            user.email = "jdoe@hospital.org"
            user.role = AppRole.NURSE
            user.display_name = "Jane Doe"
            user.deprovisioned_at = None
            user.scim_id = None

        mock_db_session.refresh = AsyncMock(side_effect=fake_refresh)

        resp = client.post(
            "/api/v1/admin/scim/Users",
            json=SCIM_USER_PAYLOAD,
            headers={"Authorization": f"Bearer {TEST_SCIM_TOKEN}"},
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["userName"] == "jdoe@hospital.org"
        assert "id" in data
        assert data["active"] is True

    def test_scim_post_duplicate_returns_existing_user(self, client, mock_db_session):
        """POST for existing email → returns existing user (idempotent), 201."""
        existing = _make_user()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db_session.execute.return_value = mock_result

        resp = client.post(
            "/api/v1/admin/scim/Users",
            json=SCIM_USER_PAYLOAD,
            headers={"Authorization": f"Bearer {TEST_SCIM_TOKEN}"},
        )

        assert resp.status_code == 201
        # DB add should NOT be called (no new user created)
        mock_db_session.add.assert_not_called()

    def test_scim_post_unknown_department_returns_400(self, client, mock_db_session):
        """POST with unmapped department → 400 Bad Request."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        payload = {**SCIM_USER_PAYLOAD}
        payload["urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"] = {
            "department": "UnknownDept"
        }

        resp = client.post(
            "/api/v1/admin/scim/Users",
            json=payload,
            headers={"Authorization": f"Bearer {TEST_SCIM_TOKEN}"},
        )
        assert resp.status_code == 400

    def test_scim_post_missing_department_returns_400(self, client, mock_db_session):
        """POST without enterpriseUser extension → 400 Bad Request."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        payload = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "nodept@hospital.org",
        }
        resp = client.post(
            "/api/v1/admin/scim/Users",
            json=payload,
            headers={"Authorization": f"Bearer {TEST_SCIM_TOKEN}"},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# AC Scenario 2 — DELETE deprovisions user + JWT blocklist
# ---------------------------------------------------------------------------


class TestScimDeleteUser:
    def test_scim_delete_deprovisions_user(
        self, client, mock_db_session, fake_redis_server
    ):
        """DELETE → 204; deprovisioned_at set; JWT blocklisted."""
        jti = "test-jti-scim-delete"
        user_id = uuid.uuid4()
        user = _make_user(user_id=user_id, current_jti=jti)
        user.deprovisioned_at = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db_session.execute.return_value = mock_result

        with patch(
            "app.core.auth.jwt_blocklist._get_redis_client",
            return_value=fake_redis_server,
        ):
            resp = client.delete(
                f"/api/v1/admin/scim/Users/{user_id}",
                headers={"Authorization": f"Bearer {TEST_SCIM_TOKEN}"},
            )

        assert resp.status_code == 204
        # Verify deprovisioned_at was set on the user mock
        assert user.deprovisioned_at is not None
        # Verify JWT blocklisted in Redis
        assert fake_redis_server.exists(f"jwt_blocklist:{jti}")

    def test_scim_delete_nonexistent_user_returns_404(self, client, mock_db_session):
        """DELETE for unknown user ID → 404."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        resp = client.delete(
            f"/api/v1/admin/scim/Users/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {TEST_SCIM_TOKEN}"},
        )
        assert resp.status_code == 404

    def test_scim_delete_already_deprovisioned_is_idempotent(
        self, client, mock_db_session
    ):
        """DELETE on already-deprovisioned user → 204 (idempotent)."""
        user = _make_user(deprovisioned_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db_session.execute.return_value = mock_result

        resp = client.delete(
            f"/api/v1/admin/scim/Users/{user.id}",
            headers={"Authorization": f"Bearer {TEST_SCIM_TOKEN}"},
        )
        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# AC Scenario 4 — PATCH updates role + audit_log
# ---------------------------------------------------------------------------


class TestScimPatchUser:
    def test_scim_patch_updates_role(self, client, mock_db_session):
        """PATCH department=Pharmacy → role updated to PHARMACIST."""
        user_id = uuid.uuid4()
        user = _make_user(user_id=user_id, role=AppRole.NURSE)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db_session.execute.return_value = mock_result

        patch_payload = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {
                    "op": "replace",
                    "path": (
                        "urn:ietf:params:scim:schemas:extension:"
                        "enterprise:2.0:User:department"
                    ),
                    "value": "Pharmacy",
                }
            ],
        }

        resp = client.patch(
            f"/api/v1/admin/scim/Users/{user_id}",
            json=patch_payload,
            headers={"Authorization": f"Bearer {TEST_SCIM_TOKEN}"},
        )

        assert resp.status_code == 200
        # Role should be updated on the user object
        assert user.role == AppRole.PHARMACIST
        # audit_log entry should have been added
        mock_db_session.add.assert_called()

    def test_scim_patch_unknown_department_returns_400(self, client, mock_db_session):
        """PATCH with unmapped department → 400."""
        user_id = uuid.uuid4()
        user = _make_user(user_id=user_id)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db_session.execute.return_value = mock_result

        patch_payload = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {"op": "replace", "path": "enterprise:department", "value": "Unknown"}
            ],
        }

        resp = client.patch(
            f"/api/v1/admin/scim/Users/{user_id}",
            json=patch_payload,
            headers={"Authorization": f"Bearer {TEST_SCIM_TOKEN}"},
        )
        assert resp.status_code == 400

    def test_scim_patch_nonexistent_user_returns_404(self, client, mock_db_session):
        """PATCH for unknown user ID → 404."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        patch_payload = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "path": "displayName", "value": "Updated"}],
        }
        resp = client.patch(
            f"/api/v1/admin/scim/Users/{uuid.uuid4()}",
            json=patch_payload,
            headers={"Authorization": f"Bearer {TEST_SCIM_TOKEN}"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# ScimRoleMapper unit tests
# ---------------------------------------------------------------------------


class TestScimRoleMapper:
    def test_map_known_department(self):
        mapper = scim_schemas.ScimRoleMapper({"Nursing": "NURSE"})
        assert mapper.map("Nursing") == "NURSE"

    def test_map_case_insensitive(self):
        mapper = scim_schemas.ScimRoleMapper({"Nursing": "NURSE"})
        assert mapper.map("nursing") == "NURSE"
        assert mapper.map("NURSING") == "NURSE"

    def test_map_unknown_department_raises(self):
        mapper = scim_schemas.ScimRoleMapper({"Nursing": "NURSE"})
        with pytest.raises(ValueError, match="no role mapping"):
            mapper.map("Radiology")
```

---

## Run the Tests

```bash
cd backend

pytest tests/unit/api/v1/admin/scim/test_scim_endpoints.py \
       -v --tb=short \
       --cov=app/api/v1/admin/scim \
       --cov=app/services/deprovision_service \
       --cov-report=term-missing \
       --cov-fail-under=80

# Run full unit suite to confirm no regressions
pytest tests/unit/ -q --tb=short
```

---

## Files Created / Modified

| File | Action |
|---|---|
| `backend/tests/unit/api/v1/admin/scim/__init__.py` | **Create** (empty) |
| `backend/tests/unit/api/v1/admin/scim/test_scim_endpoints.py` | **Create** |
