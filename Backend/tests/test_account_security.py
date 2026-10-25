from app.core.config import settings
from tests.conftest import create_user, last_code, queued_messages


async def test_forgot_and_reset_password_by_email(client):
    u = await create_user(client)
    r = await client.post("/auth/password/forgot", json={"email": "Shopper@Example.com"})
    assert r.status_code == 202
    [msg] = await queued_messages()
    assert msg["channel"] == "email" and msg["to"] == "shopper@example.com"
    code = await last_code("shopper@example.com")

    wrong = "000000" if code != "000000" else "111111"
    bad = await client.post("/auth/password/reset", json={"email": u["email"], "code": wrong,
                                                          "new_password": "BrandNew123!"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_code"

    ok = await client.post("/auth/password/reset", json={"email": u["email"], "code": code,
                                                         "new_password": "BrandNew123!"})
    assert ok.status_code == 204
    # every old session is dead: access and refresh tokens
    assert (await client.get("/users/me", headers=u["headers"])).status_code == 401
    assert (await client.post("/auth/refresh",
                              json={"refresh_token": u["tokens"]["refresh_token"]})).status_code == 401
    # old password no longer works, new one does
    assert (await client.post("/auth/login", json={"email": u["email"],
                                                   "password": u["password"]})).status_code == 401
    r = await client.post("/auth/login", json={"email": u["email"], "password": "BrandNew123!"})
    assert r.status_code == 200
    assert (await client.get("/users/me", headers={
        "Authorization": f"Bearer {r.json()['access_token']}"})).status_code == 200
    # the code was single use
    again = await client.post("/auth/password/reset", json={"email": u["email"], "code": code,
                                                            "new_password": "Another123!"})
    assert again.status_code == 400


async def test_forgot_password_is_email_only(client):
    await create_user(client, phone="0803 111 2222")
    r = await client.post("/auth/password/forgot", json={"email": "08031112222"})
    assert r.status_code == 422
    assert await queued_messages() == []


async def test_forgot_password_does_not_reveal_accounts(client):
    await create_user(client)
    real = await client.post("/auth/password/forgot", json={"email": "shopper@example.com"})
    ghost = await client.post("/auth/password/forgot", json={"email": "ghost@example.com"})
    assert real.status_code == ghost.status_code == 202
    assert real.json() == ghost.json()
    assert [m["to"] for m in await queued_messages()] == ["shopper@example.com"]


async def test_reset_code_dies_after_too_many_wrong_guesses(client):
    u = await create_user(client)
    await client.post("/auth/password/forgot", json={"email": u["email"]})
    code = await last_code(u["email"])
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(settings.OTP_MAX_ATTEMPTS):
        await client.post("/auth/password/reset", json={"email": u["email"], "code": wrong,
                                                        "new_password": "BrandNew123!"})
    r = await client.post("/auth/password/reset", json={"email": u["email"], "code": code,
                                                        "new_password": "BrandNew123!"})
    assert r.status_code == 400


async def test_reset_unlocks_a_locked_account(client):
    u = await create_user(client)
    for _ in range(settings.LOGIN_MAX_FAILURES):
        await client.post("/auth/login", json={"email": u["email"], "password": "nope"})
    assert (await client.post("/auth/login", json={"email": u["email"],
                                                   "password": u["password"]})).status_code == 429
    await client.post("/auth/password/forgot", json={"email": u["email"]})
    code = await last_code(u["email"])
    await client.post("/auth/password/reset", json={"email": u["email"], "code": code,
                                                    "new_password": "BrandNew123!"})
    assert (await client.post("/auth/login", json={"email": u["email"],
                                                   "password": "BrandNew123!"})).status_code == 200


async def test_phone_verification(client):
    u = await create_user(client, phone="0803 111 2222")
    assert (await client.get("/users/me", headers=u["headers"])).json()["phone_verified_at"] is None
    r = await client.post("/users/me/phone/verify", headers=u["headers"])
    assert r.status_code == 202
    code = await last_code("+2348031112222")
    r = await client.post("/users/me/phone/verify/confirm", headers=u["headers"], json={"code": code})
    assert r.status_code == 200 and r.json()["phone_verified_at"] is not None
    # asking again once verified is refused
    assert (await client.post("/users/me/phone/verify", headers=u["headers"])).status_code == 400
    # a new number must be verified again
    r = await client.patch("/users/me", headers=u["headers"], json={"phone": "0809 999 8888"})
    assert r.json()["phone_verified_at"] is None


async def test_phone_code_is_void_after_changing_number(client):
    u = await create_user(client, phone="0803 111 2222")
    await client.post("/users/me/phone/verify", headers=u["headers"])
    code = await last_code("+2348031112222")
    await client.patch("/users/me", headers=u["headers"], json={"phone": "0809 999 8888"})
    r = await client.post("/users/me/phone/verify/confirm", headers=u["headers"], json={"code": code})
    assert r.status_code == 400


async def test_phone_verification_needs_a_phone(client):
    u = await create_user(client)
    r = await client.post("/users/me/phone/verify", headers=u["headers"])
    assert r.status_code == 400 and r.json()["error"]["code"] == "no_phone"
