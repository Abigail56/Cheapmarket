import base64
import json
import os

import http_ece
import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlmodel import select

from app import worker
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.push_subscription import PushSubscription
from app.models.user import UserRole
from app.services import notifications, push
from scripts.vapid_keys import new_keys
from tests.conftest import create_user, queued_messages
from tests.test_delivery_flow import assign, order, rider  # noqa: F401 (fixtures)

FCM = "https://fcm.googleapis.com/fcm/send/device-123"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class Browser:
    """Plays the phone: its own key pair and auth secret, like PushManager.subscribe() makes."""

    def __init__(self, endpoint=FCM):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = os.urandom(16)
        public = self.key.public_key().public_bytes(serialization.Encoding.X962,
                                                    serialization.PublicFormat.UncompressedPoint)
        self.subscription = {"endpoint": endpoint, "keys": {"p256dh": b64url(public), "auth": b64url(self.auth)}}

    def decrypt(self, body: bytes) -> dict:
        return json.loads(http_ece.decrypt(body, private_key=self.key, auth_secret=self.auth,
                                           version="aes128gcm"))


class FakePushService:
    """Stands in for Google/Mozilla/Apple: records what we POST and answers with `status`."""

    def __init__(self, status=201):
        self.status, self.requests = status, []

    def post(self, url, data=None, headers=None, timeout=None):
        self.requests.append({"url": url, "data": data, "headers": headers})
        return type("Resp", (), {"status_code": self.status, "text": "", "reason": "", "headers": {}})()


@pytest_asyncio.fixture
async def vapid(monkeypatch):
    public, private = new_keys()
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", public)
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", private)
    return public


@pytest.fixture
def service(monkeypatch):
    fake = FakePushService()
    monkeypatch.setattr(push, "_http", fake)
    return fake


async def subscriptions():
    async with AsyncSessionLocal() as s:
        return (await s.exec(select(PushSubscription))).all()


