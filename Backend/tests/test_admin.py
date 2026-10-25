
from app.db.session import AsyncSessionLocal
from app.models import Product, UserRole
from tests.conftest import add_to_cart, checkout_body, create_user


async def place(client, shop, qty=1, **over) -> dict:
    cart = await add_to_cart(client, shop["tomato"], qty)
    r = await client.post("/orders", json=checkout_body(shop, **over),
                          headers={"X-Cart-Session": cart["session_id"]})
    assert r.status_code == 201, r.text
    return r.json()["order"]


async def test_admin_routes_are_protected(client, shop, customer):
    for method, url in [("get", "/admin/orders"), ("get", "/admin/dashboard"),
                        ("post", "/admin/products"), ("get", "/admin/coupons"),
                        ("get", "/admin/users")]:
        assert (await getattr(client, method)(url)).status_code == 401
        assert (await getattr(client, method)(url, headers=customer["headers"])).status_code == 403


async def test_product_and_category_management(client, admin, shop):
    h = admin["headers"]
    cat = (await client.post("/admin/categories", headers=h, json={"name": "Spices & Herbs"})).json()
    assert cat["slug"] == "spices-herbs"
    again = (await client.post("/admin/categories", headers=h, json={"name": "Spices & Herbs"})).json()
    assert again["slug"] == "spices-herbs-2"  # unique slugs

    p = await client.post("/admin/products", headers=h, json={
        "category_id": cat["id"], "name": "Ginger", "unit": "500 g", "price": 800, "stock_qty": 15})
    assert p.status_code == 201 and p.json()["slug"] == "ginger" and p.json()["stock_qty"] == 15
    pid = p.json()["id"]
    assert (await client.get("/products/ginger")).status_code == 200

    assert (await client.post(f"/admin/products/{pid}/stock", headers=h, json={"delta": -20})).status_code == 400
    r = await client.post(f"/admin/products/{pid}/stock", headers=h, json={"delta": 5})
    assert r.json()["stock_qty"] == 20
    assert (await client.post(f"/admin/products/{pid}/stock", headers=h, json={})).status_code == 400

    bad = await client.post("/admin/products", headers=h, json={
        "category_id": cat["id"], "name": "Bad", "unit": "x", "price": 100, "compare_at_price": 50})
    assert bad.status_code == 400

    assert (await client.delete(f"/admin/categories/{cat['id']}", headers=h)).status_code == 409  # has products
    assert (await client.delete(f"/admin/products/{pid}", headers=h)).status_code == 204
    assert (await client.get("/products/ginger")).status_code == 404       # hidden from shoppers
    assert (await client.get(f"/admin/products/{pid}", headers=h)).json()["is_active"] is False


async def test_low_stock_filter(client, admin, shop):
    r = (await client.get("/admin/products", headers=admin["headers"], params={"low_stock": True})).json()
    assert {p["slug"] for p in r["items"]} == {"tomatoes", "rice", "mango"}  # all <= threshold (10)


async def test_order_lifecycle_cod(client, shop, admin):
    h = admin["headers"]
    order = await place(client, shop)
    n = order["order_number"]
    s = lambda status: client.patch(f"/admin/orders/{n}/status", headers=h, json={"status": status})

    assert (await s("delivered")).status_code == 400  # can't skip steps
    for status in ("confirmed", "packed", "out_for_delivery", "delivered"):
        r = await s(status)
        assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "delivered"
    assert d["payment_status"] == "paid"  # cash collected on delivery
    assert [x["status"] for x in d["history"]] == ["pending", "confirmed", "packed", "out_for_delivery", "delivered"]
    assert (await s("cancelled")).status_code == 400  # terminal


