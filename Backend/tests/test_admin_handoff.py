"""An admin who signs in on the shop is passed to the dashboard with a one-time code."""


async def test_admin_code_gives_a_working_dashboard_session_once(client, admin):
    code = (await client.post("/auth/handoff", headers=admin["headers"])).json()["code"]
    r = await client.post("/auth/handoff/redeem", json={"code": code})
    assert r.status_code == 200
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert (await client.get("/admin/deliveries/board", headers=headers)).status_code == 200
    # single use
    assert (await client.post("/auth/handoff/redeem", json={"code": code})).status_code == 401


async def test_customers_cannot_get_a_code(client, customer):
    assert (await client.post("/auth/handoff", headers=customer["headers"])).status_code == 403
    assert (await client.post("/auth/handoff")).status_code == 401


async def test_made_up_code_is_refused(client):
    assert (await client.post("/auth/handoff/redeem", json={"code": "nope"})).status_code == 401


async def test_code_stops_working_when_the_admin_is_demoted(client, admin):
    from app.db.session import AsyncSessionLocal
    from app.models import User, UserRole

    code = (await client.post("/auth/handoff", headers=admin["headers"])).json()["code"]
    async with AsyncSessionLocal() as s:
        user = await s.get(User, __import__("uuid").UUID(admin["id"]))
        user.role = UserRole.CUSTOMER
        s.add(user)
        await s.commit()
    assert (await client.post("/auth/handoff/redeem", json={"code": code})).status_code == 401
