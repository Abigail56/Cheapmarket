from tests.conftest import add_to_cart


async def test_guest_cart_flow(client, shop):
    cart = await add_to_cart(client, shop["tomato"], 2)
    sid = cart["session_id"]
    assert sid and cart["item_count"] == 2 and cart["subtotal"] == 5000.0

    cart = await add_to_cart(client, shop["tomato"], 1, session_id=sid)  # same cart, qty adds up
    assert cart["item_count"] == 3
    cart = await add_to_cart(client, shop["rice"], 1, session_id=sid)
    assert cart["subtotal"] == 17000.0 and len(cart["items"]) == 2

    h = {"X-Cart-Session": sid}
    r = await client.put(f"/cart/items/{shop['tomato']}", json={"quantity": 1}, headers=h)
    assert r.json()["subtotal"] == 12000.0
    r = await client.delete(f"/cart/items/{shop['rice']}", headers=h)
    assert r.json()["item_count"] == 1
    r = await client.delete("/cart", headers=h)
    assert r.json()["items"] == []


async def test_session_header_is_returned(client, shop):
    r = await client.post("/cart/items", json={"product_id": str(shop["tomato"]), "quantity": 1})
    assert r.headers["x-cart-session"] == r.json()["session_id"]


async def test_cannot_exceed_stock_or_add_unavailable(client, shop):
    r = await client.post("/cart/items", json={"product_id": str(shop["rice"]), "quantity": 6})
    assert r.status_code == 400 and r.json()["error"]["code"] == "insufficient_stock"
    r = await client.post("/cart/items", json={"product_id": str(shop["mango"]), "quantity": 1})
    assert r.status_code == 400  # out of stock
    r = await client.post("/cart/items", json={"product_id": "00000000-0000-0000-0000-000000000000"})
    assert r.status_code == 404


async def test_empty_cart_when_no_session(client):
    r = await client.get("/cart")
    assert r.json()["items"] == [] and r.json()["session_id"] is None


async def test_user_cart_persists_and_merges_guest_cart(client, shop, customer):
    guest = await add_to_cart(client, shop["tomato"], 3)
    await add_to_cart(client, shop["tomato"], 2, headers=customer["headers"])
    r = await client.post("/cart/merge", json={"session_id": guest["session_id"]},
                          headers=customer["headers"])
    assert r.status_code == 200
    assert r.json()["item_count"] == 5
    # guest cart is gone, user cart persists across requests
    assert (await client.get("/cart", headers={"X-Cart-Session": guest["session_id"]})).json()["items"] == []
    assert (await client.get("/cart", headers=customer["headers"])).json()["item_count"] == 5


async def test_merge_caps_at_stock(client, shop, customer):
    guest = await add_to_cart(client, shop["rice"], 4)
    await add_to_cart(client, shop["rice"], 3, headers=customer["headers"])
    r = (await client.post("/cart/merge", json={"session_id": guest["session_id"]},
                           headers=customer["headers"])).json()
    assert r["item_count"] == 5 and r["notices"]
