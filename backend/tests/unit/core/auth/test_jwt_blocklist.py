"""Unit tests for app/core/auth/jwt_blocklist.py.

Uses fakeredis to stub Cloud Memorystore so tests run without a real
Redis server. The _get_redis_client lru_cache is patched per-test.

Coverage target: ≥80% branch coverage on jwt_blocklist.py (TR-020).

Design refs:
    US-059 TASK-006 — unit tests: blocklist lookup
"""
from __future__ import annotations

import time
from unittest.mock import patch

import fakeredis
import pytest

from app.core.auth import jwt_blocklist as bl_module
from app.core.auth.jwt_blocklist import add_to_blocklist, is_blocklisted


@pytest.fixture(autouse=True)
def fake_redis():
    """Patch _get_redis_client to return a fakeredis instance per test."""
    server = fakeredis.FakeServer()
    fake = fakeredis.FakeRedis(server=server, decode_responses=True)
    with patch.object(bl_module, "_get_redis_client", return_value=fake):
        yield fake


class TestAddToBlocklist:
    def test_adds_key_with_correct_ttl(self, fake_redis):
        """Key exists in Redis after add_to_blocklist with positive TTL."""
        jti = "test-jti-001"
        exp = int(time.time()) + 3600  # 1 hour from now
        add_to_blocklist(jti, exp)
        assert fake_redis.exists(f"jwt_blocklist:{jti}") == 1

    def test_ttl_within_expected_range(self, fake_redis):
        """Redis TTL is approximately remaining token lifetime (±2 seconds tolerance)."""
        jti = "test-jti-002"
        remaining = 7200  # 2 hours
        exp = int(time.time()) + remaining
        add_to_blocklist(jti, exp)
        actual_ttl = fake_redis.ttl(f"jwt_blocklist:{jti}")
        assert remaining - 2 <= actual_ttl <= remaining

    def test_expired_token_not_written(self, fake_redis):
        """Already-expired JWTs are not written to Redis (TTL ≤ 0)."""
        jti = "test-jti-expired"
        exp = int(time.time()) - 60  # expired 1 minute ago
        add_to_blocklist(jti, exp)
        assert fake_redis.exists(f"jwt_blocklist:{jti}") == 0

    def test_key_prefix_is_correct(self, fake_redis):
        """Key uses the 'jwt_blocklist:{jti}' prefix schema."""
        jti = "prefix-check-jti"
        exp = int(time.time()) + 3600
        add_to_blocklist(jti, exp)
        # Exact prefix must match to avoid namespace collisions
        assert fake_redis.exists(f"jwt_blocklist:{jti}") == 1
        assert fake_redis.exists(jti) == 0  # no bare key

    def test_value_is_one(self, fake_redis):
        """The Redis value for a blocklisted key is '1'."""
        jti = "value-check-jti"
        exp = int(time.time()) + 3600
        add_to_blocklist(jti, exp)
        assert fake_redis.get(f"jwt_blocklist:{jti}") == "1"


class TestIsBlocklisted:
    def test_returns_false_for_unknown_jti(self):
        """Non-blocklisted jti returns False."""
        assert is_blocklisted("unknown-jti-xyz") is False

    def test_returns_true_after_add(self, fake_redis):
        """Blocklisted jti returns True."""
        jti = "test-jti-003"
        exp = int(time.time()) + 3600
        add_to_blocklist(jti, exp)
        assert is_blocklisted(jti) is True

    def test_returns_false_after_key_deleted(self, fake_redis):
        """After key is deleted (simulating TTL expiry) jti is no longer blocklisted."""
        jti = "test-jti-004"
        add_to_blocklist(jti, int(time.time()) + 3600)
        assert is_blocklisted(jti) is True
        # Simulate TTL expiry by deleting the key directly
        fake_redis.delete(f"jwt_blocklist:{jti}")
        assert is_blocklisted(jti) is False

    def test_different_jtis_are_independent(self, fake_redis):
        """Blocklisting one jti does not affect another."""
        jti_a = "jti-alpha"
        jti_b = "jti-beta"
        exp = int(time.time()) + 3600
        add_to_blocklist(jti_a, exp)
        assert is_blocklisted(jti_a) is True
        assert is_blocklisted(jti_b) is False
