import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import settings
from app.services import google_auth
from tests.conftest import create_user
from tests.test_rider_signup import APPLICANT, id_files, pending

CLIENT_ID = "1234567890-abc.apps.googleusercontent.com"
GOOGLE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def google_token(email="ada@gmail.com", sub="google-sub-1", *, name="Ada Obi", verified=True,
                 aud=CLIENT_ID, iss="https://accounts.google.com", expires_in=3600, key=GOOGLE_KEY) -> str:
    """An ID token shaped and signed like Google's."""
    now = int(time.time())
    claims = {"iss": iss, "aud": aud, "sub": sub, "email": email, "email_verified": verified,
              "name": name, "iat": now, "exp": now + expires_in}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})


@pytest.fixture(autouse=True)
def google(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", CLIENT_ID)
    # "Google's current public key" is ours for these tests
    monkeypatch.setattr(google_auth, "_signing_key", lambda token: GOOGLE_KEY.public_key())


async def sign_in(client, token, create=True):
    return await client.post("/auth/google", json={"id_token": token, "create_account": create})


async def test_config_exposes_client_id_only_when_set(client, monkeypatch):
    assert (await client.get("/auth/config")).json()["google_client_id"] == CLIENT_ID
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", None)
    assert (await client.get("/auth/config")).json()["google_client_id"] is None
    r = await sign_in(client, google_token())
    assert r.status_code == 400 and r.json()["error"]["code"] == "google_disabled"


async def test_first_google_sign_in_creates_a_customer(client):
    r = await sign_in(client, google_token())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["email"] == "ada@gmail.com" and body["user"]["full_name"] == "Ada Obi"
    assert body["user"]["role"] == "customer"
    me = await client.get("/users/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    # next time: same account, not a duplicate
    again = (await sign_in(client, google_token())).json()
    assert again["user"]["id"] == body["user"]["id"]
    # they have no password anyone knows
    r = await client.post("/auth/login", json={"email": "ada@gmail.com", "password": "Passw0rd!x"})
    assert r.status_code == 401


async def test_links_an_existing_account_with_the_same_email(client):
    u = await create_user(client, email="ada@gmail.com")
    r = await sign_in(client, google_token(email="ADA@gmail.com"))
    assert r.json()["user"]["id"] == u["id"]
    # password sign-in still works too
    assert (await client.post("/auth/login", json={"email": "ada@gmail.com",
                                                   "password": u["password"]})).status_code == 200
    # but a DIFFERENT Google account can't take over that email afterwards
    r = await sign_in(client, google_token(email="ada@gmail.com", sub="someone-else"))
    assert r.status_code == 401 and r.json()["error"]["code"] == "google_mismatch"


@pytest.mark.parametrize("token, code", [
    (lambda: google_token(key=OTHER_KEY), "google_invalid"),            # not signed by Google
    (lambda: google_token(aud="another-app.apps.googleusercontent.com"), "google_invalid"),
    (lambda: google_token(iss="https://evil.example.com"), "google_invalid"),
    (lambda: google_token(expires_in=-120), "google_invalid"),          # expired
    (lambda: google_token(verified=False), "google_email_unverified"),
    (lambda: "not.a.jwt.at-all-but-long-enough", "google_invalid"),
])
async def test_bad_tokens_are_refused(client, token, code):
    r = await sign_in(client, token())
    assert r.status_code == 401 and r.json()["error"]["code"] == code
    assert (await sign_in(client, google_token())).json()["user"]["role"] == "customer"  # sanity


async def test_rider_app_and_dashboard_never_create_accounts(client):
    r = await sign_in(client, google_token(email="new@gmail.com"), create=False)
    assert r.status_code == 404 and r.json()["error"]["code"] == "google_no_account"


async def test_google_never_upgrades_roles(client, admin):
    # an admin signing in with Google stays an admin; a customer stays a customer
    r = await sign_in(client, google_token(email="admin@example.com", sub="admin-google"), create=False)
    assert r.json()["user"]["role"] == "admin"
    r = await sign_in(client, google_token(email="cust@gmail.com", sub="c-1"))
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert (await client.get("/admin/orders", headers=h)).status_code == 403


async def test_disabled_accounts_stay_out(client, admin):
    u = await create_user(client, email="ada@gmail.com")
    await client.patch(f"/admin/users/{u['id']}", headers=admin["headers"], json={"is_active": False})
    r = await sign_in(client, google_token())
    assert r.status_code == 401 and r.json()["error"]["code"] == "account_disabled"


async def test_rider_applies_with_google(client, admin):
    form = {k: v for k, v in APPLICANT.items() if k not in ("email", "password")}
    form["google_id_token"] = google_token(email="kola@gmail.com", sub="kola-google")
    r = await client.post("/auth/rider-signup", data=form, files=id_files())
    assert r.status_code == 201, r.text
    [a] = await pending(client, admin)
    assert a["email"] == "kola@gmail.com"  # from Google, verified
    # pending: Google sign-in gets the same "being reviewed" answer
    r = await sign_in(client, google_token(email="kola@gmail.com", sub="kola-google"), create=False)
    assert r.status_code == 401 and r.json()["error"]["code"] == "application_pending"
    await client.post(f"/admin/rider-applications/{a['id']}/approve", headers=admin["headers"])
    r = await sign_in(client, google_token(email="kola@gmail.com", sub="kola-google"), create=False)
    assert r.status_code == 200 and r.json()["user"]["role"] == "rider"


async def test_rider_signup_with_a_forged_google_token_fails(client):
    form = {k: v for k, v in APPLICANT.items() if k not in ("email", "password")}
    form["google_id_token"] = google_token(key=OTHER_KEY)
    r = await client.post("/auth/rider-signup", data=form, files=id_files())
    assert r.status_code == 401


async def test_password_rider_signup_still_needs_email_and_password(client):
    form = {k: v for k, v in APPLICANT.items() if k != "password"}
    r = await client.post("/auth/rider-signup", data=form, files=id_files())
    assert r.status_code == 422


async def test_pages_show_google_only_when_configured(client):
    for page in ("/rider/", "/dashboard"):
        html = (await client.get("http://test" + page)).text
        assert 'id="google-login"' in html
    js = (await client.get("http://test/static/common.js")).text
    assert "accounts.google.com/gsi/client" in js and "/auth/config" in js

