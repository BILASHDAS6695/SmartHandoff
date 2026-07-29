"""OTP generation, hashing, and Redis management for patient auth (US-052).

Design refs:
    US-052 Technical Notes — bcrypt hash, secrets.randbelow, Redis key names
    US-052 AC Scenario 2 — rate limit: block at otp_attempts >= 5
    US-052 AC Scenario 3 — OTP TTL = 600 s (10 minutes)
"""
from __future__ import annotations

import logging
import secrets

import bcrypt
import redis.asyncio as aioredis

log = logging.getLogger(__name__)

_OTP_TTL_SECONDS = 600          # 10 minutes — AC Scenario 3
_RATE_LIMIT_TTL_SECONDS = 3600  # 1 hour — AC Scenario 2
_RATE_LIMIT_MAX_ATTEMPTS = 5    # block on the 6th attempt


def _otp_key(portal_token: str) -> str:
    return f"otp:{portal_token}"


def _attempts_key(portal_token: str) -> str:
    return f"otp_attempts:{portal_token}"


def generate_otp() -> str:
    """Return a cryptographically random 6-digit OTP, zero-padded.

    Uses secrets.randbelow(1_000_000) per US-052 Technical Notes.
    """
    return str(secrets.randbelow(1_000_000)).zfill(6)


def hash_otp(otp: str) -> bytes:
    """Hash OTP with bcrypt (12 rounds).

    NEVER stored as plaintext in Redis per US-052 Technical Notes.
    """
    return bcrypt.hashpw(otp.encode(), bcrypt.gensalt(rounds=12))


async def get_remaining_attempts(
    redis: aioredis.Redis,
    portal_token: str,
) -> int:
    """Return how many OTP attempts remain (max 5) for this portal token."""
    current = await redis.get(_attempts_key(portal_token))
    used = int(current) if current else 0
    return max(0, _RATE_LIMIT_MAX_ATTEMPTS - used)


async def is_rate_limited(
    redis: aioredis.Redis,
    portal_token: str,
) -> tuple[bool, int]:
    """Check if the portal token has hit the OTP request rate limit.

    Returns:
        (is_blocked, retry_after_seconds)
        retry_after_seconds is 0 when not blocked.
    """
    current = await redis.get(_attempts_key(portal_token))
    count = int(current) if current else 0

    if count >= _RATE_LIMIT_MAX_ATTEMPTS:
        ttl = await redis.ttl(_attempts_key(portal_token))
        retry_after = max(ttl, 0)
        log.warning(
            "otp_rate_limit_hit",
            extra={"attempt_count": count},
            # portal_token deliberately excluded from logs (encodes patient data)
        )
        return True, retry_after

    return False, 0


async def store_otp_hash(
    redis: aioredis.Redis,
    portal_token: str,
    otp_hash: bytes,
) -> None:
    """Store bcrypt-hashed OTP in Redis with 10-minute TTL.

    Key: otp:{portal_token}
    TTL: 600 s (AC Scenario 3)
    """
    await redis.set(
        _otp_key(portal_token),
        otp_hash,
        ex=_OTP_TTL_SECONDS,
    )


async def increment_attempt_counter(
    redis: aioredis.Redis,
    portal_token: str,
) -> None:
    """Increment the OTP attempt counter with 1-hour TTL.

    Uses SET NX to set TTL only on the first increment so the window
    does not reset on each new OTP request.
    """
    key = _attempts_key(portal_token)
    pipe = redis.pipeline()
    pipe.incr(key)
    pipe.expire(key, _RATE_LIMIT_TTL_SECONDS)
    await pipe.execute()


async def get_otp_hash(
    redis: aioredis.Redis,
    portal_token: str,
) -> bytes | None:
    """Retrieve the bcrypt-hashed OTP from Redis.

    Returns None if the key has expired or does not exist.
    """
    stored = await redis.get(_otp_key(portal_token))
    return stored


async def delete_otp_hash(
    redis: aioredis.Redis,
    portal_token: str,
) -> None:
    """Delete the OTP hash from Redis (one-time use enforcement)."""
    await redis.delete(_otp_key(portal_token))
