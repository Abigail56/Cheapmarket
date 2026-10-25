import hashlib
import hmac
import json

from app.core.config import settings
from app.services import providers
from tests.conftest import add_to_cart, checkout_body

KEY = "sk_test_secret"


def sign(raw: bytes) -> str:
    return hmac.new(KEY.encode(), raw, hashlib.sha512).hexdigest()


async def card_order(client, shop, qty=2):
    cart = await add_to_cart(client, shop["tomato"], qty)
    r = await client.post("/orders", json=checkout_body(shop, payment_method="card",
                          customer_email="ada@example.com"),
                          headers={"X-Cart-Session": cart["session_id"]})
    assert r.status_code == 201, r.text
    assert r.json()["next_step"] == "pay_online"
    return r.json()["order"]


async def init_paystack(client, monkeypatch, order):
    settings.PAYSTACK_SECRET_KEY = KEY
    seen = {}

    async def fake_init(**kw):
        seen.update(kw)
        return {"authorization_url": "https://paystack.test/pay/abc", "reference": kw["reference"]}

    monkeypatch.setattr(providers, "paystack_initialize", fake_init)
    r = await client.post("/payments/initialize",
                          json={"order_number": order["order_number"], "phone": "08031234567"})
    assert r.status_code == 200, r.text
    return r.json(), seen


async def send_webhook(client, payload: dict, signature: str | None = None):
    raw = json.dumps(payload).encode()
    return await client.post("/payments/webhook/paystack", content=raw,
                             headers={"x-paystack-signature": signature or sign(raw),
                                      "content-type": "application/json"})


async def test_paystack_happy_path(client, shop, monkeypatch):
    order = await card_order(client, shop)  # 5,000 + 1,500 = 6,500
    init, seen = await init_paystack(client, monkeypatch, order)
    assert init["authorization_url"].startswith("https://paystack.test")
    assert seen["amount"] == order["total"] and seen["email"] == "ada@example.com"

    r = await send_webhook(client, {"event": "charge.success", "data": {
        "reference": init["reference"], "status": "success", "amount": 650000}})
    assert r.status_code == 200
    r = await client.post("/orders/track", json={"order_number": order["order_number"], "phone": "08031234567"})
    assert r.json()["payment_status"] == "paid" and r.json()["status"] == "confirmed"


async def test_webhook_replay_is_harmless(client, shop, monkeypatch):
    order = await card_order(client, shop)
    init, _ = await init_paystack(client, monkeypatch, order)
    ev = {"event": "charge.success", "data": {"reference": init["reference"], "status": "success", "amount": 650000}}
    assert (await send_webhook(client, ev)).status_code == 200
    assert (await send_webhook(client, ev)).status_code == 200
    r = await client.post("/orders/track", json={"order_number": order["order_number"], "phone": "08031234567"})
    assert r.json()["status"] == "confirmed"


async def test_bad_signature_rejected(client, shop, monkeypatch):
    order = await card_order(client, shop)
    init, _ = await init_paystack(client, monkeypatch, order)
    ev = {"event": "charge.success", "data": {"reference": init["reference"], "status": "success", "amount": 650000}}
    r = await send_webhook(client, ev, signature="deadbeef")
    assert r.status_code == 403
    r = await client.post("/orders/track", json={"order_number": order["order_number"], "phone": "08031234567"})
    assert r.json()["payment_status"] == "unpaid"


async def test_underpayment_does_not_mark_paid(client, shop, monkeypatch):
    order = await card_order(client, shop)
    init, _ = await init_paystack(client, monkeypatch, order)
    ev = {"event": "charge.success", "data": {"reference": init["reference"], "status": "success", "amount": 100}}
    assert (await send_webhook(client, ev)).status_code == 200
    r = await client.post("/orders/track", json={"order_number": order["order_number"], "phone": "08031234567"})
    assert r.json()["payment_status"] == "unpaid" and r.json()["status"] == "pending"


async def test_verify_endpoint(client, shop, monkeypatch):
    order = await card_order(client, shop)
    init, _ = await init_paystack(client, monkeypatch, order)

    async def fake_verify(reference):
        return {"success": True, "amount_kobo": 650000, "raw": {"status": "success"}}

    monkeypatch.setattr(providers, "paystack_verify", fake_verify)
    r = await client.get(f"/payments/verify/{init['reference']}")
    assert r.status_code == 200 and r.json()["payment_status"] == "paid"


async def test_cannot_pay_cod_order_online_or_pay_twice(client, shop, monkeypatch):
    cart = await add_to_cart(client, shop["tomato"], 1)
    r = await client.post("/orders", json=checkout_body(shop), headers={"X-Cart-Session": cart["session_id"]})
    r = await client.post("/payments/initialize", json={
        "order_number": r.json()["order"]["order_number"], "phone": "08031234567"})
    assert r.json()["error"]["code"] == "not_card_order"

    order = await card_order(client, shop)
    init, _ = await init_paystack(client, monkeypatch, order)
    await send_webhook(client, {"event": "charge.success", "data": {
        "reference": init["reference"], "status": "success", "amount": 650000}})
    r = await client.post("/payments/initialize", json={"order_number": order["order_number"], "phone": "08031234567"})
    assert r.json()["error"]["code"] == "already_paid"


async def test_flutterwave_webhook_reverifies_with_gateway(client, shop, monkeypatch):
    settings.FLUTTERWAVE_SECRET_KEY = "flw_key"
    settings.FLUTTERWAVE_SECRET_HASH = "my-hash"
    order = await card_order(client, shop)

    async def fake_init(**kw):
        return {"authorization_url": "https://flw.test/pay", "reference": kw["reference"]}

    async def fake_verify(reference):
        return {"success": True, "amount_kobo": 650000, "raw": {"status": "successful"}}

    monkeypatch.setattr(providers, "flutterwave_initialize", fake_init)
    monkeypatch.setattr(providers, "flutterwave_verify", fake_verify)
    init = (await client.post("/payments/initialize", json={
        "order_number": order["order_number"], "provider": "flutterwave", "phone": "08031234567"})).json()
    body = {"event": "charge.completed", "data": {"tx_ref": init["reference"]}}
    assert (await client.post("/payments/webhook/flutterwave", json=body,
                              headers={"verif-hash": "wrong"})).status_code == 403
    assert (await client.post("/payments/webhook/flutterwave", json=body,
                              headers={"verif-hash": "my-hash"})).status_code == 200
    r = await client.post("/orders/track", json={"order_number": order["order_number"], "phone": "08031234567"})
    assert r.json()["payment_status"] == "paid"


async def test_local_mock_mode_simulation(client, shop):
    order = await card_order(client, shop)
    init = (await client.post("/payments/initialize", json={
        "order_number": order["order_number"], "phone": "08031234567"})).json()
    assert init["mock"] is True
    r = await client.post(f"/payments/dev/simulate-success/{init['reference']}")
    assert r.json()["payment_status"] == "paid" and r.json()["status"] == "confirmed"
