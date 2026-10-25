from app.core.config import settings
from app.services import events
from tests.conftest import queued_messages
from tests.test_delivery_flow import stream_events
from tests.test_uploads import GPS_TAG, JPEG, PNG, exif_of, make_image

APPLICANT = {"full_name": "Kola Ade", "phone": "0811 222 3333", "email": "Kola@Example.com",
             "password": "Passw0rd!x", "vehicle_type": "motorcycle", "plate_number": "lsd 123 ab",
             "id_type": "drivers_licence", "id_number": "abc 12345 xy",
             "area": "Lekki", "note": "5 years on okada"}
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def id_files(front=JPEG, selfie=PNG, back=None):
    files = {"id_front": ("front.jpg", front, "image/jpeg"), "selfie": ("me.png", selfie, "image/png")}
    if back is not None:
        files["id_back"] = ("back.pdf", back, "application/pdf")
    return files


async def signup(client, files=None, **over):
    data = {k: v for k, v in {**APPLICANT, **over}.items() if v is not None}
    return await client.post("/auth/rider-signup", data=data, files=files if files is not None else id_files())


async def apply(client, files=None, **over) -> dict:
    r = await signup(client, files, **over)
    assert r.status_code == 201, r.text
    return r.json()


async def pending(client, admin) -> list[dict]:
    return (await client.get("/admin/rider-applications", headers=admin["headers"])).json()["items"]


async def login(client, password="Passw0rd!x"):
    return await client.post("/auth/login", json={"email": "kola@example.com", "password": password})


async def test_applicant_cannot_sign_in_until_approved(client, admin):
    assert (await apply(client))["status"] == "pending"
    r = await login(client)
    assert r.status_code == 401 and r.json()["error"]["code"] == "application_pending"
    # the "being reviewed" message only appears with the right password
    r = await login(client, "wrong-password")
    assert r.json()["error"]["code"] == "invalid_credentials"
    # the applicant was texted, and the admin dashboard got a live alert
    assert any(m["to"] == "+2348112223333" and "thanks for applying" in m["body"]
               for m in await queued_messages())
    assert "rider.applied" in [e for e, _ in await stream_events(events.ADMIN)]


async def test_admin_sees_the_application(client, admin):
    await apply(client)
    [a] = await pending(client, admin)
    assert a["full_name"] == "Kola Ade" and a["email"] == "kola@example.com"
    assert a["phone"] == "+2348112223333" and a["plate_number"] == "LSD 123 AB"
    assert a["vehicle_type"] == "motorcycle" and a["status"] == "pending"
    board = (await client.get("/admin/deliveries/board", headers=admin["headers"])).json()
    assert board["applications"][0]["full_name"] == "Kola Ade"
    # not offered deliveries while pending
    assert board["riders"] == []


async def test_approve_lets_them_in(client, admin):
    await apply(client)
    [a] = await pending(client, admin)
    r = await client.post(f"/admin/rider-applications/{a['id']}/approve", headers=admin["headers"])
    assert r.status_code == 200 and r.json()["status"] == "approved"
    r = await login(client)
    assert r.status_code == 200
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert (await client.get("/rider/deliveries", headers=h)).status_code == 200
    me = (await client.get("/users/me", headers=h)).json()
    assert me["role"] == "rider"
    assert any("you're approved" in m["body"] for m in await queued_messages())
    board = (await client.get("/admin/deliveries/board", headers=admin["headers"])).json()
    assert board["applications"] == [] and board["riders"][0]["name"] == "Kola Ade"
    logs = (await client.get("/admin/audit-logs", headers=admin["headers"])).json()["items"]
    assert logs[0]["action"] == "rider_application.approve"
    # can't be reviewed twice
    again = await client.post(f"/admin/rider-applications/{a['id']}/approve", headers=admin["headers"])
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_reviewed"


async def test_reject_with_reason(client, admin):
    await apply(client)
    [a] = await pending(client, admin)
    r = await client.post(f"/admin/rider-applications/{a['id']}/reject", headers=admin["headers"],
                          json={"reason": "We're full in Lekki for now."})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    r = await login(client)
    assert r.json()["error"]["code"] == "application_rejected"
    assert "We're full in Lekki" in r.json()["error"]["message"]
    assert any("We're full in Lekki" in m["body"] for m in await queued_messages())
    assert await pending(client, admin) == []
    rejected = (await client.get("/admin/rider-applications", headers=admin["headers"],
                                 params={"status": "rejected"})).json()["items"]
    assert rejected[0]["reject_reason"] == "We're full in Lekki for now."


async def test_duplicates_and_bad_input(client, admin, customer):
    await apply(client)
    r = await signup(client, phone="0811 999 0000")
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"
    r = await signup(client, email="other@example.com")
    assert r.status_code == 409 and r.json()["error"]["code"] == "phone_taken"
    r = await signup(client, email="x@example.com", phone=None)
    assert r.status_code == 422  # phone is required for riders
    r = await signup(client, email="y@example.com", phone="0811 000 1111", vehicle_type="jet")
    assert r.status_code == 422
    r = await signup(client, email="z@example.com", phone="0811 000 2222", id_number=None)
    assert r.status_code == 422  # ID number is required


