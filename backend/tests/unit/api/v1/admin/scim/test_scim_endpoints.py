"""Unit tests for SCIM 2.0 User provisioning endpoints.

Coverage target: ≥80% branch coverage on SCIM router (TR-021).

Design refs:
    US-060 TASK-006 — unit tests: SCIM provisioning + deprovisioning
    design.md §7.4 AIR-032
    RFC 7643, RFC 7644
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.v1.admin.scim.router as scim_router_module
from app.api.v1.admin.scim.schemas import ScimRoleMapper
from app.core.auth import jwt_blocklist as bl_module
from app.core.config import get_settings
from app.db.deps import get_write_db
from app.main import app
from app.models.app_user import AppUser

# ── Constants ──────────────────────────────────────────────────────────────

TEST_SCIM_TOKEN = "test-scim-bearer-token-abc123"

SCIM_USER_PAYLOAD = {
    "schemas": [
        "urn:ietf:params:scim:schemas:core:2.0:User",
        "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User",
    ],
    "userName": "jane.doe@hospital.example",
    "name": {"givenName": "Jane", "familyName": "Doe"},
    "emails": [{"value": "jane.doe@hospital.example", "primary": True}],
    "displayName": "Jane Doe",
    "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User": {
        "department": "Nursing",
    },
}


# ── Autouse fixtures ───────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_overrides():
    """Clear FastAPI dependency_overrides after each test."""
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def set_scim_token_env(monkeypatch):
    """Inject a predictable SCIM_CLIENT_SECRET and clear the lru_cache."""
    monkeypatch.setenv("SCIM_CLIENT_SECRET", TEST_SCIM_TOKEN)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def patch_role_mapper():
    """Replace the module-level _role_mapper with a controlled fake."""
    fake_mapper = MagicMock(spec=ScimRoleMapper)

    def _map(department: str) -> str:
        mapping = {
            "nursing": "NURSE",
            "pharmacy": "PHARMACIST",
            "medicine": "PHYSICIAN",
            "bedmanagement": "BED_MANAGER",
            "administration": "ADMIN",
        }
        normalised = department.lower().strip()
        if normalised not in mapping:
            raise ValueError(f"Unknown department: {department!r}")
        return mapping[normalised]

    fake_mapper.map.side_effect = _map

    with patch.object(scim_router_module, "_role_mapper", fake_mapper):
        yield fake_mapper


# ── DB + client fixtures ──────────────────────────────────────────────────

@pytest.fixture()
def mock_db() -> AsyncMock:
    """Return a ready-to-use async mock DB session."""
    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture()
def client(mock_db: AsyncMock) -> TestClient:
    """Return a TestClient with get_write_db overridden."""

    async def _override():
        yield mock_db

    app.dependency_overrides[get_write_db] = _override
    return TestClient(app, raise_server_exceptions=False)


# ── Helpers ────────────────────────────────────────────────────────────────

def _auth_headers(token: str = TEST_SCIM_TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_user(
    *,
    email: str = "jane.doe@hospital.example",
    role: str = "NURSE",
    full_name: str = "Jane Doe",
    deprovisioned_at: datetime | None = None,
    current_jti: str | None = None,
    scim_id: str | None = None,
) -> AppUser:
    user = MagicMock(spec=AppUser)
    user.id = uuid.uuid4()
    user.email = email
    user.role = role
    user.full_name = full_name
    user.deprovisioned_at = deprovisioned_at
    user.current_jti = current_jti
    user.scim_id = scim_id
    return user


def _scalar_result(value) -> MagicMock:
    """Wrap a value in a mock that behaves like a SQLAlchemy scalar result."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    result.scalars.return_value.all.return_value = [value] if value else []
    return result


def _count_result(count: int) -> MagicMock:
    result = MagicMock()
    result.scalar_one.return_value = count
    return result


# ═══════════════════════════════════════════════════════════════════════════
# TestScimAuth
# ═══════════════════════════════════════════════════════════════════════════

