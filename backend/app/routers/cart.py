"""Shopping cart router."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.middleware.auth import CurrentUserId
from app.models.cart import CartItem
from app.models.product import Product
from app.schemas.cart import CartItemCreate, CartItemUpdate, CartResponse

router = APIRouter(prefix="/cart", tags=["Cart"])


@router.get("/", response_model=CartResponse)
async def get_cart(
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> CartResponse:
    """Get the current user's cart."""
    result = await db.execute(
        select(CartItem)
        .where(CartItem.user_id == user_id)
        .options(selectinload(CartItem.product))
        .order_by(CartItem.created_at)
    )
    items = list(result.scalars().all())

    subtotal = sum(float(item.product.price) * item.quantity for item in items)
    return CartResponse(
        items=items,
        subtotal=round(subtotal, 2),
        item_count=sum(item.quantity for item in items),
    )


@router.post("/items", status_code=status.HTTP_201_CREATED)
async def add_to_cart(
    item_data: CartItemCreate,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Add a product to the cart. If already in cart, increment quantity."""
    # Verify product exists and is in stock
    product_result = await db.execute(
        select(Product).where(Product.id == item_data.product_id, Product.is_active.is_(True))
    )
    product = product_result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    if product.stock_quantity < item_data.quantity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient stock. Only {product.stock_quantity} available.",
        )

    # Check if item already in cart
    existing_result = await db.execute(
        select(CartItem).where(
            CartItem.user_id == user_id, CartItem.product_id == item_data.product_id
        )
    )
    existing = existing_result.scalar_one_or_none()

    if existing:
        existing.quantity += item_data.quantity
    else:
        cart_item = CartItem(
            user_id=user_id,
            product_id=item_data.product_id,
            quantity=item_data.quantity,
        )
        db.add(cart_item)

    await db.flush()
    return {"message": "Item added to cart"}


@router.patch("/items/{item_id}")
async def update_cart_item(
    item_id: uuid.UUID,
    updates: CartItemUpdate,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update the quantity of an item in the cart."""
    result = await db.execute(
        select(CartItem).where(CartItem.id == item_id, CartItem.user_id == user_id)
    )
    cart_item = result.scalar_one_or_none()
    if not cart_item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found")

    cart_item.quantity = updates.quantity
    await db.flush()
    return {"message": "Cart item updated"}


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_cart(
    item_id: uuid.UUID,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove an item from the cart."""
    result = await db.execute(
        select(CartItem).where(CartItem.id == item_id, CartItem.user_id == user_id)
    )
    cart_item = result.scalar_one_or_none()
    if not cart_item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found")

    await db.delete(cart_item)
    await db.flush()


@router.delete("/", status_code=status.HTTP_204_NO_CONTENT)
async def clear_cart(
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Clear all items from the cart."""
    result = await db.execute(select(CartItem).where(CartItem.user_id == user_id))
    for item in result.scalars().all():
        await db.delete(item)
    await db.flush()
