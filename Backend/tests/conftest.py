"""Tests run against REAL PostgreSQL and Redis (use `docker compose up -d db redis`).
They use a separate database (cmd_test) and Redis DB 15, so dev data is never touched."""
import os
import tempfile

os.environ["POSTGRES_DB"] = os.environ.get("TEST_POSTGRES_DB", "cmd_test")
os.environ["REDIS_DB"] = "15"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["ENVIRONMENT"] = "local"
os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789-abcdefghijklmnop")
os.environ.setdefault("POSTGRES_USER", "cmd_user")
os.environ.setdefault("POSTGRES_PASSWORD", "cmd_password")
os.environ["PAYSTACK_SECRET_KEY"] = ""
os.environ["FLUTTERWAVE_SECRET_KEY"] = ""
os.environ["MEDIA_DIR"] = tempfile.mkdtemp(prefix="cmd-test-media-")
os.environ["SMS_BACKEND"] = "console"
os.environ["EMAIL_BACKEND"] = "console"
os.environ["STORAGE_BACKEND"] = "local"

import json
import uuid
from decimal import Decimal

import httpx
import pytest_asyncio
from sqlalchemy import text
from sqlmodel import SQLModel

from app.core.config import settings
from app.db import base  # noqa: F401
from app.db.redis import redis_client
from app.db.session import AsyncSessionLocal, engine
from app.main import app
from app.models import Category, Coupon, DeliveryZone, DiscountType, Product, User, UserRole

settings.PAYSTACK_SECRET_KEY = None
settings.FLUTTERWAVE_SECRET_KEY = None
settings.RATE_LIMIT_ENABLED = False


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _schema():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    yield
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _clean():
    names = ", ".join(t.name for t in SQLModel.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    await redis_client.flushdb()
    settings.PAYSTACK_SECRET_KEY = None
    settings.FLUTTERWAVE_SECRET_KEY = None
    settings.FLUTTERWAVE_SECRET_HASH = None
    settings.RATE_LIMIT_ENABLED = False
    yield


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1") as c:
        yield c


@pytest_asyncio.fixture
async def shop():
    """A tiny store: 2 categories, 3 products, a zone, a coupon."""
    async with AsyncSessionLocal() as s:
        veg = Category(name="Vegetables", slug="vegetables")
        fruit = Category(name="Fruits", slug="fruits")
        s.add_all([veg, fruit])
        await s.flush()
        tomato = Product(category_id=veg.id, name="Tomatoes", slug="tomatoes", unit="basket",
                         price=Decimal(2500), compare_at_price=Decimal(3000), stock_qty=10,
                         is_featured=True)
        rice = Product(category_id=veg.id, name="Rice", slug="rice", unit="5 kg",
                       price=Decimal(9500), stock_qty=5)
        mango = Product(category_id=fruit.id, name="Mango", slug="mango", unit="6 pcs",
                        price=Decimal(1000), stock_qty=0)
        zone = DeliveryZone(name="Zone A", delivery_fee=Decimal(1500),
                            free_delivery_min=Decimal(20000))
        coupon = Coupon(code="SAVE10", discount_type=DiscountType.PERCENT, value=Decimal(10))
        s.add_all([tomato, rice, mango, zone, coupon])
        await s.commit()
        return {"veg": veg.id, "fruit": fruit.id, "tomato": tomato.id, "rice": rice.id,
                "mango": mango.id, "zone": zone.id, "coupon": coupon.id}


async def create_user(client, email="shopper@example.com", role=UserRole.CUSTOMER,
                      password="Passw0rd!x", phone=None, name="Test User") -> dict:
    """Registers via the API, optionally promotes the role in the DB, returns auth headers."""
    r = await client.post("/auth/register", json={"email": email, "full_name": name,
                                                   "password": password, "phone": phone})
    assert r.status_code == 201, r.text
    user_id = r.json()["user"]["id"]
    if role != UserRole.CUSTOMER:
        async with AsyncSessionLocal() as s:
            u = await s.get(User, uuid.UUID(user_id))
            u.role = role
            s.add(u)
            await s.commit()
    r = await client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    tokens = r.json()
    return {"id": user_id, "headers": {"Authorization": f"Bearer {tokens['access_token']}"},
            "tokens": tokens, "email": email, "password": password}


@pytest_asyncio.fixture
async def admin(client):
    return await create_user(client, "admin@example.com", UserRole.ADMIN, name="Admin")


@pytest_asyncio.fixture
async def customer(client):
    return await create_user(client)


async def add_to_cart(client, product_id, qty=1, headers=None, session_id=None) -> dict:
    h = dict(headers or {})
    if session_id:
        h["X-Cart-Session"] = session_id
    r = await client.post("/cart/items", json={"product_id": str(product_id), "quantity": qty}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def checkout_body(shop, **over) -> dict:
    body = {"customer_name": "Ada Obi", "customer_phone": "08031234567",
            "delivery_address": "12 Market Road, Opposite the Church", "zone_id": str(shop["zone"]),
            "payment_method": "cod"}
    body.update(over)
    return body


async def queued_messages() -> list[dict]:
    """Notifications waiting for the worker, oldest first."""
    from app.services.notifications import QUEUE_KEY
    raw = await redis_client.lrange(QUEUE_KEY, 0, -1)
    return [json.loads(m) for m in reversed(raw)]


async def last_code(to: str) -> str:
    """The 6-digit code in the newest queued message to `to`."""
    import re
    for msg in reversed(await queued_messages()):
        if msg["to"] == to and (m := re.search(r"\b(\d{6})\b", msg["body"])):
            return m.group(1)
    raise AssertionError(f"no code queued for {to}")
