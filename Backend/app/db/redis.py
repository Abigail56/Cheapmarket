import json
import logging
from typing import Any

import redis.asyncio as redis

from app.core.config import settings

log = logging.getLogger(__name__)

SOCKET_TIMEOUT = 5  # seconds; fail fast if Redis hangs. Blocking reads (BRPOP) must wait less
pool = redis.ConnectionPool.from_url(
    settings.REDIS_URL, decode_responses=True, max_connections=20,
    socket_timeout=SOCKET_TIMEOUT, socket_connect_timeout=SOCKET_TIMEOUT,
)
redis_client = redis.Redis(connection_pool=pool)


async def get_redis() -> redis.Redis:
    return redis_client


async def close_redis() -> None:
    await redis_client.aclose()
    await pool.aclose()


async def incr_window(r: redis.Redis, key: str, window: int) -> int:
    """Count a hit in a fixed window. INCR and EXPIRE run in one transaction, so a
    crash between them can't leave a counter that never expires."""
    async with r.pipeline(transaction=True) as pipe:
        pipe.incr(key)
        pipe.expire(key, window, nx=True)  # only the first hit starts the window
        count, _ = await pipe.execute()
    return count


# Small JSON cache helpers ------------------------------------------------------
# The cache is an optimisation: if Redis is down, reads miss and writes are skipped,
# so the catalogue keeps working straight from PostgreSQL.
async def cache_get(key: str) -> Any | None:
    try:
        raw = await redis_client.get(key)
    except redis.RedisError:
        log.warning("Redis unavailable, cache miss for %s", key)
        return None
    return json.loads(raw) if raw else None


async def cache_set(key: str, value: Any, ttl: int | None = None) -> None:
    try:
        await redis_client.set(
            key, json.dumps(value, default=str), ex=ttl or settings.CACHE_TTL_SECONDS
        )
    except redis.RedisError:
        log.warning("Redis unavailable, not caching %s", key)


async def cache_delete_prefix(prefix: str) -> int:
    """Invalidate e.g. 'cache:products:*' after an admin edits a product."""
    deleted = 0
    try:
        async for key in redis_client.scan_iter(match=f"{prefix}*", count=200):
            deleted += await redis_client.delete(key)
    except redis.RedisError:
        # entries left behind expire on their own after CACHE_TTL_SECONDS
        log.error("Redis unavailable, could not invalidate cache prefix %s", prefix)
    return deleted
