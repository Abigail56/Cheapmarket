"""A delivery that fails on the road must stay visible and be recoverable."""
import pytest_asyncio

from app.models.user import UserRole
from tests.conftest import add_to_cart, checkout_body, create_user, queued_messages
from tests.test_delivery_flow import FAR, NEAR, PIN, assign, pos, to_arrived, tracking_token


@pytest_asyncio.fixture
async def rider(client):
    return await create_user(client, "rider@example.com", UserRole.RIDER, phone="0809 000 1111", name="Sam Rider")


@pytest_asyncio.fixture
async def rider2(client):
    return await create_user(client, "two@example.com", UserRole.RIDER, phone="0809 000 2222", name="Tolu Rider")


@pytest_asyncio.fixture
async def order(client, shop, admin):
    cart = await add_to_cart(client, shop["tomato"], 2)
    r = await client.post("/orders", json=checkout_body(shop), headers={"X-Cart-Session": cart["session_id"]})
    o = r.json()["order"]
    await client.patch(f"/admin/orders/{o['order_number']}/status", headers=admin["headers"], json={"status": "confirmed"})
    return o


async def fail(client, admin, order, rider) -> str:
    did = await to_arrived(client, admin, order, rider)
    r = await client.post(f"/rider/deliveries/{did}/fail", headers=rider["headers"], json={"reason": "No answer at the gate"})
    assert r.status_code == 200, r.text
    return did


async def board(client, admin) -> dict:
    return (await client.get("/admin/deliveries/board", headers=admin["headers"])).json()


async def test_failed_order_stays_on_the_board_and_customer_is_told(client, admin, order, rider):
    await fail(client, admin, order, rider)
    [waiting] = (await board(client, admin))["needs_rider"]
    assert waiting["order_number"] == order["order_number"]
    assert waiting["failure_reason"] == "No answer at the gate"
    assert any("couldn't complete the delivery" in m["body"] for m in await queued_messages())


async def test_second_rider_can_finish_a_failed_delivery(client, admin, order, rider, rider2):
    token = await tracking_token(order["order_number"])
    await fail(client, admin, order, rider)
    did = await assign(client, admin, order, rider2)
    b = await board(client, admin)
    assert b["needs_rider"] == [] and b["active"][0]["rider_name"] == "Tolu Rider"
    d = b["active"][0]["delivery"]
    assert d["started_at"] is None and d["arrived_at"] is None and d["code_sent_at"] is None
    assert (await client.get("/rider/deliveries", headers=rider["headers"])).json() == []

    h = rider2["headers"]
    for step, body in (("accept", None), ("confirm-address", pos(PIN)), ("start", None), ("arrive", pos(NEAR))):
        r = await client.post(f"/rider/deliveries/{did}/{step}", headers=h, json=body)
        assert r.status_code == 200, (step, r.text)
    assert r.json()["order_status"] == "out_for_delivery"
    assert (await client.get(f"/track/{token}")).json()["delivery"]["rider_name"] == "Tolu"


async def test_waived_location_check_does_not_carry_to_the_next_rider(client, admin, order, rider, rider2):
    did = await to_arrived(client, admin, order, rider)
    r = await client.post(f"/admin/deliveries/{did}/override-location", headers=admin["headers"], json={"reason": "GPS is off"})
    assert r.status_code == 200
    await client.post(f"/rider/deliveries/{did}/fail", headers=rider["headers"], json={"reason": "Bike broke down"})
    await assign(client, admin, order, rider2)
    h = rider2["headers"]
    await client.post(f"/rider/deliveries/{did}/accept", headers=h)
    await client.post(f"/rider/deliveries/{did}/confirm-address", headers=h, json=pos(PIN))
    await client.post(f"/rider/deliveries/{did}/start", headers=h)
    r = await client.post(f"/rider/deliveries/{did}/arrive", headers=h, json=pos(FAR))
    assert r.status_code == 400 and r.json()["error"]["code"] == "too_far"


async def test_declined_retry_comes_back_to_the_board(client, admin, order, rider, rider2):
    did = await fail(client, admin, order, rider)
    await assign(client, admin, order, rider2)
    await client.post(f"/rider/deliveries/{did}/decline", headers=rider2["headers"], json={})
    assert [o["order_number"] for o in (await board(client, admin))["needs_rider"]] == [order["order_number"]]


async def test_failed_order_can_be_cancelled_and_leaves_the_board(client, admin, order, rider):
    await fail(client, admin, order, rider)
    r = await client.patch(f"/admin/orders/{order['order_number']}/status", headers=admin["headers"], json={"status": "cancelled"})
    assert r.status_code == 200, r.text
    assert (await board(client, admin))["needs_rider"] == []


async def test_order_on_the_road_cannot_be_taken_from_its_rider(client, admin, order, rider, rider2):
    await to_arrived(client, admin, order, rider)
    r = await client.post(f"/admin/orders/{order['order_number']}/assign-rider", headers=admin["headers"], json={"rider_id": rider2["id"]})
    assert r.status_code == 400


async def test_customer_can_fix_the_address_after_a_failed_try(client, admin, order, rider):
    token = await tracking_token(order["order_number"])
    await fail(client, admin, order, rider)
    r = await client.post(f"/track/{token}/address", json={"landmark": "The other blue gate"})
    assert r.status_code == 200 and r.json()["delivery"]["landmark"] == "The other blue gate"


async def test_shop_opened_by_ip_may_call_the_api_locally(client):
    for origin, allowed in (("http://192.168.2.137:3020", True), ("http://127.0.0.1:3020", True),
                            ("http://evil.example.com", False)):
        r = await client.options("/products", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})
        assert (r.headers.get("access-control-allow-origin") == origin) is allowed, origin
