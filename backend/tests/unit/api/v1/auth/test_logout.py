"""Unit tests for POST /api/v1/auth/logout.

Uses FastAPI TestClient with dependency_overrides to inject a pre-validated
TokenClaims without requiring a real JWT. fakeredis stubs Redis.

Coverage target: ≥80% branch coverage on auth logout handler (TR-020).

Design refs:
    US-059 TASK-006 — unit tests: logout blocklists token
"""
from __future__ import annotations

import time
import uuid
from unittest.mock import patch

import fakeredis
import pytest
from fastapi.testclient import TestClient

from app.core.auth import jwt_blocklist as bl_module
from app.core.auth.jwt import TokenClaims, get_current_user
from app.main import app


@pytest.fixture(autouse=True)
def _reset_overrides():
    """Clear dependency_overrides after each test."""
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def fake_redis():
    """Return a fakeredis instance and patch _get_redis_client."""
    server = fakeredis.FakeServer()
    fake = fakeredis.FakeRedis(server=server, decode_responses=True)
    with patch.object(bl_module, "_get_redis_client", return_value=fake):
        yield fake


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _make_claims(jti: str | None = None, include_jti: bool = True) -> TokenClaims:
    data = {
        "sub": str(uuid.uuid4()),
        "role": "nurse",
        "units": [],
        "email": "nurse@hospital.example.com",
        "iat": int(time.time()),
        "exp": int(time.time()) + 28800,
    }
    if include_jti:
        data["jti"] = jti or str(uuid.uuid4())
    return TokenClaims(**data)


class TestLogoutEndpoint:
    def test_logout_returns_200(self, client, fake_redis):
        """Successful logout returns 200 OK."""
        claims = _make_claims()
        app.dependency_overrides[get_current_user] = lambda: claims

        response = client.post("/api/v1/auth/logout")
        assert response.status_code == 200
        assert response.json()["message"] == "Logged out successfully"

    def test_logout_blocklists_jti(self, client, fake_redis):
        """After logout the jti is present in the Redis blocklist."""
        jti = str(uuid.uuid4())
        claims = _make_claims(jti=jti)
        app.dependency_overrides[get_current_user] = lambda: claims

        client.post("/api/v1/auth/logout")

        assert fake_redis.exists(f"jwt_blocklist:{jti}") == 1

    def test_logout_without_jti_returns_200(self, client, fake_redis):
        """Tokens without jti (legacy tokens) still get 200 on logout."""
        claims = _make_claims(include_jti=False)
        app.dependency_overrides[get_current_user] = lambda: claims

        response = client.post("/api/v1/auth/logout")
        assert response.status_code == 200
        assert response.json()["message"] == "Logged out successfully"

    def test_second_call_with_same_token_would_be_blocked(self, client, fake_redis):
        """After logout the jti is in Redis; a real second call would get 401.
        Here we verify the blocklist entry is set (integration with get_current_user
        is tested separately in test_jwt_blocklist.py)."""
        jti = str(uuid.uuid4())
        claims = _make_claims(jti=jti)
        app.dependency_overrides[get_current_user] = lambda: claims

        # First logout
        r1 = client.post("/api/v1/auth/logout")
        assert r1.status_code == 200

        # Blocklist entry is set
        assert fake_redis.exists(f"jwt_blocklist:{jti}") == 1

    def test_logout_without_auth_returns_403_or_401(self, client):
        """Calling /logout without a Bearer token fails authentication."""
        response = client.post("/api/v1/auth/logout")
        # 403 (HTTPBearer auto_error=True) or 401
        assert response.status_code in (401, 403)
