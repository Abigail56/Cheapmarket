"""Riders sign in through the shop, and admins manage them from the dashboard."""
from app.db.session import AsyncSessionLocal
from tests.conftest import create_user
from tests.test_rider_signup import apply


async def _rider(client, admin, email="ride@example.com", phone="08055555555"):
    r = await client.post("/admin/users", headers=admin["headers"], json={
        "full_name": "Sam Rider", "email": email, "phone": phone, "password": "Passw0rd!x", "role": "rider"})
    assert r.status_code == 201, r.text
    return r.json()


async def test_rider_gets_a_code_that_opens_the_rider_app(client, admin):
    await _rider(client, admin)
    tokens = (await client.post("/auth/login", json={"email": "ride@example.com", "password": "Passw0rd!x"})).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    code = (await client.post("/auth/handoff", headers=h)).json()["code"]
    r = await client.post("/auth/handoff/redeem", json={"code": code})
    assert r.status_code == 200
    me = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert (await client.get("/rider/deliveries", headers=me)).status_code == 200
    assert (await client.get("/admin/deliveries/board", headers=me)).status_code == 403


async def test_admin_adds_lists_suspends_and_restores_a_rider(client, admin):
    rider = await _rider(client, admin)
    h = admin["headers"]
    listed = (await client.get("/admin/riders", headers=h)).json()
    assert [x["email"] for x in listed] == ["ride@example.com"] and listed[0]["is_active"] is True

    assert (await client.patch(f"/admin/users/{rider['id']}", headers=h, json={"is_active": False})).status_code == 200
    r = await client.post("/auth/login", json={"email": "ride@example.com", "password": "Passw0rd!x"})
    assert r.status_code == 401
    assert (await client.patch(f"/admin/users/{rider['id']}", headers=h, json={"is_active": True})).status_code == 200
    r = await client.post("/auth/login", json={"email": "ride@example.com", "password": "Passw0rd!x"})
    assert r.status_code == 200


async def test_rider_with_a_delivery_in_progress_cannot_be_suspended(client, admin, shop):
    import uuid

    from app.models.delivery import Delivery, DeliveryStatus
    from app.models.order import Order
    from tests.conftest import add_to_cart, checkout_body

    rider = await _rider(client, admin)
    return_order = None
    from sqlmodel import select

    from app.models import Category, DeliveryZone, Product
    async with AsyncSessionLocal() as s:
        cat = Category(name="Veg", slug="veg")
        zone = DeliveryZone(name="Zone Z", delivery_fee=100)
        s.add_all([cat, zone])
        await s.flush()
        product = Product(category_id=cat.id, name="Yam", slug="yam", unit="1", price=100, stock_qty=5)
        s.add(product)
        await s.commit()
        pid, zid = product.id, zone.id
    cart = await add_to_cart(client, pid, 1)
    r = await client.post("/orders", json=checkout_body({"zone": zid}), headers={"X-Cart-Session": cart["session_id"]})
    return_order = r.json()["order"]["order_number"]
    async with AsyncSessionLocal() as s:
        order = (await s.exec(select(Order).where(Order.order_number == return_order))).one()
        s.add(Delivery(order_id=order.id, rider_id=uuid.UUID(rider["id"]), status=DeliveryStatus.EN_ROUTE))
        await s.commit()
    r = await client.patch(f"/admin/users/{rider['id']}", headers=admin["headers"], json={"is_active": False})
    assert r.status_code == 409 and r.json()["error"]["code"] == "rider_busy"
    assert (await client.get("/admin/riders", headers=admin["headers"])).json()[0]["active_deliveries"] == 1


async def test_unapproved_applicants_stay_out_of_the_list_and_cannot_be_switched_on(client, admin):
    await apply(client)
    h = admin["headers"]
    assert (await client.get("/admin/riders", headers=h)).json() == []
    users = (await client.get("/admin/users", headers=h, params={"role": "rider"})).json()["items"]
    r = await client.patch(f"/admin/users/{users[0]['id']}", headers=h, json={"is_active": True})
    assert r.status_code == 409


async def test_customers_cannot_see_riders(client):
    customer = await create_user(client, "shopper2@example.com")
    assert (await client.get("/admin/riders", headers=customer["headers"])).status_code == 403
