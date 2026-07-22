"""Unit tests for DELETE /api/v1/admin/users/{user_id}.

Uses AsyncMock DB session + fakeredis to avoid real infrastructure.

Coverage target: ≥80% branch coverage on admin users deprovision handler (TR-020).

Design refs:
    US-059 TASK-006 — unit tests: deprovisioning flow
"""
from __future__ import annotations

import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis
import pytest
from fastapi.testclient import TestClient

from app.core.auth import jwt_blocklist as bl_module
from app.core.auth.jwt import TokenClaims, get_current_user
from app.core.auth.rbac import load_rbac_matrix
from app.db.deps import get_write_db
from app.main import app


@pytest.fixture(autouse=True)
def _reset_overrides():
    """Clear dependency_overrides after each test to prevent bleed."""
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _clear_rbac_cache():
    """Clear lru_cache on load_rbac_matrix before and after each test."""
    load_rbac_matrix.cache_clear()
    yield
    load_rbac_matrix.cache_clear()


@pytest.fixture(autouse=True)
def fake_redis():
    """Patch _get_redis_client to return a fakeredis instance per test."""
    server = fakeredis.FakeServer()
    fake = fakeredis.FakeRedis(server=server, decode_responses=True)
    with patch.object(bl_module, "_get_redis_client", return_value=fake):
        yield fake


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _admin_claims() -> TokenClaims:
    return TokenClaims(
        sub=str(uuid.uuid4()),
        role="ADMIN",   # uppercase — must match rbac_permissions.yaml key
        units=[],
        email="admin@hospital.example.com",
        jti=str(uuid.uuid4()),
        exp=int(time.time()) + 28800,
    )


def _mock_target_user(
    deprovisioned: bool = False,
    has_jti: bool = True,
) -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.deprovisioned_at = "2026-01-01T00:00:00Z" if deprovisioned else None
    user.current_jti = str(uuid.uuid4()) if has_jti else None
    return user


def _make_mock_db(target_user) -> AsyncMock:
    """Build an AsyncMock DB session that returns target_user on scalar_one_or_none."""
    mock_db = AsyncMock()
    mock_db.execute.return_value.scalar_one_or_none.return_value = target_user
    return mock_db


def _setup_overrides(target_user) -> AsyncMock:
    """Set up dependency overrides for admin + DB.

    Overrides get_current_user only — require_permission's inner _dependency
    consumes get_current_user, so this is the correct interception point.
    Overriding require_permission(...) directly does NOT work because each
    call creates a new function object that won't match the route's registered key.
    """
    admin = _admin_claims()
    app.dependency_overrides[get_current_user] = lambda: admin

    mock_db = _make_mock_db(target_user)

    async def _fake_db():
        yield mock_db

    app.dependency_overrides[get_write_db] = _fake_db
    return mock_db


class TestDeprovisionEndpoint:
    @patch("app.core.auth.rbac.write_rbac_audit_entry", new_callable=AsyncMock)
    def test_deprovision_returns_200(self, mock_audit, client, fake_redis):
        """Deprovisioning an active user returns 200 OK."""
        target = _mock_target_user()
        _setup_overrides(target)

        response = client.delete(f"/api/v1/admin/users/{target.id}")
        assert response.status_code == 200
        body = response.json()
        assert body["message"] == "User deprovisioned successfully"
        assert body["user_id"] == str(target.id)

    @patch("app.core.auth.rbac.write_rbac_audit_entry", new_callable=AsyncMock)
    def test_deprovision_blocklists_jti(self, mock_audit, client, fake_redis):
        """Deprovisioning adds the user's current_jti to the Redis blocklist."""
        target = _mock_target_user(has_jti=True)
        _setup_overrides(target)

        client.delete(f"/api/v1/admin/users/{target.id}")

        assert fake_redis.exists(f"jwt_blocklist:{target.current_jti}") == 1

    @patch("app.core.auth.rbac.write_rbac_audit_entry", new_callable=AsyncMock)
    def test_deprovision_user_without_jti_returns_200(self, mock_audit, client, fake_redis):
        """Users without a current_jti (never logged in) can still be deprovisioned."""
        target = _mock_target_user(has_jti=False)
        _setup_overrides(target)

        response = client.delete(f"/api/v1/admin/users/{target.id}")
        assert response.status_code == 200

    @patch("app.core.auth.rbac.write_rbac_audit_entry", new_callable=AsyncMock)
    def test_deprovision_already_deprovisioned_returns_409(self, mock_audit, client, fake_redis):
        """Attempting to deprovision an already-deprovisioned user returns 409 Conflict."""
        target = _mock_target_user(deprovisioned=True)
        _setup_overrides(target)

        response = client.delete(f"/api/v1/admin/users/{target.id}")
        assert response.status_code == 409
        assert "already deprovisioned" in response.json()["detail"]

    @patch("app.core.auth.rbac.write_rbac_audit_entry", new_callable=AsyncMock)
    def test_deprovision_user_not_found_returns_404(self, mock_audit, client, fake_redis):
        """Non-existent user_id returns 404 Not Found."""
        _setup_overrides(None)  # DB returns None

        response = client.delete(f"/api/v1/admin/users/{uuid.uuid4()}")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @patch("app.core.auth.rbac.write_rbac_audit_entry", new_callable=AsyncMock)
    def test_deprovision_sets_deprovisioned_at(self, mock_audit, client, fake_redis):
        """deprovisioned_at is set on the target user after deprovisioning."""
        target = _mock_target_user()
        _setup_overrides(target)

        client.delete(f"/api/v1/admin/users/{target.id}")

        assert target.deprovisioned_at is not None

    @patch("app.core.auth.rbac.write_rbac_audit_entry", new_callable=AsyncMock)
    def test_deprovision_commits_db(self, mock_audit, client, fake_redis):
        """DB commit is called after setting deprovisioned_at."""
        target = _mock_target_user()
        mock_db = _setup_overrides(target)

        client.delete(f"/api/v1/admin/users/{target.id}")

        mock_db.commit.assert_awaited_once()

    @patch("app.core.auth.rbac.write_rbac_audit_entry", new_callable=AsyncMock)
    def test_deprovision_rbac_audit_called_for_grant(self, mock_audit, client, fake_redis):
        """write_rbac_audit_entry is called with granted=True for ADMIN access."""
        target = _mock_target_user()
        _setup_overrides(target)

        client.delete(f"/api/v1/admin/users/{target.id}")

        mock_audit.assert_awaited()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs.get("granted") is True
