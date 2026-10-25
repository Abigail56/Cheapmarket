
from app.core.config import settings
from tests.conftest import create_user


async def test_register_login_me(client):
    u = await create_user(client, phone="0803 111 2222")
    me = (await client.get("/users/me", headers=u["headers"])).json()
    assert me["email"] == "shopper@example.com"
    assert me["phone"] == "+2348031112222"  # normalised
    assert me["role"] == "customer"
    assert "password" not in str(me)


async def test_duplicate_email_rejected(client):
    await create_user(client)
    r = await client.post("/auth/register", json={"email": "SHOPPER@example.com",
                          "full_name": "Again", "password": "Passw0rd!x"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"


async def test_weak_password_rejected(client):
    r = await client.post("/auth/register", json={"email": "a@b.co", "full_name": "Abc",
                                                   "password": "short"})
    assert r.status_code == 422


async def test_wrong_password_and_unknown_user_same_error(client):
    await create_user(client)
    bad = await client.post("/auth/login", json={"email": "shopper@example.com", "password": "nope"})
    ghost = await client.post("/auth/login", json={"email": "ghost@example.com", "password": "nope"})
    assert bad.status_code == ghost.status_code == 401
    assert bad.json() == ghost.json()


async def test_login_is_email_and_password(client):
    await create_user(client, phone="08031112222")
    # email is case-insensitive
    r = await client.post("/auth/login", json={"email": "Shopper@Example.com", "password": "Passw0rd!x"})
    assert r.status_code == 200
    # a phone number is not a login
    r = await client.post("/auth/login", json={"email": "0803-111-2222", "password": "Passw0rd!x"})
    assert r.status_code == 422
    # the old field name is not accepted either
    r = await client.post("/auth/login", json={"identifier": "shopper@example.com", "password": "Passw0rd!x"})
    assert r.status_code == 422
    # the old form-based Swagger login is gone: /auth/login is the only way in
    r = await client.post("/auth/token", data={"username": "shopper@example.com", "password": "Passw0rd!x"})
    assert r.status_code == 404


async def test_swagger_authorize_uses_a_pasted_bearer_token(client):
    from app.main import app
    schemes = app.openapi()["components"]["securitySchemes"]
    assert [s["scheme"] for s in schemes.values()] == ["bearer"]


async def test_protected_route_needs_token(client):
    assert (await client.get("/users/me")).status_code == 401
    assert (await client.get("/users/me", headers={"Authorization": "Bearer junk"})).status_code == 401


async def test_refresh_rotates_and_old_token_dies(client):
    u = await create_user(client)
    old = u["tokens"]["refresh_token"]
    r = await client.post("/auth/refresh", json={"refresh_token": old})
    assert r.status_code == 200
    new = r.json()
    assert new["refresh_token"] != old
    assert (await client.post("/auth/refresh", json={"refresh_token": old})).status_code == 401
    # an access token can't be used as a refresh token
    assert (await client.post("/auth/refresh", json={"refresh_token": new["access_token"]})).status_code == 401


async def test_logout_revokes_access_token(client):
    u = await create_user(client)
    r = await client.post("/auth/logout", headers=u["headers"],
                          json={"refresh_token": u["tokens"]["refresh_token"]})
    assert r.status_code == 204
    assert (await client.get("/users/me", headers=u["headers"])).status_code == 401
    assert (await client.post("/auth/refresh",
                              json={"refresh_token": u["tokens"]["refresh_token"]})).status_code == 401


async def test_change_password(client):
    u = await create_user(client)
    bad = await client.post("/users/me/password", headers=u["headers"],
                            json={"current_password": "wrong-one", "new_password": "NewPassw0rd!"})
    assert bad.status_code == 400
    ok = await client.post("/users/me/password", headers=u["headers"],
                           json={"current_password": u["password"], "new_password": "NewPassw0rd!"})
    assert ok.status_code == 204
    r = await client.post("/auth/login", json={"email": u["email"], "password": "NewPassw0rd!"})
    assert r.status_code == 200


async def test_login_rate_limit(client):
    settings.RATE_LIMIT_ENABLED = True
    # a different identifier each time, so the per-account lockout doesn't kick in first
    codes = [(await client.post("/auth/login", json={"email": f"x{i}@y.zz", "password": "bad"})).status_code
             for i in range(7)]
    assert codes[:5] == [401] * 5
    assert codes[5:] == [429] * 2


async def test_addresses_default_handling(client):
    u = await create_user(client)
    a1 = (await client.post("/users/me/addresses", headers=u["headers"],
          json={"street": "1 First St", "city": "Town", "state": "State"})).json()
    a2 = (await client.post("/users/me/addresses", headers=u["headers"],
          json={"street": "2 Second St", "city": "Town", "state": "State", "is_default": True})).json()
    assert a1["is_default"] is True  # first address becomes default automatically
    listing = (await client.get("/users/me/addresses", headers=u["headers"])).json()
    assert [a["is_default"] for a in listing] == [True, False]
    assert listing[0]["id"] == a2["id"]  # newest default wins
    other = await create_user(client, "other@example.com")
    assert (await client.delete(f"/users/me/addresses/{a1['id']}", headers=other["headers"])).status_code == 404


async def test_login_locks_account_after_repeated_failures(client):
    await create_user(client)
    other = await create_user(client, email="other@example.com")
    for _ in range(settings.LOGIN_MAX_FAILURES):
        r = await client.post("/auth/login", json={"email": "shopper@example.com", "password": "nope"})
        assert r.status_code == 401
    # now locked, even with the right password, and regardless of email casing
    r = await client.post("/auth/login", json={"email": "Shopper@Example.com", "password": "Passw0rd!x"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "login_locked"
    assert 0 < int(r.headers["Retry-After"]) <= settings.LOGIN_LOCKOUT_SECONDS
    # other accounts are unaffected
    r = await client.post("/auth/login", json={"email": other["email"], "password": other["password"]})
    assert r.status_code == 200


async def test_unknown_account_locks_out_the_same_way(client):
    for _ in range(settings.LOGIN_MAX_FAILURES):
        await client.post("/auth/login", json={"email": "ghost@example.com", "password": "nope"})
    r = await client.post("/auth/login", json={"email": "ghost@example.com", "password": "nope"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "login_locked"


async def test_successful_login_resets_failure_count(client):
    u = await create_user(client)
    for _ in range(settings.LOGIN_MAX_FAILURES - 1):
        await client.post("/auth/login", json={"email": u["email"], "password": "nope"})
    assert (await client.post("/auth/login", json={"email": u["email"],
                                                   "password": u["password"]})).status_code == 200
    for _ in range(settings.LOGIN_MAX_FAILURES - 1):
        await client.post("/auth/login", json={"email": u["email"], "password": "nope"})
    assert (await client.post("/auth/login", json={"email": u["email"],
                                                   "password": u["password"]})).status_code == 200



async def test_register_returns_working_tokens(client):
    r = await client.post("/auth/register", json={"email": "New@Example.com", "full_name": "New One",
                                                   "password": "Passw0rd!x"})
    assert r.status_code == 201
    body = r.json()
    assert body["user"]["email"] == "new@example.com" and body["user"]["role"] == "customer"
    assert body["token_type"] == "bearer"
    me = await client.get("/users/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["id"] == body["user"]["id"]
    assert (await client.post("/auth/refresh",
                              json={"refresh_token": body["refresh_token"]})).status_code == 200


async def test_public_register_cannot_create_an_admin(client):
    r = await client.post("/auth/register", json={"email": "sneaky@example.com", "full_name": "Sneaky",
                                                   "password": "Passw0rd!x", "role": "admin"})
    assert r.status_code == 201 and r.json()["user"]["role"] == "customer"
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert (await client.get("/admin/orders", headers=h)).status_code == 403


async def test_admin_creates_admin_who_can_log_in(client, admin):
    r = await client.post("/admin/users", headers=admin["headers"], json={
        "email": "Second@Example.com", "full_name": "Second Admin", "password": "Passw0rd!x"})
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "admin" and r.json()["email"] == "second@example.com"
    login = await client.post("/auth/login", json={"email": "second@example.com",
                                                   "password": "Passw0rd!x"})
    assert login.status_code == 200
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await client.get("/admin/orders", headers=h)).status_code == 200
    logs = (await client.get("/admin/audit-logs", headers=admin["headers"],
                             params={"entity_type": "user"})).json()["items"]
    assert logs[0]["action"] == "user.create" and logs[0]["changes"]["role"] == "admin"


async def test_admin_can_create_a_rider(client, admin):
    r = await client.post("/admin/users", headers=admin["headers"], json={
        "email": "rider2@example.com", "full_name": "Rider Two", "password": "Passw0rd!x",
        "phone": "0803 555 6666", "role": "rider"})
    assert r.status_code == 201 and r.json()["role"] == "rider"


async def test_only_admins_can_create_accounts(client, customer):
    body = {"email": "x@example.com", "full_name": "X Person", "password": "Passw0rd!x"}
    assert (await client.post("/admin/users", headers=customer["headers"], json=body)).status_code == 403
    assert (await client.post("/admin/users", json=body)).status_code == 401


async def test_admin_create_rejects_duplicate_email(client, admin):
    body = {"email": "admin@example.com", "full_name": "Dup", "password": "Passw0rd!x"}
    r = await client.post("/admin/users", headers=admin["headers"], json=body)
    assert r.status_code == 409
