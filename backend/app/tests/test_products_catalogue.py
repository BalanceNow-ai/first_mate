"""Public catalogue: filters, stable pagination, vessel fitment and private-vessel isolation."""

from sqlalchemy import update

from app.database import async_session
from app.models.vessel import Vessel
from app.tests.conftest import add_fitment_rule, create_product, create_vessel
from app.tests.test_catalogue_support import API


async def _seed_mix():
    a = await create_product(
        sku="A-1",
        name="Alpha spark plug",
        brand="NGK",
        category="Engine Parts",
        sub_category="Ignition",
        price_cents=1500,
        stock_quantity=5,
        part_role="spark_plug",
        fitment_scope="specific",
        oem_part_numbers=["SYN-OEM-777"],
    )
    b = await create_product(
        sku="B-2",
        name="Bravo fuel filter",
        brand="Yamaha",
        category="Engine Parts",
        sub_category="Fuel System",
        price_cents=4000,
        sale_price_cents=3000,
        stock_quantity=0,
        part_role="fuel_filter",
        fitment_scope="specific",
    )
    c = await create_product(
        sku="C-3",
        name="Charlie zip ties",
        brand="Generic",
        category="General",
        price_cents=900,
        stock_quantity=10,
        part_role="zip_ties",
        fitment_scope="universal",
        description="Assorted UV-stable ties",
    )
    d = await create_product(sku="D-4", name="Delta inactive", category="General", price_cents=500, is_active=False)
    return a, b, c, d


async def test_filters_and_search(client):
    a, b, c, d = await _seed_mix()

    async def ids(**params):
        r = await client.get(f"{API}/products/", params=params)
        assert r.status_code == 200, r.text
        return [i["id"] for i in r.json()["items"]], r.json()

    got, body = await ids()
    assert set(got) == {str(a.id), str(b.id), str(c.id)}  # inactive hidden
    assert body["total"] == 3 and body["vessel"] is None
    assert (await ids(category="general"))[0] == [str(c.id)]
    assert (await ids(sub_category="Fuel System"))[0] == [str(b.id)]
    assert (await ids(brand="ngk"))[0] == [str(a.id)]
    assert set((await ids(min_price_cents=1000, max_price_cents=3000))[0]) == {str(a.id), str(b.id)}  # b on sale @3000
    assert set((await ids(in_stock=True))[0]) == {str(a.id), str(c.id)}
    assert (await ids(in_stock=False))[0] == [str(b.id)]
    assert (await ids(on_sale=True))[0] == [str(b.id)]
    assert (await ids(part_role="zip_ties"))[0] == [str(c.id)]
    assert (await ids(q="uv-stable"))[0] == [str(c.id)]  # description
    assert (await ids(q="b-2"))[0] == [str(b.id)]  # sku
    assert (await ids(q="SYN-OEM-777"))[0] == [str(a.id)]  # OEM part number
    assert (await ids(q="yamaha"))[0] == [str(b.id)]  # brand
    assert (await ids(q="100%"))[0] == []  # LIKE wildcards are escaped
    item = body["items"][0]
    assert {"price_cents", "sale_price_cents", "effective_price_cents", "currency", "in_stock", "fitment"} <= set(item)
    assert item["fitment"] is None


async def test_stable_pagination_and_sorting(client):
    for i in range(7):
        await create_product(sku=f"P-{i}", name="Same name", price_cents=1000 + (i % 3) * 100)
    seen = []
    for offset in range(0, 7, 3):
        r = (await client.get(f"{API}/products/", params={"offset": offset, "limit": 3})).json()
        assert r["total"] == 7 and r["limit"] == 3 and r["offset"] == offset
        seen += [i["id"] for i in r["items"]]
    assert len(seen) == 7 and len(set(seen)) == 7
    prices = [
        i["effective_price_cents"]
        for i in (await client.get(f"{API}/products/", params={"sort": "price_desc", "limit": 100})).json()["items"]
    ]
    assert prices == sorted(prices, reverse=True)
    assert (await client.get(f"{API}/products/", params={"limit": 1000})).json()["limit"] == 100


