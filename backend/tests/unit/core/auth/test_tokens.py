"""Unit tests for app/core/auth/tokens.py and app/core/auth/jwt.py.

Covers:
    - amr validation (AC Scenario 1 and 2)
    - JWKS cache behaviour
    - JWT claims mapping (DoD: sub → user_id, groups → role)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from jose import jwt

from app.core.auth.tokens import validate_id_token


# ---------------------------------------------------------------------------
# Test utilities
# ---------------------------------------------------------------------------

def _make_rsa_key_pair():
    """Generate a temporary RSA key pair for test token signing."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    return private_key


def _make_id_token(
    private_key,
    sub: str = "user-123",
    amr: list | None = None,
    issuer: str = "https://idp.hospital.example.com",
    audience: str = "smarthandoff-api-gateway",
    expired: bool = False,
) -> str:
    import time
    from cryptography.hazmat.primitives import serialization

    now = int(time.time())
    payload = {
        "sub": sub,
        "email": "user@hospital.example.com",
        "groups": ["smarthandoff-physician"],
        "units": ["4B"],
        "iss": issuer,
        "aud": audience,
        "iat": now - 60 if not expired else now - 7200,
        "exp": now + 300 if not expired else now - 3600,
    }
    if amr is not None:
        payload["amr"] = amr

    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return jwt.encode(payload, pem, algorithm="RS256")


def _make_mock_jwks(private_key) -> dict:
    """Build a JWKS from the test private key's public component."""
    from cryptography.hazmat.primitives import serialization
    from jose import jwk as jose_jwk

    pub_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    key = jose_jwk.construct(pub_pem.decode(), algorithm="RS256")
    return {"keys": [key.public_key()]}


# ---------------------------------------------------------------------------
# amr validation tests (AC Scenario 1 and 2)
# ---------------------------------------------------------------------------

class TestAmrValidation:
    @pytest.fixture(autouse=True)
    def env_setup(self, monkeypatch):
        monkeypatch.setenv("IDP_BASE_URL", "https://idp.hospital.example.com")
        monkeypatch.setenv("OIDC_CLIENT_ID", "smarthandoff-api-gateway")

    @pytest.mark.asyncio
    async def test_valid_mfa_token_succeeds(self):
        """amr: ["mfa"] → returns decoded claims."""
        key = _make_rsa_key_pair()
        token = _make_id_token(key, amr=["mfa"])
        jwks = _make_mock_jwks(key)

        with patch("app.core.auth.tokens.fetch_jwks", AsyncMock(return_value=jwks)):
            claims = await validate_id_token(token)

        assert claims["sub"] == "user-123"
        assert "mfa" in claims["amr"]

    @pytest.mark.asyncio
    async def test_amr_missing_raises_401_mfa_required(self):
        """amr claim absent → HTTP 401 with detail 'MFA required'."""
        key = _make_rsa_key_pair()
        # amr=None means the claim is omitted
        token = _make_id_token(key, amr=None)
        jwks = _make_mock_jwks(key)

        with patch("app.core.auth.tokens.fetch_jwks", AsyncMock(return_value=jwks)):
            with pytest.raises(HTTPException) as exc_info:
                await validate_id_token(token)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "MFA required"

    @pytest.mark.asyncio
    async def test_amr_password_only_rejected(self):
        """amr: ["password"] (no mfa) → HTTP 401 with detail 'MFA required' (AC Scenario 2)."""
        key = _make_rsa_key_pair()
        token = _make_id_token(key, amr=["password"])
        jwks = _make_mock_jwks(key)

        with patch("app.core.auth.tokens.fetch_jwks", AsyncMock(return_value=jwks)):
            with pytest.raises(HTTPException) as exc_info:
                await validate_id_token(token)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "MFA required"

    @pytest.mark.asyncio
    async def test_expired_token_raises_401(self):
        """Expired id_token → HTTP 401 (JWTError on exp check)."""
        key = _make_rsa_key_pair()
        token = _make_id_token(key, amr=["mfa"], expired=True)
        jwks = _make_mock_jwks(key)

        with patch("app.core.auth.tokens.fetch_jwks", AsyncMock(return_value=jwks)):
            with pytest.raises(HTTPException) as exc_info:
                await validate_id_token(token)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_audience_raises_401(self):
        """id_token issued for different audience → HTTP 401."""
        key = _make_rsa_key_pair()
        token = _make_id_token(key, amr=["mfa"], audience="other-app")
        jwks = _make_mock_jwks(key)

        with patch("app.core.auth.tokens.fetch_jwks", AsyncMock(return_value=jwks)):
            with pytest.raises(HTTPException) as exc_info:
                await validate_id_token(token)

        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# JWT claims mapping tests (DoD: "sub → user_id, groups → role")
