import base64
import io
import json

import httpx
import pytest
from PIL import Image

from app import worker
from app.core.config import settings
from app.db.redis import redis_client
from app.services import id_verification
from tests.test_rider_signup import pending, signup

NIN = {"id_type": "nin", "id_number": "123 4567 8901"}


def dojah_reply(status=200, first="KOLA", last="ADE", match=True, confidence=97.5):
    body = {"entity": {"nin": "1*****78901", "firstname": first, "surname": last, "gender": "m",
                       "birthdate": "10-06-1990", "phone_number": "08000000000", "photo": "BASE64...",
                       "selfie_verification": {"confidence_value": confidence, "match": match}}}
    return status, body


class FakeDojah:
    def __init__(self, status=200, body=None, error=None):
        self.status, self.body, self.error, self.requests = status, body or dojah_reply()[1], error, []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.error:
            raise self.error
        return httpx.Response(self.status, json=self.body)


@pytest.fixture
def dojah(monkeypatch):
    fake = FakeDojah()
    real_client = httpx.AsyncClient
    monkeypatch.setattr(id_verification.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(fake.handler), **kw))
    for k, v in {"ID_VERIFY_PROVIDER": "dojah", "DOJAH_APP_ID": "app-123",
                 "DOJAH_SECRET_KEY": "test_sk_abc", "DOJAH_BASE_URL": "https://sandbox.dojah.io"}.items():
        monkeypatch.setattr(settings, k, v)
    return fake


async def apply_and_check(client, admin, **over) -> dict:
    """Applies, lets the worker run the queued check, returns the application as admins see it."""
    r = await signup(client, **{**NIN, **over})
    assert r.status_code == 201, r.text
    assert await worker.process_one_job(timeout=1)
    apps = await pending(client, admin)
    return next(a for a in apps if a["email"] == (over.get("email") or "kola@example.com"))


# ----------------------------------------------------------------- no provider
async def test_without_a_provider_it_asks_for_a_manual_check(client, admin):
    a = await apply_and_check(client, admin)
    assert a["id_check_status"] == "manual"
    assert any("Automatic government check is off" in r for r in a["id_check_reasons"])


async def test_signup_queues_the_check_for_the_worker(client, admin):
    await signup(client, **NIN)
    [job] = [json.loads(j) for j in await redis_client.lrange(id_verification.JOB_QUEUE, 0, -1)]
    assert job["type"] == "id_check"
    [a] = await pending(client, admin)
    assert a["id_check_status"] == "pending"  # until the worker gets to it


async def test_format_and_duplicate_checks_are_free(client, admin):
    a = await apply_and_check(client, admin, id_number="12345")  # NIN must be 11 digits
    assert any("A NIN has exactly 11 digits" in r for r in a["id_check_reasons"])
    assert a["id_check_status"] == "review"  # a red flag, not just "check by hand"
    b = await apply_and_check(client, admin, email="second@example.com", phone="0811 444 5555",
                              id_number="12345")  # same ID as the first applicant
    assert any("also on Kola Ade's application" in r for r in b["id_check_reasons"])
    assert b["id_check_status"] == "review"


# ----------------------------------------------------------------- with Dojah
async def test_real_nin_with_matching_face_and_name_is_verified(client, admin, dojah):
    a = await apply_and_check(client, admin)
    assert a["id_check_status"] == "verified", a["id_check_reasons"]
    assert a["id_record_name"] == "Kola Ade" and a["id_name_match"] == 100 and a["id_face_match"] == 97.5
    # the request is the one Dojah documents
    [req] = dojah.requests
    assert str(req.url) == "https://sandbox.dojah.io/api/v1/kyc/nin/verify"
    assert req.headers["AppId"] == "app-123" and req.headers["Authorization"] == "test_sk_abc"
    body = json.loads(req.content)
    assert body["nin"] == "12345678901" and body["threshold"] == settings.ID_FACE_MATCH_THRESHOLD
    assert not body["selfie_image"].startswith("data:")
    with Image.open(io.BytesIO(base64.b64decode(body["selfie_image"]))) as img:
        assert img.format == "JPEG"  # converted, whatever the applicant uploaded


async def test_only_name_and_scores_are_kept(client, admin, dojah):
    from sqlmodel import select

    from app.db.session import AsyncSessionLocal
    from app.models.rider_application import RiderApplication
    await apply_and_check(client, admin)
    async with AsyncSessionLocal() as s:
        row = (await s.exec(select(RiderApplication))).one()
    stored = json.dumps(row.model_dump(), default=str)
    for secret in ("10-06-1990", "08000000000", "BASE64..."):  # DOB, phone, government photo
        assert secret not in stored


