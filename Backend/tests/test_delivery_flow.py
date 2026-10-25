import json
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy import update

from app import worker
from app.core.config import settings
from app.db.redis import redis_client
from app.db.session import AsyncSessionLocal
from app.models.delivery import Delivery
from app.models.user import UserRole
from app.services import events
from tests.conftest import add_to_cart, checkout_body, create_user, last_code, queued_messages
from tests.test_uploads import PNG

PIN = (6.5244, 3.3792)          # the customer's door (Lagos)
NEAR = (6.5250, 3.3795)         # ~75 m away
FAR = (6.6000, 3.3800)          # ~8.4 km away
CUSTOMER_PHONE = "+2348031234567"


def pos(point):
    return {"latitude": point[0], "longitude": point[1]}


@pytest_asyncio.fixture
async def rider(client):
    return await create_user(client, "rider@example.com", UserRole.RIDER, phone="0809 000 1111",
                             name="Sam Rider")


@pytest_asyncio.fixture
async def order(client, shop, admin):
    """A confirmed COD order (with email), ready for a rider."""
    cart = await add_to_cart(client, shop["tomato"], 2)
    r = await client.post("/orders", json=checkout_body(shop, customer_email="ada@example.com"),
                          headers={"X-Cart-Session": cart["session_id"]})
    o = r.json()["order"]
    await client.patch(f"/admin/orders/{o['order_number']}/status", headers=admin["headers"],
                       json={"status": "confirmed"})
    return o


async def tracking_token(order_number: str) -> str:
    from sqlmodel import select

    from app.models.order import Order
    async with AsyncSessionLocal() as s:
        return (await s.exec(select(Order.tracking_token).where(Order.order_number == order_number))).one()


async def assign(client, admin, order, rider) -> str:
    r = await client.post(f"/admin/orders/{order['order_number']}/assign-rider",
                          headers=admin["headers"], json={"rider_id": rider["id"]})
    assert r.status_code == 200, r.text
    return r.json()["delivery"]["id"]


async def to_arrived(client, admin, order, rider) -> str:
    """assign -> accept -> confirm pin -> start -> arrive"""
    did = await assign(client, admin, order, rider)
    h = rider["headers"]
    for step, body in (("accept", None), ("confirm-address", {**pos(PIN), "landmark": "Blue gate"}),
                       ("start", None), ("arrive", pos(NEAR))):
        r = await client.post(f"/rider/deliveries/{did}/{step}", headers=h, json=body)
        assert r.status_code == 200, (step, r.text)
    return did


async def complete(client, rider, did, code, point=NEAR, photo=PNG):
    return await client.post(f"/rider/deliveries/{did}/complete", headers=rider["headers"],
                             data={"code": code, "latitude": point[0], "longitude": point[1]},
                             files={"photo": ("door.png", photo, "image/png")})


async def stream_events(key: str) -> list[tuple[str, dict]]:
    return [(f["event"], json.loads(f["data"])) for _, f in await redis_client.xrange(key)]


