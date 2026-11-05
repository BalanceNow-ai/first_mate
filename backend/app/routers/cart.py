"""Shopping cart router. All mutations go through ``app.services.cart_service``."""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import mutation_limit
from app.database import get_db
from app.middleware.auth import CurrentUserId
from app.models.cart import CartItem
from app.schemas.cart import CartItemCreate, CartItemResponse, CartItemUpdate, CartResponse
from app.services import cart_service
from app.services.catalogue import cart_product_summary
from app.services.pricing import effective_price_cents

router = APIRouter(prefix="/cart", tags=["Cart"])


def _item_response(item: CartItem) -> CartItemResponse:
    unit = effective_price_cents(item.product)
    return CartItemResponse(
        id=item.id,
        product_id=item.product_id,
        quantity=item.quantity,
        unit_price_cents=unit,
        line_total_cents=unit * item.quantity,
        product=cart_product_summary(item.product),
        issues=cart_service.line_issues(item),
        created_at=item.created_at,
    )


async def build_cart_response(db: AsyncSession, user_id: uuid.UUID) -> CartResponse:
    items = await cart_service.load_cart(db, user_id)
    lines = [_item_response(i) for i in items]
    return CartResponse(
        items=lines,
        subtotal_cents=sum(line.line_total_cents for line in lines),
        item_count=sum(line.quantity for line in lines),
        has_issues=any(line.issues for line in lines),
    )


@router.get("/", response_model=CartResponse)
async def get_cart(user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")) -> CartResponse:
    """The current user's cart with server-computed prices and per-line issues."""
    return await build_cart_response(db, user_id)


@router.post(
    "/items",
    response_model=CartResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(mutation_limit())],
)
async def add_to_cart(
    item: CartItemCreate, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> CartResponse:
    """Add a product (validated: active, quantity bounds, aggregate stock)."""
    await cart_service.add_item(db, user_id, item.product_id, item.quantity)
    return await build_cart_response(db, user_id)


@router.patch("/items/{item_id}", response_model=CartResponse, dependencies=[Depends(mutation_limit())])
async def update_cart_item(
    item_id: uuid.UUID, updates: CartItemUpdate, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> CartResponse:
    """Set the quantity of a cart line."""
    await cart_service.set_quantity(db, user_id, item_id, updates.quantity)
    return await build_cart_response(db, user_id)


@router.delete("/items/{item_id}", response_model=CartResponse, dependencies=[Depends(mutation_limit())])
async def remove_from_cart(
    item_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> CartResponse:
    """Remove a line from the cart (no error if already removed)."""
    await db.execute(delete(CartItem).where(CartItem.id == item_id, CartItem.user_id == user_id))
    return await build_cart_response(db, user_id)


@router.delete("/", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(mutation_limit())])
async def clear_cart(user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")) -> None:
    """Remove every line from the cart."""
    await db.execute(delete(CartItem).where(CartItem.user_id == user_id))
