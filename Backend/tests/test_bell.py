"""The notification bell, plus the delivery proof the customer and admin can now see."""
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy import update

from app import worker
from app.db.session import AsyncSessionLocal
from app.models.delivery import Delivery
from app.models.notification import Notification
from app.models.user import UserRole
from app.services import events, inbox
from tests.conftest import add_to_cart, checkout_body, create_user, last_code, queued_messages
from tests.test_delivery_flow import (
    NEAR,
    assign,
    complete,
    pos,
    stream_events,
    to_arrived,
    tracking_token,
)


@pytest_asyncio.fixture
async def rider(client):
    return await create_user(client, "rider@example.com", UserRole.RIDER, phone="0809 000 1111",
                             name="Sam Rider")


async def place(client, shop, **over) -> dict:
    cart = await add_to_cart(client, shop["tomato"], 2)
    r = await client.post("/orders", json=checkout_body(shop, **over),
                          headers={"X-Cart-Session": cart["session_id"]})
    assert r.status_code == 201, r.text
    return r.json()["order"]


@pytest_asyncio.fixture
async def order(client, shop, admin):
    o = await place(client, shop, customer_email="ada@example.com")
    await client.patch(f"/admin/orders/{o['order_number']}/status", headers=admin["headers"],
                       json={"status": "confirmed"})
    return o


async def bell(client, user) -> dict:
    r = await client.get("/notifications", headers=user["headers"])
    assert r.status_code == 200, r.text
    return r.json()


async def test_a_new_order_rings_every_admin_but_nobody_else(client, shop, admin, rider, customer):
    second = await create_user(client, "second@example.com", UserRole.ADMIN, name="Second")
    o = await place(client, shop)
    for person in (admin, second):
        data = await bell(client, person)
        assert data["unread"] == 1
        [n] = data["items"]
        assert n["title"] == "New order" and n["order_number"] == o["order_number"]
        assert "₦6,500" in n["body"] and "pay on delivery" in n["body"]
    assert (await bell(client, rider))["unread"] == 0
    assert (await bell(client, customer))["unread"] == 0


async def test_the_bell_needs_a_login(client):
    assert (await client.get("/notifications")).status_code == 401


async def test_rider_bell_gets_their_offer_only(client, admin, order, rider):
    other = await create_user(client, "other@example.com", UserRole.RIDER, name="Other Rider")
    await assign(client, admin, order, rider)
    [n] = (await bell(client, rider))["items"]
    assert n["title"] == "New delivery for you" and n["order_number"] == order["order_number"]
    assert (await bell(client, other))["items"] == []


async def test_rider_is_told_when_the_order_is_cancelled(client, admin, order, rider):
    did = await assign(client, admin, order, rider)
    await client.post(f"/rider/deliveries/{did}/accept", headers=rider["headers"])
    await client.patch(f"/admin/orders/{order['order_number']}/status", headers=admin["headers"],
                       json={"status": "cancelled"})
    titles = [n["title"] for n in (await bell(client, rider))["items"]]
    assert "Order cancelled" in titles
    assert "Order cancelled" in [n["title"] for n in (await bell(client, admin))["items"]]


async def test_expired_offer_rings_both_sides(client, admin, order, rider):
    did = await assign(client, admin, order, rider)
    async with AsyncSessionLocal() as s:
        await s.exec(update(Delivery).where(Delivery.id == did).values(
            accept_deadline=datetime.now(UTC) - timedelta(seconds=1)))
        await s.commit()
    assert await worker.expire_offers_once() == 1
    assert "Offer ended" in [n["title"] for n in (await bell(client, rider))["items"]]
    titles = [n["title"] for n in (await bell(client, admin))["items"]]
    assert "No answer from rider" in titles


async def test_reassigning_tells_the_first_rider(client, admin, order, rider):
    other = await create_user(client, "other@example.com", UserRole.RIDER, name="Other Rider")
    await assign(client, admin, order, rider)
    await assign(client, admin, order, other)
    assert "Delivery reassigned" in [n["title"] for n in (await bell(client, rider))["items"]]


async def test_mark_read_and_mark_all(client, shop, admin):
    await place(client, shop)
    await place(client, shop)
    data = await bell(client, admin)
    assert data["unread"] == 2
    first = data["items"][0]["id"]
    assert (await client.post(f"/notifications/{first}/read", headers=admin["headers"])).status_code == 204
    assert (await bell(client, admin))["unread"] == 1
    assert (await client.post("/notifications/read-all", headers=admin["headers"])).status_code == 204
    assert (await bell(client, admin))["unread"] == 0


async def test_nobody_can_touch_someone_elses_notification(client, shop, admin, rider):
    await place(client, shop)
    nid = (await bell(client, admin))["items"][0]["id"]
    assert (await client.post(f"/notifications/{nid}/read", headers=rider["headers"])).status_code == 404
    assert (await bell(client, admin))["unread"] == 1


async def test_location_pings_never_reach_the_bell(client, admin, order, rider):
    did = await assign(client, admin, order, rider)
    await client.post(f"/rider/deliveries/{did}/accept", headers=rider["headers"])
    before = len((await bell(client, admin))["items"])
    await client.post("/rider/location", headers=rider["headers"], json=pos(NEAR))
    assert len((await bell(client, admin))["items"]) == before


