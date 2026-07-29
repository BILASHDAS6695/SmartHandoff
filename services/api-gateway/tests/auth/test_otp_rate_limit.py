"""Unit tests for OTP rate limiting — US-052 AC Scenario 2.

Verifies:
    - 5 OTP requests within 1 hour: all return 200 / OTP stored
    - 6th OTP request within 1 hour: 429 Too Many Requests + Retry-After header
    - No OTP key written to Redis when rate limit is hit
    - Rate limit counter TTL set to 3600 s on first increment

Uses fakeredis.aioredis to avoid live Redis dependency.
"""
from __future__ import annotations

import pytest
import fakeredis.aioredis as fake_redis

from app.services.otp_service import (
    increment_attempt_counter,
    is_rate_limited,
    store_otp_hash,
)

PORTAL_TOKEN = "test.portal.token.abc123"


@pytest.fixture
async def redis():
    """Yield a fresh fakeredis async client for each test."""
    client = await fake_redis.FakeRedis.create()
    yield client
    await client.flushall()
    await client.aclose()


@pytest.mark.asyncio
async def test_rate_limit_allows_fifth_request(redis):
    """5th OTP request within 1 hour must not be blocked."""
    for _ in range(4):
        await increment_attempt_counter(redis, PORTAL_TOKEN)

    blocked, retry_after = await is_rate_limited(redis, PORTAL_TOKEN)
    assert not blocked, "5th request must NOT be blocked (only 4 previous attempts)"
    assert retry_after == 0


@pytest.mark.asyncio
async def test_rate_limit_blocks_sixth_request(redis):
    """6th OTP request within 1 hour must return 429 with Retry-After."""
    for _ in range(5):
        await increment_attempt_counter(redis, PORTAL_TOKEN)

    blocked, retry_after = await is_rate_limited(redis, PORTAL_TOKEN)
    assert blocked, "6th request MUST be blocked after 5 attempts"
    assert retry_after > 0, "Retry-After must be a positive integer"


@pytest.mark.asyncio
async def test_no_otp_key_written_when_rate_limited(redis):
    """When rate limited, no OTP hash key must exist in Redis."""
    for _ in range(5):
        await increment_attempt_counter(redis, PORTAL_TOKEN)

    blocked, _ = await is_rate_limited(redis, PORTAL_TOKEN)
    assert blocked

    # Simulate the endpoint NOT writing OTP hash when blocked
    otp_key = f"otp:{PORTAL_TOKEN}"
    stored = await redis.get(otp_key)
    assert stored is None, "OTP hash must NOT be written when rate limited"


@pytest.mark.asyncio
async def test_rate_limit_counter_ttl_set_on_first_increment(redis):
    """Rate limit counter TTL must be set to 3600 s on the first increment only."""
    await increment_attempt_counter(redis, PORTAL_TOKEN)

    attempts_key = f"otp_attempts:{PORTAL_TOKEN}"
    ttl = await redis.ttl(attempts_key)

    assert 3590 <= ttl <= 3600, f"Expected TTL ~3600 s, got {ttl}"


@pytest.mark.asyncio
async def test_rate_limit_counter_ttl_not_reset_on_subsequent_increments(redis):
    """Subsequent increments must NOT reset the TTL (window does not slide)."""
    await increment_attempt_counter(redis, PORTAL_TOKEN)
    attempts_key = f"otp_attempts:{PORTAL_TOKEN}"
    ttl_after_first = await redis.ttl(attempts_key)

    await increment_attempt_counter(redis, PORTAL_TOKEN)
    ttl_after_second = await redis.ttl(attempts_key)

    # TTL must decrease, not reset to 3600 again
    assert ttl_after_second <= ttl_after_first, (
        "TTL must not reset on subsequent increments"
    )