# ------------------------------------------------------------------- happy path
async def test_full_delivery_journey(client, admin, order, rider):
    h, n = rider["headers"], order["order_number"]
    token = await tracking_token(n)

    # the customer's very first SMS carries the tracking link
    first = (await queued_messages())[0]
    assert f"/track/{token}" in first["body"]

    did = await assign(client, admin, order, rider)
    # rider is texted and sees the offer (no customer phone before accepting)
    assert any(m["to"] == "+2348090001111" and n in m["body"] for m in await queued_messages())
    [job] = (await client.get("/rider/deliveries", headers=h)).json()
    assert job["status"] == "assigned" and job["customer_phone"] is None
    assert job["accept_deadline"] and job["collect_cash"] == 6500.0

    job = (await client.post(f"/rider/deliveries/{did}/accept", headers=h)).json()
    assert job["status"] == "accepted" and job["customer_phone"] == CUSTOMER_PHONE
    assert any("Sam is your rider" in m["body"] for m in await queued_messages())

    # can't set off before the address is confirmed
    r = await client.post(f"/rider/deliveries/{did}/start", headers=h)
    assert r.status_code == 400 and r.json()["error"]["code"] == "address_not_confirmed"
    job = (await client.post(f"/rider/deliveries/{did}/confirm-address", headers=h,
                             json={**pos(PIN), "landmark": "Blue gate", "notes": "Call at gate"})).json()
    assert job["address_confirmed"] and job["landmark"] == "Blue gate"

    job = (await client.post(f"/rider/deliveries/{did}/start", headers=h)).json()
    assert job["status"] == "en_route" and job["order_status"] == "out_for_delivery"

    # live position: on the customer's page with an ETA
    assert (await client.post("/rider/location", headers=h, json=pos(FAR))).status_code == 204
    t = (await client.get(f"/track/{token}")).json()
    assert t["status"] == "out_for_delivery" and t["delivery"]["rider_name"] == "Sam"
    assert t["delivery"]["rider_position"]["latitude"] == FAR[0]
    assert t["delivery"]["eta_minutes"] >= 1 and t["can_edit_address"] is False

    # can't arrive from 8 km away
    r = await client.post(f"/rider/deliveries/{did}/arrive", headers=h, json=pos(FAR))
    assert r.status_code == 400 and r.json()["error"]["code"] == "too_far"
    assert (await client.post(f"/rider/deliveries/{did}/arrive", headers=h, json=pos(NEAR))).json()["status"] == "arrived"

    sent = await client.post(f"/rider/deliveries/{did}/send-code", headers=h, json=pos(NEAR))
    assert sent.status_code == 200 and sent.json() == {"sent": True, "expires_in_minutes": 10}
    code = await last_code(CUSTOMER_PHONE)
    assert code not in sent.text  # the rider never gets it from the API

    job = (await complete(client, rider, did, code)).json()
    assert job["status"] == "delivered" and job["order_status"] == "delivered"

    detail = (await client.get(f"/admin/orders/{n}", headers=admin["headers"])).json()
    assert detail["payment_status"] == "paid"  # COD collected
    d = detail["delivery"]
    assert d["proof_photo_url"].startswith(settings.MEDIA_BASE_URL + "/proof/")
    assert (d["delivered_latitude"], d["delivered_longitude"]) == NEAR
    assert "code_hash" not in d
    # the code never appears in any live event
    for key in (events.ADMIN, events.track_stream(order["id"]), events.rider_stream(rider["id"])):
        assert code not in json.dumps(await stream_events(key))
    admin_events = [e for e, _ in await stream_events(events.ADMIN)]
    for expected in ("order.placed", "delivery.assigned", "delivery.accepted", "delivery.started",
                     "rider.location", "delivery.arrived", "delivery.code_sent", "delivery.delivered"):
        assert expected in admin_events, expected


# ------------------------------------------------------------ the code can't be faked
async def test_wrong_codes_lock_and_alert_admin(client, admin, order, rider):
    did = await to_arrived(client, admin, order, rider)
    await client.post(f"/rider/deliveries/{did}/send-code", headers=rider["headers"], json=pos(NEAR))
    code = await last_code(CUSTOMER_PHONE)
    wrong = "000000" if code != "000000" else "111111"
    for i in range(settings.DELIVERY_CODE_MAX_ATTEMPTS):
        r = await complete(client, rider, did, wrong)
        assert r.status_code == 400 and r.json()["error"]["code"] == "wrong_code"
    r = await complete(client, rider, did, code)  # even the right code is now dead
    assert r.status_code == 400 and r.json()["error"]["code"] == "code_locked"
    wrong_alerts = [d for e, d in await stream_events(events.ADMIN) if e == "delivery.code_wrong"]
    assert len(wrong_alerts) == settings.DELIVERY_CODE_MAX_ATTEMPTS


async def test_code_from_another_delivery_does_not_work(client, shop, admin, order, rider):
    # a second order to a different customer, with a second rider, both at their doors
    cart = await add_to_cart(client, shop["rice"], 1)
    r = await client.post("/orders", json=checkout_body(shop, customer_phone="08035550000"),
                          headers={"X-Cart-Session": cart["session_id"]})
    order2 = r.json()["order"]
    await client.patch(f"/admin/orders/{order2['order_number']}/status", headers=admin["headers"],
                       json={"status": "confirmed"})
    rider2 = await create_user(client, "rider2@example.com", UserRole.RIDER)
    did1 = await to_arrived(client, admin, order, rider)
    did2 = await to_arrived(client, admin, order2, rider2)
    await client.post(f"/rider/deliveries/{did1}/send-code", headers=rider["headers"], json=pos(NEAR))
    await client.post(f"/rider/deliveries/{did2}/send-code", headers=rider2["headers"], json=pos(NEAR))
    code1 = await last_code(CUSTOMER_PHONE)
    code2 = await last_code("+2348035550000")
    if code1 == code2:  # 1-in-a-million: nothing to prove this run
        return
    r = await complete(client, rider2, did2, code1)  # rider 2 tries customer 1's code
    assert r.status_code == 400 and r.json()["error"]["code"] == "wrong_code"
    assert (await complete(client, rider2, did2, code2)).status_code == 200


