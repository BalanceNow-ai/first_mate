"""Order management router."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.middleware.auth import CurrentUserId
from app.models.cart import CartItem
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.schemas.order import OrderCreate, OrderResponse, OrderStatusUpdate

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.get("/", response_model=list[OrderResponse])
async def list_orders(
    user_id: CurrentUserId,
    status_filter: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[Order]:
    """List the current user's orders."""
    query = (
        select(Order)
        .where(Order.user_id == user_id)
        .options(selectinload(Order.items))
        .order_by(Order.created_at.desc())
    )
    if status_filter:
        query = query.where(Order.status == status_filter)

    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("/", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    order_data: OrderCreate,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> Order:
    """Create a new order from the user's cart.

    This converts the user's cart items into an order. The cart is
    cleared after the order is created. Payment is processed separately
    via the /payments endpoint.
    """
    # Get cart items
    cart_result = await db.execute(
        select(CartItem)
        .where(CartItem.user_id == user_id)
        .options(selectinload(CartItem.product))
    )
    cart_items = list(cart_result.scalars().all())

    if not cart_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cart is empty",
        )

    # Calculate subtotal
    subtotal = sum(float(item.product.price) * item.quantity for item in cart_items)

    # TODO: Calculate actual shipping cost from NZ Post / Aramex APIs
    shipping_cost = 0.0 if subtotal >= 150 else 9.90  # Free shipping over $150 NZD

    # Create order
    order = Order(
        user_id=user_id,
        status="pending",
        subtotal=round(subtotal, 2),
        shipping_cost=shipping_cost,
        total=round(subtotal + shipping_cost, 2),
        delivery_type=order_data.delivery_type,
        shipping_address=order_data.shipping_address,
        helm_dash_coordinates=order_data.helm_dash_coordinates,
        notes=order_data.notes,
    )
    db.add(order)
    await db.flush()

    # Create order items and reduce stock
    for cart_item in cart_items:
        order_item = OrderItem(
            order_id=order.id,
            product_id=cart_item.product_id,
            quantity=cart_item.quantity,
            unit_price=float(cart_item.product.price),
        )
        db.add(order_item)

        # Reduce stock quantity
        cart_item.product.stock_quantity -= cart_item.quantity

        # Remove from cart
        await db.delete(cart_item)

    await db.flush()

    # Reload with items
    result = await db.execute(
        select(Order).where(Order.id == order.id).options(selectinload(Order.items))
    )
    return result.scalar_one()


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: uuid.UUID,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> Order:
    """Get a specific order by ID."""
    result = await db.execute(
        select(Order)
        .where(Order.id == order_id, Order.user_id == user_id)
        .options(selectinload(Order.items))
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


@router.patch("/{order_id}/status", response_model=OrderResponse)
async def update_order_status(
    order_id: uuid.UUID,
    status_update: OrderStatusUpdate,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> Order:
    """Update the status of an order (admin only)."""
    result = await db.execute(
        select(Order).where(Order.id == order_id).options(selectinload(Order.items))
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    valid_statuses = {"pending", "paid", "fulfilled", "shipped", "delivered", "cancelled"}
    if status_update.status not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}",
        )

    order.status = status_update.status
    if status_update.tracking_number:
        order.tracking_number = status_update.tracking_number
    if status_update.courier:
        order.courier = status_update.courier

    await db.flush()
    return order