async def test_unpaid_card_or_transfer_order_cannot_be_confirmed(client, shop, admin):
    order = await place(client, shop, payment_method="transfer")
    n = order["order_number"]
    r = await client.patch(f"/admin/orders/{n}/status", headers=admin["headers"], json={"status": "confirmed"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "unpaid_order"
    r = await client.post(f"/admin/orders/{n}/mark-paid", headers=admin["headers"], json={"note": "Alat ref 123"})
    assert r.status_code == 200
    assert r.json()["payment_status"] == "paid" and r.json()["status"] == "confirmed"
    assert r.json()["payments"][0]["status"] == "success"
    assert (await client.post(f"/admin/orders/{n}/mark-paid", headers=admin["headers"], json={})).status_code == 400


async def test_admin_cancel_restores_stock(client, shop, admin):
    order = await place(client, shop, qty=3)
    r = await client.patch(f"/admin/orders/{order['order_number']}/status",
                           headers=admin["headers"], json={"status": "cancelled", "note": "Out of supply"})
    assert r.status_code == 200
    async with AsyncSessionLocal() as s:
        assert (await s.get(Product, shop["tomato"])).stock_qty == 10


async def test_order_search_and_filters(client, shop, admin):
    await place(client, shop, customer_name="Chidi Okeke")
    await place(client, shop, customer_name="Bola Ade")
    h = admin["headers"]
    assert (await client.get("/admin/orders", headers=h)).json()["total"] == 2
    r = (await client.get("/admin/orders", headers=h, params={"q": "chidi"})).json()
    assert r["total"] == 1 and r["items"][0]["customer_name"] == "Chidi Okeke"
    assert (await client.get("/admin/orders", headers=h, params={"status": "delivered"})).json()["total"] == 0
    assert (await client.get("/admin/orders/CMD-NOPE", headers=h)).status_code == 404


async def test_assign_rider_rules(client, shop, admin):
    """The full rider journey is in test_delivery_flow.py; this covers who can be assigned when."""
    rider = await create_user(client, "rider@example.com", UserRole.RIDER, name="Sam Rider")
    order = await place(client, shop)
    n, h = order["order_number"], admin["headers"]

    r = await client.post(f"/admin/orders/{n}/assign-rider", headers=h, json={"rider_id": rider["id"]})
    assert r.status_code == 400  # still pending
    await client.patch(f"/admin/orders/{n}/status", headers=h, json={"status": "confirmed"})
    not_rider = await client.post(f"/admin/orders/{n}/assign-rider", headers=h, json={"rider_id": admin["id"]})
    assert not_rider.status_code == 400
    r = await client.post(f"/admin/orders/{n}/assign-rider", headers=h, json={"rider_id": rider["id"]})
    assert r.status_code == 200
    assert r.json()["delivery"]["rider_id"] == rider["id"] and r.json()["delivery"]["status"] == "assigned"
    assert "code_hash" not in r.json()["delivery"]


async def test_zones_coupons_users_and_dashboard(client, shop, admin, customer):
    h = admin["headers"]
    z = await client.post("/admin/zones", headers=h, json={"name": "Zone B", "delivery_fee": 2500})
    assert z.status_code == 201
    assert (await client.post("/admin/zones", headers=h, json={"name": "Zone B", "delivery_fee": 1})).status_code == 409

    c = await client.post("/admin/coupons", headers=h, json={
        "code": "eid20", "discount_type": "fixed", "value": 2000, "min_order": 5000, "max_uses": 1})
    assert c.status_code == 201 and c.json()["code"] == "EID20"
    assert (await client.post("/admin/coupons", headers=h, json={
        "code": "EID20", "discount_type": "fixed", "value": 5})).status_code == 409
    assert (await client.post("/admin/coupons", headers=h, json={
        "code": "BAD", "discount_type": "percent", "value": 150})).status_code == 422

    # single-use coupon is really single-use
    o1 = await place(client, shop, qty=3, coupon_code="EID20")
    assert o1["discount_total"] == 2000.0
    cart = await add_to_cart(client, shop["tomato"], 3)
    r = await client.post("/orders", json=checkout_body(shop, coupon_code="EID20"),
                          headers={"X-Cart-Session": cart["session_id"]})
    assert r.json()["error"]["code"] == "coupon_exhausted"

    # role management
    r = await client.patch(f"/admin/users/{customer['id']}", headers=h, json={"role": "rider"})
    assert r.json()["role"] == "rider"
    assert (await client.patch(f"/admin/users/{admin['id']}", headers=h, json={"is_active": False})).status_code == 400
    await client.patch(f"/admin/users/{customer['id']}", headers=h, json={"is_active": False})
    r = await client.post("/auth/login", json={"email": customer["email"], "password": customer["password"]})
    assert r.status_code == 401 and r.json()["error"]["code"] == "account_disabled"
    assert (await client.get("/users/me", headers=customer["headers"])).status_code == 401

    d = (await client.get("/admin/dashboard", headers=h)).json()
    assert d["orders_today"] == 1 and d["orders_by_status"]["pending"] == 1
    assert d["revenue_total"] == 0  # nothing paid yet
    assert any(p["name"] == "Rice" for p in d["low_stock"])


async def test_health(client):
    r = await client.get("http://test/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