async def test_code_expires(client, admin, order, rider):
    did = await to_arrived(client, admin, order, rider)
    await client.post(f"/rider/deliveries/{did}/send-code", headers=rider["headers"], json=pos(NEAR))
    code = await last_code(CUSTOMER_PHONE)
    async with AsyncSessionLocal() as s:
        await s.exec(update(Delivery).where(Delivery.id == did)
                     .values(code_expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        await s.commit()
    r = await complete(client, rider, did, code)
    assert r.status_code == 400 and r.json()["error"]["code"] == "code_expired"


async def test_send_code_and_complete_need_the_rider_at_the_door(client, admin, order, rider):
    did = await to_arrived(client, admin, order, rider)
    r = await client.post(f"/rider/deliveries/{did}/send-code", headers=rider["headers"], json=pos(FAR))
    assert r.status_code == 400 and r.json()["error"]["code"] == "too_far"
    await client.post(f"/rider/deliveries/{did}/send-code", headers=rider["headers"], json=pos(NEAR))
    code = await last_code(CUSTOMER_PHONE)
    r = await complete(client, rider, did, code, point=FAR)
    assert r.status_code == 400 and r.json()["error"]["code"] == "too_far"
    # resending straight away is throttled
    r = await client.post(f"/rider/deliveries/{did}/send-code", headers=rider["headers"], json=pos(NEAR))
    assert r.status_code == 400 and r.json()["error"]["code"] == "code_recently_sent"


async def test_photo_is_required_and_must_be_an_image(client, admin, order, rider):
    did = await to_arrived(client, admin, order, rider)
    await client.post(f"/rider/deliveries/{did}/send-code", headers=rider["headers"], json=pos(NEAR))
    code = await last_code(CUSTOMER_PHONE)
    no_photo = await client.post(f"/rider/deliveries/{did}/complete", headers=rider["headers"],
                                 data={"code": code, "latitude": NEAR[0], "longitude": NEAR[1]})
    assert no_photo.status_code == 422
    fake = await complete(client, rider, did, code, photo=b"not a picture")
    assert fake.status_code == 400 and fake.json()["error"]["code"] == "unsupported_image"


async def test_admin_can_waive_the_location_check(client, admin, order, rider):
    did = await assign(client, admin, order, rider)
    h = rider["headers"]
    await client.post(f"/rider/deliveries/{did}/accept", headers=h)
    await client.post(f"/rider/deliveries/{did}/confirm-address", headers=h, json=pos(PIN))
    await client.post(f"/rider/deliveries/{did}/start", headers=h)
    assert (await client.post(f"/rider/deliveries/{did}/arrive", headers=h, json=pos(FAR))).status_code == 400
    r = await client.post(f"/admin/deliveries/{did}/override-location", headers=admin["headers"],
                          json={"reason": "Called customer, rider is at the gate; GPS drifting"})
    assert r.status_code == 200 and r.json()["geofence_override_at"]
    assert (await client.post(f"/rider/deliveries/{did}/arrive", headers=h, json=pos(FAR))).status_code == 200
    logs = (await client.get("/admin/audit-logs", headers=admin["headers"],
                             params={"entity_type": "delivery"})).json()["items"]
    assert logs[0]["action"] == "delivery.geofence_override"


# ---------------------------------------------------------------- accept / decline
async def test_steps_must_happen_in_order_and_only_by_the_assigned_rider(client, admin, order, rider):
    did = await assign(client, admin, order, rider)
    other = await create_user(client, "rider2@example.com", UserRole.RIDER)
    assert (await client.post(f"/rider/deliveries/{did}/accept", headers=other["headers"])).status_code == 404
    r = await client.post(f"/rider/deliveries/{did}/arrive", headers=rider["headers"], json=pos(NEAR))
    assert r.status_code == 409 and r.json()["error"]["code"] == "wrong_delivery_state"
    customer = await create_user(client, "c2@example.com")
    assert (await client.get("/rider/deliveries", headers=customer["headers"])).status_code == 403


async def test_decline_sends_it_back_to_the_admin(client, admin, order, rider):
    did = await assign(client, admin, order, rider)
    r = await client.post(f"/rider/deliveries/{did}/decline", headers=rider["headers"],
                          json={"reason": "Bike puncture"})
    assert r.status_code == 204
    assert (await client.get("/rider/deliveries", headers=rider["headers"])).json() == []
    board = (await client.get("/admin/deliveries/board", headers=admin["headers"])).json()
    assert [o["order_number"] for o in board["needs_rider"]] == [order["order_number"]]
    declined = [d for e, d in await stream_events(events.ADMIN) if e == "delivery.declined"]
    assert declined[0]["reason"] == "Bike puncture"
    # and it can be offered to someone else
    rider2 = await create_user(client, "rider2@example.com", UserRole.RIDER)
    await assign(client, admin, order, rider2)


async def test_unanswered_offer_expires(client, admin, order, rider):
    did = await assign(client, admin, order, rider)
    async with AsyncSessionLocal() as s:
        await s.exec(update(Delivery).where(Delivery.id == did)
                     .values(accept_deadline=datetime.now(UTC) - timedelta(seconds=1)))
        await s.commit()
    r = await client.post(f"/rider/deliveries/{did}/accept", headers=rider["headers"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "offer_expired"
    assert await worker.expire_offers_once() == 1
    board = (await client.get("/admin/deliveries/board", headers=admin["headers"])).json()
    assert board["needs_rider"][0]["order_number"] == order["order_number"]
    assert "delivery.expired" in [e for e, _ in await stream_events(events.ADMIN)]
    assert "delivery.expired" in [e for e, _ in await stream_events(events.rider_stream(rider["id"]))]


async def test_reassigning_tells_the_first_rider(client, admin, order, rider):
    did = await assign(client, admin, order, rider)
    rider2 = await create_user(client, "rider2@example.com", UserRole.RIDER)
    await assign(client, admin, order, rider2)
    assert "delivery.unassigned" in [e for e, _ in await stream_events(events.rider_stream(rider["id"]))]
    assert (await client.post(f"/rider/deliveries/{did}/accept", headers=rider["headers"])).status_code == 404


async def test_cancelling_the_order_stops_the_rider(client, admin, order, rider):
    did = await assign(client, admin, order, rider)
    await client.post(f"/rider/deliveries/{did}/accept", headers=rider["headers"])
    await client.patch(f"/admin/orders/{order['order_number']}/status", headers=admin["headers"],
                       json={"status": "cancelled"})
    detail = (await client.get(f"/admin/orders/{order['order_number']}", headers=admin["headers"])).json()
    assert detail["delivery"]["status"] == "cancelled"
    assert "order.status_changed" in [e for e, _ in await stream_events(events.rider_stream(rider["id"]))]


# -------------------------------------------------------------------- tracking page
async def test_tracking_hides_the_rider_until_on_the_way(client, admin, order, rider):
    token = await tracking_token(order["order_number"])
    t = (await client.get(f"/track/{token}")).json()
    assert t["delivery"] is None and t["can_edit_address"] is True
    assert [s["status"] for s in t["timeline"]] == ["pending", "confirmed"]
    did = await assign(client, admin, order, rider)
    await client.post(f"/rider/deliveries/{did}/accept", headers=rider["headers"])
    await client.post("/rider/location", headers=rider["headers"], json=pos(FAR))
    t = (await client.get(f"/track/{token}")).json()
    assert t["delivery"]["rider_name"] == "Sam"
    assert t["delivery"]["rider_position"] is None and t["delivery"]["rider_phone"] is None


async def test_customer_corrects_address_and_rider_must_reconfirm(client, admin, order, rider):
    token = await tracking_token(order["order_number"])
    # before any rider: the correction is kept for whoever is assigned
    r = await client.post(f"/track/{token}/address", json={**pos(PIN), "landmark": "Opposite church"})
    assert r.status_code == 200 and r.json()["delivery"]["landmark"] == "Opposite church"
    did = await assign(client, admin, order, rider)
    h = rider["headers"]
    job = (await client.post(f"/rider/deliveries/{did}/accept", headers=h)).json()
    assert job["landmark"] == "Opposite church" and job["dropoff_latitude"] == PIN[0]
    await client.post(f"/rider/deliveries/{did}/confirm-address", headers=h, json=pos(PIN))
    # customer changes it again: the rider's confirmation is cleared, and they're told live
    await client.post(f"/track/{token}/address", json={"notes": "Ring twice"})
    [job] = (await client.get("/rider/deliveries", headers=h)).json()
    assert job["address_confirmed"] is False and job["customer_changed_address"] is True
    assert "delivery.address_corrected" in [e for e, _ in await stream_events(events.rider_stream(rider["id"]))]
    assert (await client.post(f"/rider/deliveries/{did}/start", headers=h)).status_code == 400
    await client.post(f"/rider/deliveries/{did}/confirm-address", headers=h, json=pos(PIN))
    await client.post(f"/rider/deliveries/{did}/start", headers=h)
    # once the rider has left, the address is locked
    r = await client.post(f"/track/{token}/address", json={"landmark": "Somewhere else"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "rider_on_the_way"


async def test_unknown_tracking_link(client):
    assert (await client.get("/track/not-a-real-token")).status_code == 404


async def test_admin_board(client, admin, order, rider):
    board = (await client.get("/admin/deliveries/board", headers=admin["headers"])).json()
    assert board["needs_rider"][0]["order_number"] == order["order_number"]
    assert board["riders"][0]["name"] == "Sam Rider" and board["riders"][0]["busy"] is False
    did = await assign(client, admin, order, rider)
    board = (await client.get("/admin/deliveries/board", headers=admin["headers"])).json()
    assert board["needs_rider"] == [] and board["active"][0]["delivery"]["id"] == did
    assert board["riders"][0]["busy"] is True


# ----------------------------------------------------------------- live event stream
async def test_event_stream_yields_published_events():
    from app.services.events import publish, stream

    class FakeRequest:
        calls = 0

        async def is_disconnected(self):
            self.calls += 1
            return self.calls > 2

    req = FakeRequest()
    gen = stream(req, "events:test")
    assert await gen.__anext__() == "retry: 3000\n\n"
    padding = await gen.__anext__()  # opens buffering proxies; browsers ignore comments
    assert padding.startswith(":") and len(padding) > 2000
    await publish(["events:test"], "delivery.arrived", {"delivery_id": "abc"})
    chunk = await gen.__anext__()
    assert "event: delivery.arrived" in chunk and '"delivery_id": "abc"' in chunk
    await gen.aclose()


# ------------------------------------------------------------------------ pages
async def test_pages_are_served(client):
    base = "http://test"
    r = await client.get(f"{base}/rider/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert 'rel="manifest"' in r.text and r.headers["x-frame-options"] == "DENY"
    assert (await client.get(f"{base}/rider")).status_code in (307, 308)
    m = await client.get(f"{base}/rider/manifest.webmanifest")
    assert m.headers["content-type"].startswith("application/manifest+json")
    assert m.json()["scope"] == "/rider/" and m.json()["display"] == "standalone"
    sw = await client.get(f"{base}/rider/sw.js")
    assert "javascript" in sw.headers["content-type"] and "cmd-rider" in sw.text
    t = await client.get(f"{base}/track/anything")
    assert t.status_code == 200 and t.headers["cache-control"] == "no-store"
    assert (await client.get(f"{base}/dashboard")).status_code == 200
    for asset in ("common.js", "common.css", "track.js", "dashboard.js"):
        assert (await client.get(f"{base}/static/{asset}")).status_code == 200
    # Leaflet is pinned with integrity hashes on every page that uses it
    for page in ("/rider/", "/track/x", "/dashboard"):
        html = (await client.get(base + page)).text
        assert "leaflet@1.9.4" in html and 'integrity="sha256-' in html


async def test_live_responses_tell_proxies_not_to_buffer(client, admin):
    from fastapi import Request

    from app.services import events
    scope = {"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b""}
    r = events.response(Request(scope), "events:test", None)
    assert r.media_type == "text/event-stream"
    assert "no-transform" in r.headers["cache-control"] and r.headers["x-accel-buffering"] == "no"
