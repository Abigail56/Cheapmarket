async def test_admin_changes_are_audited(client, shop, admin):
    h = admin["headers"]
    r = await client.patch(f"/admin/products/{shop['tomato']}", headers=h,
                           json={"price": "2600", "name": "Fresh Tomatoes"})
    assert r.status_code == 200
    await client.post(f"/admin/products/{shop['tomato']}/stock", headers=h, json={"delta": 5})

    logs = (await client.get("/admin/audit-logs", headers=h,
                             params={"entity_type": "product"})).json()
    assert logs["total"] == 2
    stock, update = logs["items"]  # newest first
    assert update["action"] == "product.update" and update["actor_id"] == admin["id"]
    assert update["entity_id"] == str(shop["tomato"])
    assert update["changes"] == {"price": [2500.0, 2600.0], "name": ["Tomatoes", "Fresh Tomatoes"]}
    assert stock["action"] == "product.stock" and stock["changes"] == {"stock_qty": [10, 15]}


async def test_rejected_change_leaves_no_audit_entry(client, shop, admin):
    h = admin["headers"]
    r = await client.patch(f"/admin/products/{shop['tomato']}", headers=h,
                           json={"compare_at_price": "100"})  # below price: rejected
    assert r.status_code == 400
    assert (await client.get("/admin/audit-logs", headers=h)).json()["total"] == 0


async def test_order_and_user_actions_are_audited(client, shop, admin, customer):
    from tests.conftest import add_to_cart, checkout_body
    h = admin["headers"]
    cart = await add_to_cart(client, shop["tomato"], 1)
    order = (await client.post("/orders", json=checkout_body(shop),
                               headers={"X-Cart-Session": cart["session_id"]})).json()["order"]
    await client.patch(f"/admin/orders/{order['order_number']}/status", headers=h,
                       json={"status": "confirmed", "note": "called customer"})
    await client.patch(f"/admin/users/{customer['id']}", headers=h, json={"is_active": False})

    logs = {i["action"]: i for i in (await client.get("/admin/audit-logs", headers=h)).json()["items"]}
    assert logs["order.status"]["entity_id"] == order["order_number"]
    assert logs["order.status"]["changes"] == {"status": ["pending", "confirmed"],
                                               "note": "called customer"}
    assert logs["user.update"]["changes"] == {"is_active": [True, False]}
    assert "password_hash" not in str(logs)


async def test_audit_log_is_admin_only(client, customer):
    assert (await client.get("/admin/audit-logs", headers=customer["headers"])).status_code == 403
