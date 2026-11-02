"""Admins put products on sale by percentage, one at a time or in bulk."""


async def _product(client, slug="tomatoes"):
    return (await client.get(f"/products/{slug}")).json()


async def test_discount_comes_off_the_normal_price_and_does_not_stack(client, shop, admin):
    # tomatoes: price 2500, normal price 3000
    r = await client.post("/admin/products/discount", headers=admin["headers"],
                          json={"percent": 10, "product_ids": [str(shop["tomato"])]})
    assert r.status_code == 200 and r.json()["updated"] == 1
    p = await _product(client)
    assert p["price"] == 2700.0 and p["compare_at_price"] == 3000.0 and p["discount_percent"] == 10

    await client.post("/admin/products/discount", headers=admin["headers"],
                      json={"percent": 20, "product_ids": [str(shop["tomato"])]})
    p = await _product(client)
    assert p["price"] == 2400.0 and p["compare_at_price"] == 3000.0 and p["discount_percent"] == 20


async def test_zero_ends_the_discount(client, shop, admin):
    await client.post("/admin/products/discount", headers=admin["headers"],
                      json={"percent": 0, "product_ids": [str(shop["tomato"])]})
    p = await _product(client)
    assert p["price"] == 3000.0 and p["compare_at_price"] is None and p["discount_percent"] is None


async def test_whole_shop_and_category(client, shop, admin):
    r = await client.post("/admin/products/discount", headers=admin["headers"], json={"percent": 10})
    assert r.json()["updated"] == 3
    for item in (await client.get("/products")).json()["items"]:
        assert item["discount_percent"] == 10

    cats = {c["slug"]: c["id"] for c in (await client.get("/categories")).json()}
    r = await client.post("/admin/products/discount", headers=admin["headers"],
                          json={"percent": 25, "category_id": cats["fruits"]})
    assert r.json()["updated"] == 1
    items = {p["slug"]: p for p in (await client.get("/products")).json()["items"]}
    assert items["mango"]["discount_percent"] == 25 and items["rice"]["discount_percent"] == 10


async def test_percent_shown_matches_what_the_admin_typed_after_rounding(client, shop, admin):
    pid = str(shop["tomato"])
    await client.patch(f"/admin/products/{pid}", headers=admin["headers"],
                       json={"price": 1001, "compare_at_price": None})
    await client.post("/admin/products/discount", headers=admin["headers"],
                      json={"percent": 15, "product_ids": [pid]})
    p = await _product(client)
    assert p["price"] == 851.0 and p["discount_percent"] == 15


async def test_only_admins_and_sensible_percentages(client, shop, admin, customer):
    assert (await client.post("/admin/products/discount", json={"percent": 10})).status_code == 401
    r = await client.post("/admin/products/discount", headers=customer["headers"], json={"percent": 10})
    assert r.status_code == 403
    for bad in (-1, 91, 10.5):
        r = await client.post("/admin/products/discount", headers=admin["headers"], json={"percent": bad})
        assert r.status_code == 422
    assert (await _product(client))["price"] == 2500.0


async def test_new_customers_pay_the_discounted_price(client, shop, admin):
    await client.post("/admin/products/discount", headers=admin["headers"],
                      json={"percent": 50, "product_ids": [str(shop["tomato"])]})
    await client.get("/products")
    assert (await _product(client))["price"] == 1500.0
