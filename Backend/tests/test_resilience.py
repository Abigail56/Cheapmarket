import httpx
import pytest_asyncio
from redis.exceptions import ConnectionError as RedisConnectionError

import app.db.redis as redis_module
from app.core.config import settings
from app.db.redis import get_redis
from app.main import app
from app.services import catalog_service, notifications
from tests.conftest import create_user


class BrokenRedis:
    """Stands in for a Redis server that is down: every command fails."""

    def __getattr__(self, name):
        async def fail(*args, **kwargs):
            raise RedisConnectionError("Redis is down")
        return fail

    def pipeline(self, *args, **kwargs):
        return _BrokenPipeline()

    async def scan_iter(self, *args, **kwargs):
        raise RedisConnectionError("Redis is down")
        yield  # pragma: no cover (makes this an async generator)


class _BrokenPipeline:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __getattr__(self, name):
        return lambda *a, **kw: None

    async def execute(self):
        raise RedisConnectionError("Redis is down")


@pytest_asyncio.fixture
async def redis_down(monkeypatch):
    broken = BrokenRedis()
    app.dependency_overrides[get_redis] = lambda: broken
    monkeypatch.setattr(redis_module, "redis_client", broken)
    monkeypatch.setattr(notifications, "redis_client", broken)
    yield
    app.dependency_overrides.pop(get_redis, None)


async def test_responses_carry_a_request_id(client):
    r = await client.get("/categories")
    assert len(r.headers["x-request-id"]) == 32
    r = await client.get("/categories", headers={"X-Request-ID": "trace-abc_123"})
    assert r.headers["x-request-id"] == "trace-abc_123"
    # junk (or log-injection attempts) is replaced, not echoed
    r = await client.get("/categories", headers={"X-Request-ID": "bad id\nwith newline"})
    assert r.headers["x-request-id"] != "bad id\nwith newline"


async def test_unexpected_errors_return_clean_500(monkeypatch):
    async def boom(session):
        raise RuntimeError("database exploded")

    monkeypatch.setattr(catalog_service, "get_categories", boom)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1") as c:
        r = await c.get("/categories", headers={"X-Request-ID": "req-42"})
    assert r.status_code == 500
    err = r.json()["error"]
    assert err["code"] == "internal_error" and err["request_id"] == "req-42"
    assert "exploded" not in r.text  # internals are not leaked


async def test_shop_keeps_working_when_redis_is_down(client, shop, redis_down):
    settings.RATE_LIMIT_ENABLED = True  # conftest turns it back off for the next test
    # browse (cache misses go straight to the database)
    r = await client.get("/products")
    assert r.status_code == 200 and r.json()["total"] == 3
    # register and log in (rate limit + lockout are skipped, not fatal)
    u = await create_user(client)
    # authenticated requests still work
    assert (await client.get("/users/me", headers=u["headers"])).status_code == 200


async def test_admin_edit_succeeds_when_cache_cannot_be_cleared(client, shop, admin, redis_down):
    r = await client.patch(f"/admin/products/{shop['tomato']}", headers=admin["headers"],
                           json={"price": "2700"})
    assert r.status_code == 200 and r.json()["price"] == 2700.0
