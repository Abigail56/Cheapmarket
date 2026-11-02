"""Delivery areas and categories, as the admin dashboard uses them."""


async def test_delivery_area_can_be_renamed_and_its_rules_changed(client, shop, admin):
    h = admin["headers"]
    zone = str(shop["zone"])
    r = await client.patch(f"/admin/zones/{zone}", headers=h,
                           json={"name": "Ikeja", "delivery_fee": 2000, "free_delivery_min": None, "is_active": True})
    assert r.status_code == 200
    public = (await client.get("/delivery-zones")).json()
    assert public[0]["name"] == "Ikeja" and public[0]["delivery_fee"] == 2000.0
    assert public[0]["free_delivery_min"] is None


async def test_renaming_to_a_taken_name_is_refused_politely(client, shop, admin):
    h = admin["headers"]
    other = (await client.post("/admin/zones", headers=h, json={"name": "Lekki", "delivery_fee": 3000})).json()
    r = await client.patch(f"/admin/zones/{shop['zone']}", headers=h, json={"name": "Lekki"})
    assert r.status_code == 409
    # saving an area without changing its name is fine
    assert (await client.patch(f"/admin/zones/{other['id']}", headers=h, json={"name": "Lekki"})).status_code == 200


async def test_turned_off_area_leaves_checkout(client, shop, admin):
    r = await client.patch(f"/admin/zones/{shop['zone']}", headers=admin["headers"], json={"is_active": False})
    assert r.status_code == 200
    assert (await client.get("/delivery-zones")).json() == []


async def test_category_with_products_cannot_be_deleted(client, shop, admin):
    h = admin["headers"]
    cats = {c["slug"]: c["id"] for c in (await client.get("/categories")).json()}
    r = await client.delete(f"/admin/categories/{cats['fruits']}", headers=h)
    assert r.status_code == 409 and "another category" in r.json()["error"]["message"]
    empty = (await client.post("/admin/categories", headers=h, json={"name": "Drinks"})).json()
    assert (await client.delete(f"/admin/categories/{empty['id']}", headers=h)).status_code == 204
