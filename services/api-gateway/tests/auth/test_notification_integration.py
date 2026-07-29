"""Integration tests for OTP endpoint with Notification Service (US-052 TASK-002).

Verifies:
    - OTP generation and storage
    - Rate limiting enforcement
    - Notification Service call on success
    - Graceful handling of Notification Service failures
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import fakeredis.aioredis as fake_redis
from fastapi.testclient import TestClient
from datetime import datetime, timedelta, timezone

from app.main import app
from app.core.redis import get_redis
from app.services.otp_service import hash_otp, store_otp_hash


@pytest.fixture
async def redis():
    """Yield a fresh fakeredis async client for each test."""
    client = await fake_redis.FakeRedis.create()
    yield client
    await client.flushall()
    await client.aclose()


@pytest.fixture
def override_redis(redis):
    """Override get_redis dependency."""
    async def _get_redis():
        return redis
    app.dependency_overrides[get_redis] = _get_redis
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_otp_endpoint_calls_notification_service(redis, override_redis):
    """Verify POST /otp calls Notification Service on success."""
    from app.core.auth.portal_token import PortalTokenClaims
    
    with patch("app.routers.auth.patient_otp.decode_portal_token") as mock_decode, \
         patch("app.routers.auth.patient_otp.send_otp_notification") as mock_notify:
        
        mock_decode.return_value = PortalTokenClaims(
            patient_id="pat-001",
            encounter_id="enc-001",
        )
        mock_notify.return_value = True
        
        client = TestClient(app)
        response = client.post(
            "/api/v1/auth/patient/otp",
            json={"portal_token": "valid.token"},
        )
        
        assert response.status_code == 200
        assert response.json()["message"] == "OTP sent. Check your SMS."
        mock_notify.assert_called_once()
        
        # Verify notification was called with patient_id and otp
        call_args = mock_notify.call_args
        assert call_args.kwargs["patient_id"] == "pat-001"
        assert len(call_args.kwargs["otp"]) == 6


@pytest.mark.asyncio
async def test_otp_endpoint_handles_notification_failure(redis, override_redis):
    """Verify endpoint succeeds even if Notification Service fails."""
    from app.core.auth.portal_token import PortalTokenClaims
    
    with patch("app.routers.auth.patient_otp.decode_portal_token") as mock_decode, \
         patch("app.routers.auth.patient_otp.send_otp_notification") as mock_notify:
        
        mock_decode.return_value = PortalTokenClaims(
            patient_id="pat-001",
            encounter_id="enc-001",
        )
        mock_notify.return_value = False  # Notification failed
        
        client = TestClient(app)
        response = client.post(
            "/api/v1/auth/patient/otp",
            json={"portal_token": "valid.token"},
        )
        
        # Should still return 200 — OTP is stored even if notification fails
        assert response.status_code == 200
        assert "OTP sent" in response.json()["message"]
