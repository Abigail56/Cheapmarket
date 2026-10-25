import asyncio

from app.db.session import AsyncSessionLocal
from app.models import Coupon, Product
from tests.conftest import add_to_cart, checkout_body, create_user


async def stock_of(pid) -> int:
    async with AsyncSessionLocal() as s:
        return (await s.get(Product, pid)).stock_qty


async def test_quote_free_delivery_and_coupon(client, shop):
    cart = await add_to_cart(client, shop["tomato"], 2)  # 5,000
    h = {"X-Cart-Session": cart["session_id"]}
    q = (await client.post("/checkout/quote", json={"zone_id": str(shop["zone"])}, headers=h)).json()
    assert q["delivery_fee"] == 1500.0 and q["total"] == 6500.0
    assert q["free_delivery_remaining"] == 15000.0
    q = (await client.post("/checkout/quote", json={"zone_id": str(shop["zone"]),
                           "coupon_code": "save10"}, headers=h)).json()
    assert q["discount_total"] == 500.0 and q["total"] == 6000.0 and q["coupon_applied"] == "SAVE10"

    await add_to_cart(client, shop["rice"], 2, session_id=cart["session_id"])  # subtotal 24,000
    q = (await client.post("/checkout/quote", json={"zone_id": str(shop["zone"])}, headers=h)).json()
    assert q["delivery_fee"] == 0 and q["total"] == 24000.0


async def test_guest_cod_checkout(client, shop):
    cart = await add_to_cart(client, shop["tomato"], 3)  # 7,500
    h = {"X-Cart-Session": cart["session_id"]}
    r = await client.post("/orders", json=checkout_body(shop, coupon_code="SAVE10"), headers=h)
    assert r.status_code == 201, r.text
    body = r.json()
    o = body["order"]
    assert body["next_step"] == "pay_on_delivery"
    assert o["order_number"].startswith("CMD-") and o["status"] == "pending"
    assert (o["subtotal"], o["delivery_fee"], o["discount_total"], o["total"]) == (7500.0, 1500.0, 750.0, 8250.0)
    assert o["customer_phone"] == "+2348031234567"
    assert o["items"][0]["product_name"] == "Tomatoes" and o["items"][0]["quantity"] == 3
    assert await stock_of(shop["tomato"]) == 7                      # stock decremented
    assert (await client.get("/cart", headers=h)).json()["items"] == []  # cart emptied
    async with AsyncSessionLocal() as s:
        assert (await s.get(Coupon, shop["coupon"])).used_count == 1


async def test_prices_come_from_the_server_not_the_client(client, shop):
    cart = await add_to_cart(client, shop["tomato"], 1)
    body = checkout_body(shop, total=1, subtotal=1, delivery_fee=0)  # attempted tampering
    r = await client.post("/orders", json=body, headers={"X-Cart-Session": cart["session_id"]})
    assert r.json()["order"]["total"] == 4000.0


async def test_order_snapshot_survives_price_change(client, shop, admin):
    cart = await add_to_cart(client, shop["tomato"], 1)
    r = await client.post("/orders", json=checkout_body(shop), headers={"X-Cart-Session": cart["session_id"]})
    number = r.json()["order"]["order_number"]
    await client.patch(f"/admin/products/{shop['tomato']}", headers=admin["headers"], json={"price": 99})
    r = await client.post("/orders/track", json={"order_number": number, "phone": "0803 123 4567"})
    assert r.json()["items"][0]["unit_price"] == 2500.0


async def test_empty_cart_and_bad_inputs(client, shop):
    r = await client.post("/orders", json=checkout_body(shop))
    assert r.status_code == 400 and r.json()["error"]["code"] == "empty_cart"
    cart = await add_to_cart(client, shop["tomato"], 1)
    h = {"X-Cart-Session": cart["session_id"]}
    bad = checkout_body(shop)
    del bad["delivery_address"]
    assert (await client.post("/orders", json=bad, headers=h)).status_code == 422
    r = await client.post("/orders", json=checkout_body(shop, coupon_code="FAKE"), headers=h)
    assert r.json()["error"]["code"] == "invalid_coupon"
    r = await client.post("/orders", json=checkout_body(shop, payment_method="card"), headers=h)
    assert r.json()["error"]["code"] == "email_required"


async def test_stock_changes_between_cart_and_checkout(client, shop, admin):
    cart = await add_to_cart(client, shop["rice"], 4)
    await client.post(f"/admin/products/{shop['rice']}/stock", headers=admin["headers"], json={"set": 2})
    r = await client.post("/orders", json=checkout_body(shop), headers={"X-Cart-Session": cart["session_id"]})
    assert r.status_code == 400 and r.json()["error"]["code"] == "insufficient_stock"
    assert await stock_of(shop["rice"]) == 2  # nothing was taken


async def test_two_buyers_one_item_left_only_one_wins(client, shop):
    """Concurrency: both checkouts race for the last 5 bags of rice (each wants 5)."""
    carts = [await add_to_cart(client, shop["rice"], 5) for _ in range(2)]
    results = await asyncio.gather(*[
        client.post("/orders", json=checkout_body(shop), headers={"X-Cart-Session": c["session_id"]})
        for c in carts
    ])
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 400]
    assert await stock_of(shop["rice"]) == 0  # never negative / oversold


async def test_cancel_restores_stock_and_coupon(client, shop):
    cart = await add_to_cart(client, shop["tomato"], 4)
    r = await client.post("/orders", json=checkout_body(shop, coupon_code="SAVE10"),
                          headers={"X-Cart-Session": cart["session_id"]})
    number = r.json()["order"]["order_number"]
    assert await stock_of(shop["tomato"]) == 6
    # wrong phone can't cancel (and gets the same 404 as a missing order)
    assert (await client.post(f"/orders/{number}/cancel", json={"phone": "08000000000"})).status_code == 404
    r = await client.post(f"/orders/{number}/cancel", json={"phone": "08031234567", "reason": "Changed mind"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert await stock_of(shop["tomato"]) == 10
    async with AsyncSessionLocal() as s:
        assert (await s.get(Coupon, shop["coupon"])).used_count == 0
    r = await client.post(f"/orders/{number}/cancel", json={"phone": "08031234567"})
    assert r.status_code == 400  # already cancelled


async def test_logged_in_checkout_with_saved_address_and_order_history(client, shop, customer):
    h = customer["headers"]
    addr = (await client.post("/users/me/addresses", headers=h, json={
        "street": "5 Palm Ave", "city": "Town", "state": "State", "zone_id": str(shop["zone"])})).json()
    await add_to_cart(client, shop["tomato"], 1, headers=h)
    body = {"customer_name": "Ada", "customer_phone": "08031234567", "address_id": addr["id"],
            "payment_method": "transfer"}
    r = await client.post("/orders", json=body, headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["next_step"] == "bank_transfer"
    assert "5 Palm Ave" in r.json()["order"]["delivery_address"]
    mine = (await client.get("/orders", headers=h)).json()
    assert mine["total"] == 1
    number = mine["items"][0]["order_number"]
    assert (await client.get(f"/orders/{number}", headers=h)).status_code == 200
    other = await create_user(client, "other@example.com")
    assert (await client.get(f"/orders/{number}", headers=other["headers"])).status_code == 404
    assert (await client.get("/orders")).status_code == 401
