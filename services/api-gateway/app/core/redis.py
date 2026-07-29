"""Redis connection management and dependency injection for FastAPI."""
from __future__ import annotations

import redis.asyncio as aioredis
from api_gateway.app.core.config import settings

_redis_client: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """Get or create the async Redis client for dependency injection."""
    global _redis_client
    if _redis_client is None:
        _redis_client = await aioredis.from_url(settings.REDIS_URL, decode_responses=False)
    return _redis_client


async def close_redis() -> None:
    """Close the Redis connection on application shutdown."""
    global _redis_client
    if _redis_client:
        await _redis_client.close()
        _redis_client = None