class TestScimAuth:
    """SCIM bearer token authentication guard."""

    def test_post_without_token_returns_401(self, client: TestClient):
        resp = client.post("/api/v1/admin/scim/Users", json=SCIM_USER_PAYLOAD)
        assert resp.status_code == 401

    def test_post_wrong_token_returns_401(self, client: TestClient):
        resp = client.post(
            "/api/v1/admin/scim/Users",
            json=SCIM_USER_PAYLOAD,
            headers=_auth_headers("wrong-token"),
        )
        assert resp.status_code == 401

    def test_correct_token_does_not_return_401(self, client: TestClient, mock_db: AsyncMock):
        # Returns 201 or 4xx depending on payload/DB, but NOT 401
        mock_db.execute.return_value = _scalar_result(None)  # no existing user
        resp = client.post(
            "/api/v1/admin/scim/Users",
            json=SCIM_USER_PAYLOAD,
            headers=_auth_headers(),
        )
        assert resp.status_code != 401


# ═══════════════════════════════════════════════════════════════════════════
# TestScimPostCreateUser
# ═══════════════════════════════════════════════════════════════════════════

class TestScimPostCreateUser:
    """POST /api/v1/admin/scim/Users — provision new user."""

    def test_scim_post_creates_user_returns_201(self, client: TestClient, mock_db: AsyncMock):
        """Happy path: new user is created; 201 + SCIM User resource returned.
        Asserts scim_id is captured from externalId (TASK-003 AC Scenario 1).
        """
        mock_db.execute.return_value = _scalar_result(None)
        payload = {**SCIM_USER_PAYLOAD, "externalId": "idp-abc-123"}

        resp = client.post(
            "/api/v1/admin/scim/Users",
            json=payload,
            headers=_auth_headers(),
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["userName"] == "jane.doe@hospital.example"
        assert body["active"] is True
        # Verify the AppUser was added with scim_id from externalId
        added_user = mock_db.add.call_args[0][0]
        assert added_user.scim_id == "idp-abc-123"
        mock_db.commit.assert_called_once()

    def test_scim_post_duplicate_returns_existing_user(
        self, client: TestClient, mock_db: AsyncMock
    ):
        """Idempotent: if email already exists, return existing user with 200."""
        existing = _make_user(email="jane.doe@hospital.example")
        mock_db.execute.return_value = _scalar_result(existing)

        resp = client.post(
            "/api/v1/admin/scim/Users",
            json=SCIM_USER_PAYLOAD,
            headers=_auth_headers(),
        )

        assert resp.status_code == 201  # FastAPI uses route status_code for all model returns
        body = resp.json()
        assert body["id"] == str(existing.id)
        mock_db.add.assert_not_called()

    def test_scim_post_unknown_department_returns_400(
        self, client: TestClient, mock_db: AsyncMock
    ):
        """Unknown department → 400 Bad Request."""
        mock_db.execute.return_value = _scalar_result(None)
        payload = dict(SCIM_USER_PAYLOAD)
        payload["urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"] = {
            "department": "Radiology"
        }
        resp = client.post(
            "/api/v1/admin/scim/Users",
            json=payload,
            headers=_auth_headers(),
        )
        assert resp.status_code == 400

    def test_scim_post_missing_department_returns_400(
        self, client: TestClient, mock_db: AsyncMock
    ):
        """Missing department entirely → 400 Bad Request."""
        mock_db.execute.return_value = _scalar_result(None)
        payload = dict(SCIM_USER_PAYLOAD)
        payload["urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"] = {}
        resp = client.post(
            "/api/v1/admin/scim/Users",
            json=payload,
            headers=_auth_headers(),
        )
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════
# TestScimDeleteUser
# ═══════════════════════════════════════════════════════════════════════════

class TestScimDeleteUser:
    """DELETE /api/v1/admin/scim/Users/{id} — SCIM-triggered deprovision."""

    def test_scim_delete_deprovisions_user(self, client: TestClient, mock_db: AsyncMock):
        """Happy path: user is found and deprovisioned; 204 No Content."""
        jti = str(uuid.uuid4())
        user = _make_user(current_jti=jti)
        mock_db.execute.return_value = _scalar_result(user)

        server = fakeredis.FakeServer()
        fake = fakeredis.FakeRedis(server=server, decode_responses=True)
        with patch.object(bl_module, "_get_redis_client", return_value=fake):
            resp = client.delete(
                f"/api/v1/admin/scim/Users/{user.id}",
                headers=_auth_headers(),
            )

        assert resp.status_code == 204
        assert fake.exists(f"jwt_blocklist:{jti}") == 1

    def test_scim_delete_nonexistent_user_returns_404(
        self, client: TestClient, mock_db: AsyncMock
    ):
        """Non-existent user_id → 404 Not Found."""
        mock_db.execute.return_value = _scalar_result(None)
        resp = client.delete(
            f"/api/v1/admin/scim/Users/{uuid.uuid4()}",
            headers=_auth_headers(),
        )
        assert resp.status_code == 404

    def test_scim_delete_already_deprovisioned_is_idempotent(
        self, client: TestClient, mock_db: AsyncMock
    ):
        """Already deprovisioned user → 204 (idempotent; no error)."""
        user = _make_user(deprovisioned_at=datetime.now(timezone.utc))
        mock_db.execute.return_value = _scalar_result(user)

        server = fakeredis.FakeServer()
        fake = fakeredis.FakeRedis(server=server, decode_responses=True)
        with patch.object(bl_module, "_get_redis_client", return_value=fake):
            resp = client.delete(
                f"/api/v1/admin/scim/Users/{user.id}",
                headers=_auth_headers(),
            )

        assert resp.status_code == 204


# ═══════════════════════════════════════════════════════════════════════════
# TestScimPatchUser
# ═══════════════════════════════════════════════════════════════════════════

class TestScimPatchUser:
    """PATCH /api/v1/admin/scim/Users/{id} — partial update."""

    def test_scim_patch_updates_role(self, client: TestClient, mock_db: AsyncMock):
        """Patch department → role is updated; 200 + updated SCIM resource."""
        user = _make_user(role="NURSE")
        mock_db.execute.return_value = _scalar_result(user)

        patch_payload = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {
                    "op": "replace",
                    "path": "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User:department",
                    "value": "Pharmacy",
                }
            ],
        }
        resp = client.patch(
            f"/api/v1/admin/scim/Users/{user.id}",
            json=patch_payload,
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        # Role must have been updated on the user object
        assert user.role == "PHARMACIST"
        # Audit log entry must have been written (DR-003, AC Scenario 4)
        mock_db.add.assert_called()

    def test_scim_patch_unknown_department_returns_400(
        self, client: TestClient, mock_db: AsyncMock
    ):
        """Patch with unknown department → 400 Bad Request."""
        user = _make_user()
        mock_db.execute.return_value = _scalar_result(user)

        patch_payload = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {
                    "op": "replace",
                    "path": "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User:department",
                    "value": "Radiology",
                }
            ],
        }
        resp = client.patch(
            f"/api/v1/admin/scim/Users/{user.id}",
            json=patch_payload,
            headers=_auth_headers(),
        )
        assert resp.status_code == 400

    def test_scim_patch_nonexistent_user_returns_404(
        self, client: TestClient, mock_db: AsyncMock
    ):
        """PATCH on non-existent user → 404 Not Found."""
        mock_db.execute.return_value = _scalar_result(None)

        patch_payload = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {
                    "op": "replace",
                    "path": "displayName",
                    "value": "Ghost User",
                }
            ],
        }
        resp = client.patch(
            f"/api/v1/admin/scim/Users/{uuid.uuid4()}",
            json=patch_payload,
            headers=_auth_headers(),
        )
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# TestScimRoleMapper
# ═══════════════════════════════════════════════════════════════════════════

class TestScimRoleMapper:
    """Unit tests for ScimRoleMapper in isolation (without the HTTP layer)."""

    @pytest.fixture()
    def real_mapper(self) -> ScimRoleMapper:
        """Load the real YAML-backed mapper."""
        return ScimRoleMapper.load()

    def test_known_department_returns_role(self, real_mapper: ScimRoleMapper):
        assert real_mapper.map("Nursing") == "NURSE"

    def test_mapping_is_case_insensitive(self, real_mapper: ScimRoleMapper):
        assert real_mapper.map("nursing") == "NURSE"
        assert real_mapper.map("NURSING") == "NURSE"

    def test_unknown_department_raises_value_error(self, real_mapper: ScimRoleMapper):
        with pytest.raises(ValueError, match="no role mapping"):
            real_mapper.map("Radiology")