async def test_vessel_fitment_annotations_and_engine_change(client, customer):
    vessel = await create_vessel(customer.id, engine_make="Yamaha", engine_model="F150")
    fits = await create_product(name="Fits F150", fitment_scope="specific")
    await add_fitment_rule(fits.id, engine_make="Yamaha", engine_model="F150")
    other = await create_product(name="Fits DF140", fitment_scope="specific")
    await add_fitment_rule(other.id, engine_make="Suzuki", engine_model="DF140")
    unverified = await create_product(name="Unverified rule", fitment_scope="specific")
    await add_fitment_rule(unverified.id, verification_status="unverified")
    nothing = await create_product(name="No data", fitment_scope="unspecified")
    universal = await create_product(name="Zip ties", fitment_scope="universal")

    async def statuses(**extra):
        r = await client.get(
            f"{API}/products/", params={"vessel_id": str(vessel.id), "limit": 100, **extra}, headers=customer.headers
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["vessel"]["id"] == str(vessel.id) and "My Stabi" in body["vessel"]["label"]
        return {i["name"]: i["fitment"]["status"] for i in body["items"]}, body

    s, _ = await statuses()
    assert s == {
        "Fits F150": "verified_fit",
        "Fits DF140": "verified_mismatch",
        "Unverified rule": "unknown",
        "No data": "unknown",
        "Zip ties": "universal",
    }
    compat, body = await statuses(compatible_only="true")
    assert set(compat) == {"Fits F150", "Zip ties"} and body["total"] == 2
    assert all(v in ("verified_fit", "universal") for v in compat.values())  # unknown never shown as fit

    async with async_session() as db:
        await db.execute(
            update(Vessel).where(Vessel.id == vessel.id).values(engine_make="Suzuki", engine_model="DF140")
        )
        await db.commit()
    s, _ = await statuses()
    assert s["Fits F150"] == "verified_mismatch" and s["Fits DF140"] == "verified_fit"
    compat, _ = await statuses(compatible_only="true")
    assert set(compat) == {"Fits DF140", "Zip ties"}

    # Detail + fitment endpoints use the same evaluation.
    r = await client.get(f"{API}/products/{other.id}", params={"vessel_id": str(vessel.id)}, headers=customer.headers)
    assert r.json()["fitment"]["status"] == "verified_fit"
    r = await client.get(
        f"{API}/products/{nothing.id}/fitment", params={"vessel_id": str(vessel.id)}, headers=customer.headers
    )
    assert r.status_code == 200 and r.json()["status"] == "unknown" and "unknown" in r.json()["message"].lower()
    assert universal and unverified


async def test_compatible_only_pagination_is_exact(client, customer):
    vessel = await create_vessel(customer.id)
    fitting = []
    for i in range(5):
        p = await create_product(sku=f"FIT-{i}", name=f"Fit {i}", fitment_scope="specific")
        await add_fitment_rule(p.id)
        fitting.append(str(p.id))
        # Candidates that pass the make-only SQL prefilter but fail exact evaluation.
        q = await create_product(sku=f"NOFIT-{i}", name=f"Fit {i} wrong model", fitment_scope="specific")
        await add_fitment_rule(q.id, engine_model="F200")
    seen = []
    for offset in (0, 2, 4):
        r = (
            await client.get(
                f"{API}/products/",
                headers=customer.headers,
                params={"vessel_id": str(vessel.id), "compatible_only": "true", "offset": offset, "limit": 2},
            )
        ).json()
        assert r["total"] == 5
        seen += [i["id"] for i in r["items"]]
    assert sorted(seen) == sorted(fitting)
    r = await client.get(f"{API}/products/", params={"compatible_only": "true"})
    assert r.status_code == 422


async def test_private_vessel_isolation(client, customer, other_customer):
    vessel = await create_vessel(customer.id)
    p = await create_product()
    for path in ("/products/", f"/products/{p.id}", f"/products/{p.id}/fitment", "/search/products"):
        r = await client.get(f"{API}{path}", params={"vessel_id": str(vessel.id)})
        assert r.status_code == 401, (path, r.text)
        r = await client.get(f"{API}{path}", params={"vessel_id": str(vessel.id)}, headers=other_customer.headers)
        assert r.status_code == 404, (path, r.text)
        assert "Stabi" not in r.text
    bad = {"Authorization": "Bearer not-a-token"}
    assert (await client.get(f"{API}/products/", headers=bad)).status_code == 401


async def test_detail_compatibility_categories_and_inactive(client):
    p = await create_product(
        name="Impeller",
        oem_part_numbers=["SYN-IMP-1"],
        fitment_scope="specific",
        category="Engine Parts",
        sub_category="Cooling",
        brand="Yamaha",
    )
    await add_fitment_rule(p.id, engine_make="Yamaha", engine_model="F150")
    await add_fitment_rule(p.id, engine_make="Yamaha", engine_model="F200", verification_status="unverified")
    await add_fitment_rule(p.id, engine_make="Yamaha", engine_model="F250", confidence_score=0.5)
    inactive = await create_product(is_active=False, category="Hidden")
    r = await client.get(f"{API}/products/{p.id}/compatibility")
    body = r.json()
    assert r.status_code == 200 and body["oem_part_numbers"] == ["SYN-IMP-1"]
    assert [k["engine_model"] for k in body["known_to_fit"]] == ["F150"]
    assert body["known_to_fit"][0]["is_synthetic"] is True
    for path in (f"/products/{inactive.id}", f"/products/{inactive.id}/compatibility"):
        assert (await client.get(f"{API}{path}")).status_code == 404
    cats = (await client.get(f"{API}/products/categories")).json()
    assert cats == [{"category": "Engine Parts", "count": 1, "sub_categories": [{"name": "Cooling", "count": 1}]}]
    assert (await client.get(f"{API}/products/brands")).json() == [{"brand": "Yamaha", "count": 1}]
    r = await client.get(f"{API}/products/{p.id}")
    assert r.status_code == 200 and r.json()["fitment"] is None
