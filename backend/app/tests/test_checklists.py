"""Tests for the Voyage Checklist API."""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.checklist import ChecklistItem, VoyageChecklist
from app.models.product import Product
from app.tests.conftest import TEST_USER_ID


@pytest.mark.asyncio
async def test_generate_checklists(client: AsyncClient, test_user, test_vessel):
    """Test generating default voyage checklists for a vessel."""
    response = await client.post(f"/api/v1/checklists/vessel/{test_vessel.id}/generate")
    assert response.status_code == 201
    data = response.json()
    assert data["message"] == "Checklists generated"
    assert len(data["checklists"]) == 3

    tiers = {c["tier"] for c in data["checklists"]}
    assert "grab_and_go" in tiers
    assert "coastal_cruising" in tiers
    assert "offshore_passage" in tiers


@pytest.mark.asyncio
async def test_get_vessel_checklists(client: AsyncClient, test_user, test_vessel):
    """Test retrieving checklists for a vessel."""
    # Generate first
    await client.post(f"/api/v1/checklists/vessel/{test_vessel.id}/generate")

    response = await client.get(f"/api/v1/checklists/vessel/{test_vessel.id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3

    # Verify items exist
    grab_and_go = next(c for c in data if c["tier"] == "grab_and_go")
    assert len(grab_and_go["items"]) > 0


@pytest.mark.asyncio
async def test_duplicate_generate_fails(client: AsyncClient, test_user, test_vessel):
    """Test that generating checklists twice fails."""
    await client.post(f"/api/v1/checklists/vessel/{test_vessel.id}/generate")
    response = await client.post(f"/api/v1/checklists/vessel/{test_vessel.id}/generate")
    assert response.status_code == 409


# --- Phase 5: Product search & linking tests ---


@pytest.mark.asyncio
async def test_generate_links_matching_product(
    client: AsyncClient, db_session: AsyncSession, test_user, test_vessel
):
    """When a product name matches a checklist item, product_id should be set."""
    # Create a product whose name matches "Spark Plugs" from the Grab & Go list
    product = Product(
        sku="SP-001",
        name="Spare Spark Plugs Set",
        category="Engine Parts",
        price=29.99,
        stock_quantity=20,
    )
    db_session.add(product)
    await db_session.commit()

    response = await client.post(f"/api/v1/checklists/vessel/{test_vessel.id}/generate")
    assert response.status_code == 201
    data = response.json()
    assert data["products_linked"] >= 1

    # Verify the item has product_id set
    checklists_resp = await client.get(
        f"/api/v1/checklists/vessel/{test_vessel.id}"
    )
    all_items = []
    for c in checklists_resp.json():
        all_items.extend(c["items"])

    spark_plug_items = [i for i in all_items if "Spark Plug" in i["item_name"]]
    assert any(i["product_id"] is not None for i in spark_plug_items)


@pytest.mark.asyncio
async def test_generate_no_link_for_ambiguous_matches(
    client: AsyncClient, db_session: AsyncSession, test_user, test_vessel
):
    """When multiple products match, no product_id should be set (ambiguous)."""
    for i in range(3):
        product = Product(
            sku=f"FUSE-{i}",
            name=f"Assorted Fuses Pack {i + 1}",
            category="Electrical",
            price=9.99 + i,
            stock_quantity=10,
        )
        db_session.add(product)
    await db_session.commit()

    response = await client.post(f"/api/v1/checklists/vessel/{test_vessel.id}/generate")
    assert response.status_code == 201

    # The fuse items should NOT be linked (3 ambiguous matches)
    checklists_resp = await client.get(
        f"/api/v1/checklists/vessel/{test_vessel.id}"
    )
    all_items = []
    for c in checklists_resp.json():
        all_items.extend(c["items"])

    fuse_items = [i for i in all_items if "Fuse" in i["item_name"]]
    # All fuse items should have no product_id due to ambiguity
    for item in fuse_items:
        assert item["product_id"] is None


@pytest.mark.asyncio
async def test_toggle_checklist_item(client: AsyncClient, test_user, test_vessel):
    """Test toggling checked state of a checklist item."""
    await client.post(f"/api/v1/checklists/vessel/{test_vessel.id}/generate")

    # Get checklists and find an item
    checklists_resp = await client.get(
        f"/api/v1/checklists/vessel/{test_vessel.id}"
    )
    first_item = checklists_resp.json()[0]["items"][0]
    item_id = first_item["id"]
    assert first_item["is_checked"] is False

    # Toggle it
    toggle_resp = await client.patch(f"/api/v1/checklists/items/{item_id}/toggle")
    assert toggle_resp.status_code == 200
    assert toggle_resp.json()["is_checked"] is True

    # Toggle back
    toggle_resp2 = await client.patch(f"/api/v1/checklists/items/{item_id}/toggle")
    assert toggle_resp2.status_code == 200
    assert toggle_resp2.json()["is_checked"] is False


@pytest.mark.asyncio
async def test_link_product_to_item(
    client: AsyncClient, db_session: AsyncSession, test_user, test_vessel, test_product
):
    """Test manually linking a product to a checklist item."""
    await client.post(f"/api/v1/checklists/vessel/{test_vessel.id}/generate")

    checklists_resp = await client.get(
        f"/api/v1/checklists/vessel/{test_vessel.id}"
    )
    first_item = checklists_resp.json()[0]["items"][0]
    item_id = first_item["id"]

    resp = await client.patch(
        f"/api/v1/checklists/items/{item_id}/link-product",
        json={"product_id": str(test_product.id)},
    )
    assert resp.status_code == 200
    assert resp.json()["product_id"] == str(test_product.id)


@pytest.mark.asyncio
async def test_link_product_nonexistent_product(
    client: AsyncClient, test_user, test_vessel
):
    """Linking a non-existent product should 404."""
    await client.post(f"/api/v1/checklists/vessel/{test_vessel.id}/generate")

    checklists_resp = await client.get(
        f"/api/v1/checklists/vessel/{test_vessel.id}"
    )
    item_id = checklists_resp.json()[0]["items"][0]["id"]

    fake_id = str(uuid.uuid4())
    resp = await client.patch(
        f"/api/v1/checklists/items/{item_id}/link-product",
        json={"product_id": fake_id},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_add_unchecked_to_cart(
    client: AsyncClient, db_session: AsyncSession, test_user, test_vessel, test_product
):
    """Test adding unchecked items with linked products to the cart."""
    await client.post(f"/api/v1/checklists/vessel/{test_vessel.id}/generate")

    # Link a product to the first item
    checklists_resp = await client.get(
        f"/api/v1/checklists/vessel/{test_vessel.id}"
    )
    first_item = checklists_resp.json()[0]["items"][0]
    item_id = first_item["id"]

    await client.patch(
        f"/api/v1/checklists/items/{item_id}/link-product",
        json={"product_id": str(test_product.id)},
    )

    # Add unchecked items to cart
    resp = await client.post(
        f"/api/v1/checklists/vessel/{test_vessel.id}/add-unchecked-to-cart"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["added_count"] >= 1

    # Verify item is in cart
    cart_resp = await client.get("/api/v1/cart/")
    assert cart_resp.status_code == 200
    cart_items = cart_resp.json()["items"]
    product_ids = [item["product_id"] for item in cart_items]
    assert str(test_product.id) in product_ids


@pytest.mark.asyncio
async def test_add_unchecked_to_cart_no_linked_items(
    client: AsyncClient, test_user, test_vessel
):
    """When no items have linked products, nothing should be added."""
    await client.post(f"/api/v1/checklists/vessel/{test_vessel.id}/generate")

    resp = await client.post(
        f"/api/v1/checklists/vessel/{test_vessel.id}/add-unchecked-to-cart"
    )
    assert resp.status_code == 200
    assert resp.json()["added_count"] == 0


@pytest.mark.asyncio
async def test_add_unchecked_skips_checked_items(
    client: AsyncClient, db_session: AsyncSession, test_user, test_vessel
):
    """Checked items should not be added to cart even if they have linked products."""
    # Use a product with a unique name that won't auto-match any checklist items
    unique_product = Product(
        sku="UNIQUE-001",
        name="Zebra Widget XYZ",
        category="Accessories",
        price=19.99,
        stock_quantity=10,
    )
    db_session.add(unique_product)
    await db_session.commit()

    await client.post(f"/api/v1/checklists/vessel/{test_vessel.id}/generate")

    checklists_resp = await client.get(
        f"/api/v1/checklists/vessel/{test_vessel.id}"
    )
    first_item = checklists_resp.json()[0]["items"][0]
    item_id = first_item["id"]

    # Link product and then check the item
    await client.patch(
        f"/api/v1/checklists/items/{item_id}/link-product",
        json={"product_id": str(unique_product.id)},
    )
    await client.patch(f"/api/v1/checklists/items/{item_id}/toggle")

    # Add unchecked - should skip the checked item
    resp = await client.post(
        f"/api/v1/checklists/vessel/{test_vessel.id}/add-unchecked-to-cart"
    )
    assert resp.status_code == 200
    # The single linked item was checked, so nothing should be added
    assert resp.json()["added_count"] == 0


@pytest.mark.asyncio
async def test_products_linked_count_in_generate(
    client: AsyncClient, db_session: AsyncSession, test_user, test_vessel
):
    """The generate response should report the number of products linked."""
    # No products exist => 0 linked
    response = await client.post(f"/api/v1/checklists/vessel/{test_vessel.id}/generate")
    data = response.json()
    assert "products_linked" in data
    assert data["products_linked"] == 0