async def test_face_mismatch_needs_review(client, admin, dojah):
    dojah.body = dojah_reply(match=False, confidence=41.0)[1]
    a = await apply_and_check(client, admin)
    assert a["id_check_status"] == "review"
    assert any("selfie doesn't match the NIN photo" in r and "41.0%" in r for r in a["id_check_reasons"])


async def test_name_mismatch_needs_review(client, admin, dojah):
    dojah.body = dojah_reply(first="CHINEDU", last="OKAFOR")[1]
    a = await apply_and_check(client, admin)
    assert a["id_check_status"] == "review" and a["id_name_match"] < settings.ID_NAME_MATCH_THRESHOLD
    assert any("Chinedu Okafor" in r and "Kola Ade" in r for r in a["id_check_reasons"])


async def test_unknown_nin_fails(client, admin, dojah):
    dojah.status, dojah.body = 404, {"error": "NIN not found"}
    a = await apply_and_check(client, admin)
    assert a["id_check_status"] == "failed"
    assert any("not found in NIMC records" in r for r in a["id_check_reasons"])


@pytest.mark.parametrize("status, error, text", [
    (402, None, "wallet is empty"),
    (401, None, "rejected the keys"),
    (429, None, "rate-limiting"),
    (200, httpx.ConnectTimeout("slow"), "Could not reach Dojah"),
])
async def test_provider_problems_are_errors_not_verdicts(client, admin, dojah, status, error, text):
    dojah.status, dojah.error = status, error
    if status != 200:
        dojah.body = {"error": "nope"}
    a = await apply_and_check(client, admin)
    assert a["id_check_status"] == "error"
    assert any(text in r for r in a["id_check_reasons"])


async def test_admin_can_check_again(client, admin, dojah):
    dojah.status, dojah.body = 402, {"error": "insufficient balance"}
    a = await apply_and_check(client, admin)
    assert a["id_check_status"] == "error"
    dojah.status, dojah.body = dojah_reply()  # wallet funded
    r = await client.post(f"/admin/rider-applications/{a['id']}/check-id", headers=admin["headers"])
    assert r.status_code == 200 and r.json()["id_check_status"] == "verified"
    logs = (await client.get("/admin/audit-logs", headers=admin["headers"])).json()["items"]
    assert any(log["action"] == "rider_application.check_id" for log in logs)


async def test_duplicate_id_overrides_a_passing_check(client, admin, dojah):
    await apply_and_check(client, admin)
    b = await apply_and_check(client, admin, email="twin@example.com", phone="0811 777 8888",
                              full_name="Kola Ade")
    assert b["id_check_status"] == "review"
    assert any("also on" in r for r in b["id_check_reasons"])


async def test_other_id_types_go_to_manual_with_a_provider(client, admin, dojah):
    a = await apply_and_check(client, admin, id_type="drivers_licence", id_number="ABC12345AA01")
    assert a["id_check_status"] == "manual" and dojah.requests == []
    assert any("cover NIN only" in r for r in a["id_check_reasons"])


async def test_approval_records_the_id_check_result(client, admin, dojah):
    dojah.body = dojah_reply(match=False, confidence=30)[1]
    a = await apply_and_check(client, admin)
    await client.post(f"/admin/rider-applications/{a['id']}/approve", headers=admin["headers"])
    logs = (await client.get("/admin/audit-logs", headers=admin["headers"])).json()["items"]
    approve = next(log for log in logs if log["action"] == "rider_application.approve")
    assert approve["changes"]["id_check"] == "review"  # admin approved despite the warning: on record


async def test_dashboard_board_shows_the_result(client, admin, dojah):
    await apply_and_check(client, admin)
    board = (await client.get("/admin/deliveries/board", headers=admin["headers"])).json()
    app = board["applications"][0]
    assert app["id_check_status"] == "verified" and app["id_face_match"] == 97.5


@pytest.mark.parametrize("typed, record, at_least, at_most", [
    ("Kola Ade", ("ADE", "KOLA"), 100, 100),          # surname first on the record
    ("Kola Adé", ("KOLA", None, "ADE"), 100, 100),    # tone marks typed, plain on the record
    ("Adéwálé Ọlá", ("ADEWALE", "OLA"), 100, 100),
    ("Kola Adeh", ("KOLA", "ADE"), 85, 99),           # small spelling slip
    ("Kola Ade", ("KOLAWOLE", "JOHN", "ADE"), 80, 100),
    ("Chinedu Okafor", ("KOLA", "ADE"), 0, 50),        # someone else
])
def test_name_matching(typed, record, at_least, at_most):
    assert at_least <= id_verification.name_match(typed, *record) <= at_most
