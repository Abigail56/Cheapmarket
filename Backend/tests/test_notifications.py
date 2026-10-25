import json

import httpx

from app import worker
from app.core.config import settings
from app.db.redis import redis_client
from app.services import notifications
from tests.conftest import add_to_cart, checkout_body, queued_messages


async def place_order(client, shop, **over):
    cart = await add_to_cart(client, shop["tomato"], 2)
    r = await client.post("/orders", json=checkout_body(shop, **over),
                          headers={"X-Cart-Session": cart["session_id"]})
    assert r.status_code == 201, r.text
    return r.json()["order"]


async def test_checkout_queues_sms_and_email(client, shop):
    order = await place_order(client, shop, customer_email="ada@example.com")
    msgs = await queued_messages()
    assert [(m["channel"], m["to"]) for m in msgs] == [("sms", "+2348031234567"),
                                                       ("email", "ada@example.com")]
    assert order["order_number"] in msgs[0]["body"]
    assert "NGN 6,500.00" in msgs[0]["body"]


async def test_status_changes_notify_customer(client, shop, admin):
    order = await place_order(client, shop)  # COD, no email
    await redis_client.delete(notifications.QUEUE_KEY)
    h = admin["headers"]
    n = order["order_number"]
    await client.patch(f"/admin/orders/{n}/status", headers=h, json={"status": "confirmed"})
    await client.patch(f"/admin/orders/{n}/status", headers=h, json={"status": "packed"})  # silent
    await client.patch(f"/admin/orders/{n}/status", headers=h, json={"status": "cancelled"})
    bodies = [m["body"] for m in await queued_messages()]
    assert len(bodies) == 2
    assert "confirmed" in bodies[0] and "cancelled" in bodies[1]


async def test_worker_sends_queued_message(client, shop, monkeypatch):
    await place_order(client, shop)
    sent = []

    async def fake_send(msg):
        sent.append(msg)

    monkeypatch.setattr(notifications, "send", fake_send)
    assert await worker.process_one_notification(timeout=1) is True
    assert sent[0]["to"] == "+2348031234567"
    assert await queued_messages() == []
    assert await worker.process_one_notification(timeout=1) is False  # queue empty


async def test_worker_retries_then_gives_up(monkeypatch):
    calls = []

    async def failing_send(msg):
        calls.append(msg["attempts"])
        raise notifications.NotificationError("provider down")

    async def no_sleep(_):
        return None

    monkeypatch.setattr(notifications, "send", failing_send)
    monkeypatch.setattr(worker.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(settings, "NOTIFICATION_MAX_ATTEMPTS", 2)
    await notifications.enqueue("sms", "+2348031234567", "hello")
    await worker.process_one_notification(timeout=1)  # fails, re-queued
    [msg] = await queued_messages()
    assert msg["attempts"] == 1
    await worker.process_one_notification(timeout=1)  # fails again, dropped
    assert calls == [0, 1]
    assert await queued_messages() == []


async def test_termii_backend_sends_expected_request(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message_id": "1"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(notifications.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(settings, "SMS_BACKEND", "termii")
    monkeypatch.setattr(settings, "TERMII_API_KEY", "tk_test")
    await notifications.send({"channel": "sms", "to": "+2348031234567", "body": "hi", "subject": ""})
    assert seen["url"].endswith("/api/sms/send")
    assert seen["body"]["to"] == "2348031234567" and seen["body"]["sms"] == "hi"
    assert seen["body"]["api_key"] == "tk_test"


async def test_termii_error_raises(monkeypatch):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(notifications.httpx, "AsyncClient", lambda **kw: real_client(
        transport=httpx.MockTransport(lambda r: httpx.Response(401, text="bad key")), **kw))
    monkeypatch.setattr(settings, "SMS_BACKEND", "termii")
    monkeypatch.setattr(settings, "TERMII_API_KEY", "tk_test")
    try:
        await notifications.send({"channel": "sms", "to": "+234803", "body": "hi", "subject": ""})
    except notifications.NotificationError as e:
        assert "401" in str(e)
    else:
        raise AssertionError("expected NotificationError")