async def test_only_admins_review(client, admin, customer):
    await apply(client)
    [a] = await pending(client, admin)
    h = customer["headers"]
    assert (await client.get("/admin/rider-applications", headers=h)).status_code == 403
    assert (await client.post(f"/admin/rider-applications/{a['id']}/approve", headers=h)).status_code == 403
    assert (await client.post(f"/admin/rider-applications/{a['id']}/approve")).status_code == 401


# ------------------------------------------------------------------ ID documents
async def test_id_photos_are_required_and_checked(client, admin):
    r = await signup(client, files={"id_front": ("f.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 422  # no selfie
    r = await signup(client, files=id_files(front=b"just some text"))
    assert r.status_code == 400 and r.json()["error"]["code"] == "unsupported_document"
    r = await signup(client, files=id_files(selfie=PDF))  # the face photo must be a photo
    assert r.status_code == 400 and r.json()["error"]["code"] == "unsupported_document"
    r = await signup(client, files=id_files(front=PDF))   # a PDF of the ID is fine
    assert r.status_code == 201
    [a] = await pending(client, admin)
    assert {d["kind"]: d["content_type"] for d in a["documents"]}["id_front"] == "application/pdf"


async def test_too_big_document(client, monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_BYTES", 40)
    r = await signup(client, files=id_files(front=JPEG + b"\x00" * 100))
    assert r.status_code == 400 and r.json()["error"]["code"] == "file_too_large"


async def test_admin_sees_and_opens_the_documents(client, admin):
    await apply(client, files=id_files(back=PDF))
    [a] = await pending(client, admin)
    assert a["id_type"] == "drivers_licence" and a["id_number"] == "ABC 12345 XY"
    kinds = {d["kind"]: d for d in a["documents"]}
    assert set(kinds) == {"id_front", "id_back", "selfie"}
    assert "data" not in kinds["id_front"]  # the list never carries file contents
    assert kinds["id_back"]["content_type"] == "application/pdf"

    r = await client.get(f"/admin/rider-applications/{a['id']}/documents/{kinds['id_front']['id']}",
                         headers=admin["headers"])
    assert r.status_code == 200 and r.content[:3] == b"\xff\xd8\xff"  # a (re-encoded) JPEG
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "private, no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    # every view is in the audit log
    logs = (await client.get("/admin/audit-logs", headers=admin["headers"],
                             params={"entity_type": "rider_application"})).json()["items"]
    assert logs[0]["action"] == "rider_document.view" and logs[0]["changes"] == {"document": "id_front"}
    board = (await client.get("/admin/deliveries/board", headers=admin["headers"])).json()
    assert {d["kind"] for d in board["applications"][0]["documents"]} == {"id_front", "id_back", "selfie"}


async def test_documents_are_private(client, admin, customer):
    await apply(client)
    [a] = await pending(client, admin)
    doc = a["documents"][0]["id"]
    url = f"/admin/rider-applications/{a['id']}/documents/{doc}"
    assert (await client.get(url)).status_code == 401
    assert (await client.get(url, headers=customer["headers"])).status_code == 403
    # a document id under the wrong application isn't served
    other = await apply(client, email="other@example.com", phone="0811 555 6666")  # noqa: F841
    apps = await pending(client, admin)
    other_app = next(x for x in apps if x["email"] == "other@example.com")
    r = await client.get(f"/admin/rider-applications/{other_app['id']}/documents/{doc}",
                         headers=admin["headers"])
    assert r.status_code == 404
    # nothing was written to the public media folder
    from pathlib import Path
    assert not any(p.name.startswith(("id_", "selfie")) for p in Path(settings.MEDIA_DIR).rglob("*"))


async def test_signup_cannot_make_an_admin(client, admin):
    await apply(client, role="admin")
    [a] = await pending(client, admin)
    await client.post(f"/admin/rider-applications/{a['id']}/approve", headers=admin["headers"])
    r = await login(client)
    me = (await client.get("/users/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})).json()
    assert me["role"] == "rider"


async def test_rider_page_has_the_apply_form(client):
    html = (await client.get("http://test/rider/")).text
    assert 'id="apply-form"' in html and "Apply to ride with us" in html


async def test_id_photos_lose_their_location_even_without_the_app(client, admin):
    # someone posting straight to the API, skipping the app's own re-encoding
    selfie = make_image("JPEG", gps=True)
    await apply(client, files={"id_front": ("f.jpg", make_image("JPEG", gps=True), "image/jpeg"),
                               "selfie": ("s.jpg", selfie, "image/jpeg")})
    [a] = await pending(client, admin)
    for d in a["documents"]:
        r = await client.get(f"/admin/rider-applications/{a['id']}/documents/{d['id']}", headers=admin["headers"])
        assert GPS_TAG not in exif_of(r.content) and b"PhoneMaker" not in r.content