# ------------------------------------------------------------------- endpoints
async def test_key_endpoint_reports_whether_push_is_on(client, rider, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", None)
    r = await client.get("/rider/push/key", headers=rider["headers"])
    assert r.json() == {"enabled": False, "public_key": None}
    public, private = new_keys()
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", public)
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", private)
    assert (await client.get("/rider/push/key", headers=rider["headers"])).json() == {
        "enabled": True, "public_key": public}
    assert len(b64url_decode(public)) == 65  # what pushManager.subscribe() expects


async def test_subscribe_and_unsubscribe(client, rider, vapid):  # noqa: F811
    sub = Browser().subscription
    r = await client.post("/rider/push/subscribe", headers=rider["headers"], json=sub)
    assert r.status_code == 201
    [saved] = await subscriptions()
    assert saved.endpoint == FCM and str(saved.user_id) == rider["id"]
    # subscribing the same phone again doesn't duplicate it
    await client.post("/rider/push/subscribe", headers=rider["headers"], json=sub)
    assert len(await subscriptions()) == 1
    r = await client.post("/rider/push/unsubscribe", headers=rider["headers"], json={"endpoint": FCM})
    assert r.status_code == 204 and await subscriptions() == []


async def test_only_real_push_services_are_accepted(client, rider, vapid):  # noqa: F811
    for bad in ("http://fcm.googleapis.com/x",           # not https
                "https://169.254.169.254/latest/meta",    # cloud metadata address
                "https://internal.example.com/push",      # any other host
                "https://fcm.googleapis.com.evil.com/x"): # look-alike host
        r = await client.post("/rider/push/subscribe", headers=rider["headers"],
                              json=Browser(bad).subscription)
        assert r.status_code == 400 and r.json()["error"]["code"] == "bad_push_endpoint", bad
    ok = await client.post("/rider/push/subscribe", headers=rider["headers"],
                           json=Browser("https://wns2-par02p.notify.windows.com/w/?token=x").subscription)
    assert ok.status_code == 201


async def test_a_phone_follows_whoever_logs_in(client, rider, vapid):  # noqa: F811
    sub = Browser().subscription
    await client.post("/rider/push/subscribe", headers=rider["headers"], json=sub)
    rider2 = await create_user(client, "rider2@example.com", UserRole.RIDER)
    await client.post("/rider/push/subscribe", headers=rider2["headers"], json=sub)
    [saved] = await subscriptions()
    assert str(saved.user_id) == rider2["id"]


async def test_customers_cannot_subscribe(client, customer, vapid):
    r = await client.post("/rider/push/subscribe", headers=customer["headers"], json=Browser().subscription)
    assert r.status_code == 403


async def test_subscribe_refused_when_push_is_off(client, rider, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", None)
    r = await client.post("/rider/push/subscribe", headers=rider["headers"], json=Browser().subscription)
    assert r.status_code == 400 and r.json()["error"]["code"] == "push_disabled"


# ---------------------------------------------------------------- what triggers a push
async def test_offer_cancel_and_address_change_push_the_rider(client, admin, order, rider):  # noqa: F811
    did = await assign(client, admin, order, rider)
    pushes = [m for m in await queued_messages() if m["channel"] == "push"]
    assert pushes[-1]["to"] == rider["id"] and order["order_number"] in pushes[-1]["subject"]
    assert pushes[-1]["tag"] == f"offer-{did}" and pushes[-1]["url"] == "/rider/"

    from tests.test_delivery_flow import tracking_token
    token = await tracking_token(order["order_number"])
    await client.post(f"/track/{token}/address", json={"landmark": "Behind the mosque"})
    pushes = [m for m in await queued_messages() if m["channel"] == "push"]
    assert pushes[-1]["subject"].startswith("Address changed")

    await client.post(f"/rider/deliveries/{did}/accept", headers=rider["headers"])
    await client.patch(f"/admin/orders/{order['order_number']}/status", headers=admin["headers"],
                       json={"status": "cancelled"})
    pushes = [m for m in await queued_messages() if m["channel"] == "push"]
    assert pushes[-1]["subject"].startswith("Cancelled")


# ------------------------------------------------------------- sending, for real
async def test_push_is_encrypted_for_the_phone_and_signed_with_our_key(client, rider, vapid, service):  # noqa: F811
    phone = Browser()
    await client.post("/rider/push/subscribe", headers=rider["headers"], json=phone.subscription)
    await notifications.push_rider(rider["id"], "New delivery: CMD-1", "Accept within 5 minutes.",
                                   tag="offer-1")
    assert await worker.process_one_notification(timeout=1)

    [req] = service.requests
    assert req["url"] == FCM
    # only the phone can read it
    assert b"CMD-1" not in req["data"]
    assert phone.decrypt(req["data"]) == {"title": "New delivery: CMD-1", "body": "Accept within 5 minutes.",
                                          "url": "/rider/", "tag": "offer-1"}
    # signed with our VAPID key, for this push service
    headers = {k.lower(): v for k, v in req["headers"].items()}
    scheme, _, params = headers["authorization"].partition(" ")
    assert scheme == "vapid"
    fields = dict(p.strip().split("=", 1) for p in params.split(","))
    assert fields["k"] == vapid
    pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b64url_decode(vapid))
    claims = jwt.decode(fields["t"], pub, algorithms=["ES256"], audience="https://fcm.googleapis.com")
    assert claims["sub"] == settings.VAPID_SUBJECT
    assert headers["urgency"] == "high" and int(headers["ttl"]) == 600
    [saved] = await subscriptions()
    assert saved.last_success_at is not None


async def test_gone_subscriptions_are_removed(client, rider, vapid, service):  # noqa: F811
    await client.post("/rider/push/subscribe", headers=rider["headers"], json=Browser().subscription)
    service.status = 410  # phone uninstalled the app / turned alerts off
    assert await push.send_to_user(rider["id"], {"title": "t", "body": "b"}) == (0, 0)
    assert await subscriptions() == []


async def test_temporary_failures_are_retried(client, rider, vapid, service, monkeypatch):  # noqa: F811
    await client.post("/rider/push/subscribe", headers=rider["headers"], json=Browser().subscription)
    service.status = 503
    with pytest.raises(notifications.NotificationError):
        await notifications.send({"channel": "push", "to": rider["id"], "subject": "t", "body": "b"})
    assert len(await subscriptions()) == 1  # kept: the worker retries


async def test_no_devices_is_not_an_error(rider, vapid, service):  # noqa: F811
    await notifications.send({"channel": "push", "to": rider["id"], "subject": "t", "body": "b"})
    assert service.requests == []
