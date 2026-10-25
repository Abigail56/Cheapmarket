async def test_list_and_paginate(client, shop):
    r = await client.get("/products", params={"size": 2})
    d = r.json()
    assert d["total"] == 3 and d["pages"] == 2 and len(d["items"]) == 2


async def test_hides_exact_stock_but_shows_in_stock(client, shop):
    items = {p["slug"]: p for p in (await client.get("/products")).json()["items"]}
    assert "stock_qty" not in items["tomatoes"]
    assert items["tomatoes"]["in_stock"] is True and items["mango"]["in_stock"] is False
    assert items["tomatoes"]["discount_percent"] == 16
    assert items["tomatoes"]["price"] == 2500.0  # JSON number, not string


async def test_filters_and_sorting(client, shop):
    veg = (await client.get("/products", params={"category": "vegetables"})).json()
    assert {p["slug"] for p in veg["items"]} == {"tomatoes", "rice"}
    q = (await client.get("/products", params={"q": "ric"})).json()
    assert [p["slug"] for p in q["items"]] == ["rice"]
    cheap = (await client.get("/products", params={"max_price": 3000, "sort": "price_asc"})).json()
    assert [p["slug"] for p in cheap["items"]] == ["mango", "tomatoes"]
    stock = (await client.get("/products", params={"in_stock_only": True})).json()
    assert "mango" not in {p["slug"] for p in stock["items"]}
    feat = (await client.get("/products", params={"featured": True})).json()
    assert [p["slug"] for p in feat["items"]] == ["tomatoes"]
    assert (await client.get("/products", params={"category": "nope"})).status_code == 404


async def test_product_detail_and_404(client, shop):
    assert (await client.get("/products/tomatoes")).json()["category"]["slug"] == "vegetables"
    assert (await client.get("/products/missing")).status_code == 404


async def test_categories_and_zones(client, shop):
    cats = (await client.get("/categories")).json()
    assert {c["slug"] for c in cats} == {"vegetables", "fruits"}
    zones = (await client.get("/delivery-zones")).json()
    assert zones[0]["delivery_fee"] == 1500.0


async def test_cache_is_invalidated_when_admin_edits(client, shop, admin):
    first = (await client.get("/products/tomatoes")).json()
    await client.get("/products")  # warm the list cache
    pid = str(shop["tomato"])
    r = await client.patch(f"/admin/products/{pid}", headers=admin["headers"], json={"price": 2000})
    assert r.status_code == 200
    items = {p["slug"]: p for p in (await client.get("/products")).json()["items"]}
    assert items["tomatoes"]["price"] == 2000.0
    assert first["price"] == 2500.0
