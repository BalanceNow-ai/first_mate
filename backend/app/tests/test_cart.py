"""Cart validation through the shared cart service."""

from app.services import cart_service
from app.tests.conftest import create_product


async def test_add_uses_sale_price_and_validates(client, customer):
    p = await create_product(price_cents=10000, sale_price_cents=7999, stock_quantity=3)
    r = await client.post("/api/v1/cart/items", json={"product_id": str(p.id), "quantity": 2}, headers=customer.headers)
    assert r.status_code == 201, r.text
    cart = r.json()
    assert cart["items"][0]["unit_price_cents"] == 7999
    assert cart["subtotal_cents"] == 15998 and cart["currency"] == "NZD"
    # Aggregate quantity cannot exceed stock.
    r = await client.post("/api/v1/cart/items", json={"product_id": str(p.id), "quantity": 2}, headers=customer.headers)
    assert r.status_code == 409 and r.json()["code"] == "insufficient_stock"
    for qty in (0, -1, 100):
        r = await client.post(
            "/api/v1/cart/items", json={"product_id": str(p.id), "quantity": qty}, headers=customer.headers
        )
        assert r.status_code == 422


async def test_inactive_product_rejected_and_flagged(client, customer, db_session):
    p = await create_product(is_active=False)
    r = await client.post("/api/v1/cart/items", json={"product_id": str(p.id)}, headers=customer.headers)
    assert r.status_code == 404
    q = await create_product(stock_quantity=5)
    await client.post("/api/v1/cart/items", json={"product_id": str(q.id), "quantity": 5}, headers=customer.headers)
    await db_session.execute(
        __import__("sqlalchemy").update(type(q)).where(type(q).id == q.id).values(stock_quantity=2)
    )
    await db_session.commit()
    cart = (await client.get("/api/v1/cart/", headers=customer.headers)).json()
    assert cart["has_issues"] and cart["items"][0]["issues"] == ["insufficient_stock"]


async def test_update_remove_and_isolation(client, customer, other_customer):
    p = await create_product(stock_quantity=10)
    cart = (await client.post("/api/v1/cart/items", json={"product_id": str(p.id)}, headers=customer.headers)).json()
    item_id = cart["items"][0]["id"]
    assert (await client.patch(f"/api/v1/cart/items/{item_id}", json={"quantity": 4}, headers=customer.headers)).json()[
        "item_count"
    ] == 4
    assert (
        await client.patch(f"/api/v1/cart/items/{item_id}", json={"quantity": 11}, headers=customer.headers)
    ).status_code == 409
    # Other customers cannot touch this line.
    assert (
        await client.patch(f"/api/v1/cart/items/{item_id}", json={"quantity": 1}, headers=other_customer.headers)
    ).status_code == 404
    await client.delete(f"/api/v1/cart/items/{item_id}", headers=other_customer.headers)
    assert (await client.get("/api/v1/cart/", headers=customer.headers)).json()["item_count"] == 4
    assert (await client.delete(f"/api/v1/cart/items/{item_id}", headers=customer.headers)).json()["items"] == []


async def test_ensure_quantities_is_idempotent_and_stock_safe(db_session, customer):
    a = await create_product(stock_quantity=10)
    b = await create_product(stock_quantity=1)
    first = await cart_service.ensure_quantities(db_session, customer.id, [(a.id, 2), (b.id, 3)])
    await db_session.commit()
    statuses = {line.product_id: line.status for line in first.lines}
    assert statuses[a.id] == "added" and statuses[b.id] == "limited"
    second = await cart_service.ensure_quantities(db_session, customer.id, [(a.id, 2), (b.id, 3)])
    await db_session.commit()
    assert all(line.added == 0 for line in second.lines)
    items = {i.product_id: i.quantity for i in await cart_service.load_cart(db_session, customer.id)}
    assert items == {a.id: 2, b.id: 1}
