"""Staff can be told about new orders by SMS and email, for when the dashboard is closed."""
from app.core.config import settings
from tests.conftest import add_to_cart, checkout_body, queued_messages


async def _place(client, shop):
    cart = await add_to_cart(client, shop["tomato"], 1)
    r = await client.post("/orders", json=checkout_body(shop), headers={"X-Cart-Session": cart["session_id"]})
    assert r.status_code == 201, r.text
    return r.json()["order"]


async def test_new_order_alerts_every_listed_contact(client, shop, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_ALERT_PHONES", "08011111111, 08022222222")
    monkeypatch.setattr(settings, "ADMIN_ALERT_EMAILS", "boss@example.com")
    order = await _place(client, shop)
    alerts = [m for m in await queued_messages() if f"New order {order['order_number']}" in m["body"]]
    assert sorted(m["to"] for m in alerts) == ["08011111111", "08022222222", "boss@example.com"]
    assert "pay on delivery" in alerts[0]["body"]


async def test_no_contacts_means_no_alerts(client, shop, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_ALERT_PHONES", "")
    monkeypatch.setattr(settings, "ADMIN_ALERT_EMAILS", "")
    order = await _place(client, shop)
    assert not [m for m in await queued_messages() if f"New order {order['order_number']}" in m["body"]]
