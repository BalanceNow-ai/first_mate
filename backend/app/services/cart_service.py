"""Cart rules shared by the cart API, checklist bulk-add and First Mate cart actions.

Every entry point validates: product exists and is active, quantity is positive and
bounded, and the aggregate quantity in the cart does not exceed available stock.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.models.cart import CartItem
from app.models.product import Product
from app.services.pricing import effective_price_cents

MAX_LINE_QUANTITY = 99


@dataclass
class CartLineResult:
    product_id: uuid.UUID
    requested: int
    added: int
    quantity_in_cart: int
    status: str  # added | already_satisfied | insufficient_stock | unavailable | limited
    message: str | None = None


@dataclass
class BulkAddResult:
    lines: list[CartLineResult] = field(default_factory=list)

    @property
    def added_count(self) -> int:
        return sum(1 for line in self.lines if line.added > 0)


async def _get_product(db: AsyncSession, product_id: uuid.UUID) -> Product | None:
    return (await db.execute(select(Product).where(Product.id == product_id))).scalar_one_or_none()


async def _get_line(db: AsyncSession, user_id: uuid.UUID, product_id: uuid.UUID) -> CartItem | None:
    return (
        await db.execute(
            select(CartItem).where(CartItem.user_id == user_id, CartItem.product_id == product_id).with_for_update()
        )
    ).scalar_one_or_none()


def _validate_quantity(quantity: int) -> None:
    if quantity < 1 or quantity > MAX_LINE_QUANTITY:
        raise AppError(422, "invalid_quantity", f"Quantity must be between 1 and {MAX_LINE_QUANTITY}")


async def add_item(db: AsyncSession, user_id: uuid.UUID, product_id: uuid.UUID, quantity: int) -> CartItem:
    """Add ``quantity`` to the cart line (raises AppError on any rule violation)."""
    _validate_quantity(quantity)
    product = await _get_product(db, product_id)
    if product is None or not product.is_active:
        raise AppError(404, "product_unavailable", "This product is not available")
    line = await _get_line(db, user_id, product_id)
    new_qty = (line.quantity if line else 0) + quantity
    if new_qty > MAX_LINE_QUANTITY:
        raise AppError(422, "invalid_quantity", f"A cart line is limited to {MAX_LINE_QUANTITY}")
    if new_qty > product.stock_quantity:
        raise AppError(
            409,
            "insufficient_stock",
            f"Only {product.stock_quantity} available",
            extra={"available_quantity": product.stock_quantity},
        )
    if line is None:
        line = CartItem(user_id=user_id, product_id=product_id, quantity=new_qty)
        db.add(line)
    else:
        line.quantity = new_qty
    await db.flush()
    return line


async def set_quantity(db: AsyncSession, user_id: uuid.UUID, item_id: uuid.UUID, quantity: int) -> CartItem:
    _validate_quantity(quantity)
    line = (
        await db.execute(select(CartItem).where(CartItem.id == item_id, CartItem.user_id == user_id).with_for_update())
    ).scalar_one_or_none()
    if line is None:
        raise AppError(404, "not_found", "Cart item not found")
    product = await _get_product(db, line.product_id)
    if product is None or not product.is_active:
        raise AppError(409, "product_unavailable", "This product is no longer available")
    if quantity > product.stock_quantity:
        raise AppError(
            409,
            "insufficient_stock",
            f"Only {product.stock_quantity} available",
            extra={"available_quantity": product.stock_quantity},
        )
    line.quantity = quantity
    await db.flush()
    return line


async def ensure_quantities(db: AsyncSession, user_id: uuid.UUID, wanted: list[tuple[uuid.UUID, int]]) -> BulkAddResult:
    """Ensure the cart holds *at least* each wanted quantity (idempotent bulk add).

    Repeating the call does not keep increasing quantities. Lines that cannot be
    satisfied are reported, not raised, and never exceed available stock.
    """
    merged: dict[uuid.UUID, int] = {}
    for product_id, qty in wanted:
        merged[product_id] = merged.get(product_id, 0) + max(qty, 0)

    result = BulkAddResult()
    for product_id in sorted(merged):  # stable lock order
        want = min(merged[product_id], MAX_LINE_QUANTITY)
        product = await _get_product(db, product_id)
        line = await _get_line(db, user_id, product_id)
        have = line.quantity if line else 0
        if product is None or not product.is_active:
            result.lines.append(CartLineResult(product_id, want, 0, have, "unavailable", "Product unavailable"))
            continue
        if have >= want:
            result.lines.append(CartLineResult(product_id, want, 0, have, "already_satisfied"))
            continue
        target = min(want, product.stock_quantity)
        if target <= have:
            result.lines.append(
                CartLineResult(
                    product_id, want, 0, have, "insufficient_stock", f"Only {product.stock_quantity} available"
                )
            )
            continue
        if line is None:
            line = CartItem(user_id=user_id, product_id=product_id, quantity=target)
            db.add(line)
        else:
            line.quantity = target
        status = "added" if target == want else "limited"
        message = None if status == "added" else f"Only {product.stock_quantity} available"
        result.lines.append(CartLineResult(product_id, want, target - have, target, status, message))
    await db.flush()
    return result


async def load_cart(db: AsyncSession, user_id: uuid.UUID) -> list[CartItem]:
    return list(
        (
            await db.execute(
                select(CartItem)
                .where(CartItem.user_id == user_id)
                .options(selectinload(CartItem.product))
                .order_by(CartItem.created_at, CartItem.id)
            )
        ).scalars()
    )


def line_issues(item: CartItem) -> list[str]:
    """Problems that would block checkout for this line."""
    issues: list[str] = []
    product = item.product
    if not product.is_active:
        issues.append("product_unavailable")
    elif item.quantity > product.stock_quantity:
        issues.append("insufficient_stock")
    return issues


def cart_subtotal_cents(items: list[CartItem]) -> int:
    return sum(effective_price_cents(i.product) * i.quantity for i in items)