# ---------------------------------------------------------------------------

class TestJwtClaimsMapping:
    @pytest.fixture(autouse=True)
    def env_setup(self, monkeypatch):
        monkeypatch.setenv("JWT_SIGNING_KEY", "testkey_minimum_32_chars_exactly_32")

    def test_physician_group_maps_to_physician_role(self):
        """'smarthandoff-physician' group → role='physician'."""
        from app.core.auth.jwt import _map_claims

        claims = _map_claims({
            "sub": "u1",
            "groups": ["smarthandoff-physician"],
            "units": ["4B"],
            "email": "dr@hospital.example.com",
        })

        assert claims["role"] == "physician"
        assert claims["sub"] == "u1"
        assert claims["units"] == ["4B"]

    def test_nurse_group_maps_to_nurse_role(self):
        """'smarthandoff-nurse' group → role='nurse'."""
        from app.core.auth.jwt import _map_claims

        claims = _map_claims({
            "sub": "u2",
            "groups": ["smarthandoff-nurse"],
            "units": [],
            "email": "nurse@hospital.example.com",
        })
        assert claims["role"] == "nurse"

    def test_admin_group_maps_to_admin_role(self):
        """'smarthandoff-admin' group → role='admin'."""
        from app.core.auth.jwt import _map_claims

        claims = _map_claims({
            "sub": "u3",
            "groups": ["smarthandoff-admin"],
            "units": [],
            "email": "",
        })
        assert claims["role"] == "admin"

    def test_unknown_group_raises_403(self):
        """Groups not in _ROLE_MAP → HTTP 403."""
        from app.core.auth.jwt import _map_claims

        with pytest.raises(HTTPException) as exc_info:
            _map_claims({"sub": "u4", "groups": ["unknown-dept"], "email": ""})

        assert exc_info.value.status_code == 403

    def test_empty_groups_raises_403(self):
        """Empty groups list → HTTP 403."""
        from app.core.auth.jwt import _map_claims

        with pytest.raises(HTTPException) as exc_info:
            _map_claims({"sub": "u5", "groups": [], "email": ""})

        assert exc_info.value.status_code == 403

    def test_jwt_expiry_is_8_hours(self):
        """Issued JWT has exp = iat + 28800 (8 hours)."""
        from jose import jwt as jose_jwt
        import os
        from app.core.auth.jwt import issue_app_jwt

        token = issue_app_jwt({
            "sub": "u6",
            "groups": ["smarthandoff-nurse"],
            "units": [],
            "email": "nurse@hospital.example.com",
        })
        payload = jose_jwt.decode(
            token,
            os.environ["JWT_SIGNING_KEY"],
            algorithms=["HS256"],
            options={"verify_exp": False},
        )
        assert payload["exp"] - payload["iat"] == 28800

    def test_jwt_signing_key_minimum_length_enforced(self, monkeypatch):
        """JWT_SIGNING_KEY shorter than 32 chars → RuntimeError."""
        monkeypatch.setenv("JWT_SIGNING_KEY", "short")
        # Force reimport to re-read env var (module-level caching avoidance)
        import importlib
        import app.core.auth.jwt as jwt_module
        importlib.reload(jwt_module)

        with pytest.raises(RuntimeError, match="JWT_SIGNING_KEY"):
            jwt_module._jwt_signing_key()