async def test_a_bell_failure_never_fails_the_order(client, shop, admin, monkeypatch):
    class Broken:
        def __call__(self):
            raise RuntimeError("database hiccup")
    monkeypatch.setattr(inbox, "AsyncSessionLocal", Broken())
    await place(client, shop)  # still 201 (checked inside place)


async def test_old_notifications_are_cleared(client, shop, admin):
    await place(client, shop)
    async with AsyncSessionLocal() as s:
        await s.exec(update(Notification).values(created_at=datetime.now(UTC) - timedelta(days=31)))
        await s.commit()
    await place(client, shop)
    async with AsyncSessionLocal() as s:
        await inbox.prune(s)
    assert len((await bell(client, admin))["items"]) == 1


async def test_tracking_link_goes_out_when_the_rider_accepts(client, admin, order, rider):
    token = await tracking_token(order["order_number"])
    did = await assign(client, admin, order, rider)
    await client.post(f"/rider/deliveries/{did}/accept", headers=rider["headers"])
    msgs = [m for m in await queued_messages() if "Sam is your rider" in m["body"]]
    assert {m["channel"] for m in msgs} == {"sms", "email"}
    assert all(f"/track/{token}" in m["body"] for m in msgs)


async def test_customer_sees_code_state_then_the_photo_never_the_code(client, admin, order, rider):
    token = await tracking_token(order["order_number"])
    did = await to_arrived(client, admin, order, rider)
    assert (await client.get(f"/track/{token}")).json()["delivery"]["code_sent"] is False
    r = await client.post(f"/rider/deliveries/{did}/send-code", headers=rider["headers"], json=pos(NEAR))
    assert r.status_code == 200
    code = await last_code("+2348031234567")
    view = await client.get(f"/track/{token}")
    assert view.json()["delivery"]["code_sent"] is True and code not in view.text
    assert view.json()["delivery"]["proof_photo_url"] is None

    r = await complete(client, rider, did, code)
    assert r.status_code == 200, r.text
    d = (await client.get(f"/track/{token}")).json()["delivery"]
    assert d["proof_photo_url"] and "/proof/" in d["proof_photo_url"]
    assert d["code_sent"] is False

    board = (await client.get("/admin/deliveries/board", headers=admin["headers"])).json()
    [done] = board["delivered"]
    assert done["order_number"] == order["order_number"]
    assert done["proof_photo_url"] == d["proof_photo_url"] and done["rider_name"] == "Sam Rider"
    assert "Delivered" in [n["title"] for n in (await bell(client, admin))["items"]]


async def test_board_lists_new_orders_until_they_are_confirmed(client, shop, admin):
    cod = await place(client, shop)
    transfer = await place(client, shop, payment_method="transfer")
    h = admin["headers"]
    new = (await client.get("/admin/deliveries/board", headers=h)).json()["new_orders"]
    assert {o["order_number"] for o in new} == {cod["order_number"], transfer["order_number"]}

    # the two buttons on the board
    r = await client.patch(f"/admin/orders/{cod['order_number']}/status", headers=h, json={"status": "confirmed"})
    assert r.status_code == 200
    r = await client.post(f"/admin/orders/{transfer['order_number']}/mark-paid", headers=h,
                          json={"note": "Transfer seen, confirmed on the live board"})
    assert r.status_code == 200, r.text
    board = (await client.get("/admin/deliveries/board", headers=h)).json()
    assert board["new_orders"] == []
    assert {o["order_number"] for o in board["needs_rider"]} == {cod["order_number"], transfer["order_number"]}


async def test_every_delivery_stage_reaches_the_dashboard(client, admin, order, rider):
    """Each step publishes a named live event, and the board shows the new state."""
    did = await to_arrived(client, admin, order, rider)
    await client.post(f"/rider/deliveries/{did}/send-code", headers=rider["headers"], json=pos(NEAR))
    seen = {e: d for e, d in await stream_events(events.ADMIN)}
    for name in ("delivery.assigned", "delivery.accepted", "delivery.address_confirmed",
                 "delivery.started", "delivery.arrived", "delivery.code_sent"):
        assert seen[name]["order_number"] == order["order_number"], name
        assert seen[name]["rider_name"] == "Sam Rider", name
    [active] = (await client.get("/admin/deliveries/board", headers=admin["headers"])).json()["active"]
    d = active["delivery"]
    assert d["status"] == "arrived"
    assert all(d[k] for k in ("assigned_at", "accepted_at", "started_at", "arrived_at", "code_sent_at"))
    assert active["customer_phone"] == "+2348031234567"


async def test_rider_gets_the_customers_number_to_call_on_arrival(client, admin, order, rider):
    await to_arrived(client, admin, order, rider)
    [job] = (await client.get("/rider/deliveries", headers=rider["headers"])).json()
    assert job["status"] == "arrived" and job["customer_phone"] == "+2348031234567"


async def test_order_carries_its_tracking_token_for_the_shop(client, shop):
    o = await place(client, shop)
    assert o["tracking_token"] == await tracking_token(o["order_number"])
