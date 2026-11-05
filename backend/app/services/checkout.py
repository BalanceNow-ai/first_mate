"""Idempotent checkout: cart -> order with reserved stock, in one transaction.

The amount that will be charged is computed here once, from server data only:

    subtotal  = sum(effective unit price x quantity)            (services.pricing)
    discount  = reserved discount entitlement (<= subtotal)
    shipping  = 0 for click & collect; the bound quote's price otherwise, except courier
                orders whose subtotal after discount reaches the free-shipping threshold
    total     = subtotal - discount + shipping                  (>= min_charge_cents)

Anything that fails raises ``AppError`` and the request transaction is rolled back, so
no partial reservation, quote use or entitlement change survives a failed checkout.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.core.errors import AppError
from app.database import utcnow
from app.models.cart import CartItem
from app.models.helm_dash import OperatingArea
from app.models.loyalty import DiscountEntitlement
from app.models.order import Order, OrderItem, StockReservation
from app.models.shipping import DeliveryQuote
from app.services import entitlements, reservations, shipping_quotes
from app.services.payment_providers import get_provider
from app.services.pricing import effective_price_cents

logger = logging.getLogger(__name__)

_ORDER_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # no 0/O/1/I


def new_order_number() -> str:
    settings = get_settings()
    suffix = "".join(secrets.choice(_ORDER_ALPHABET) for _ in range(6))
    return f"{settings.order_number_prefix}-{utcnow():%y%m%d}-{suffix}"


@dataclass
class CheckoutRequest:
    delivery_type: str
    quote_id: uuid.UUID | None = None
    shipping_address: dict | None = None
    helm_dash_contact: dict | None = None
    discount_entitlement_id: uuid.UUID | None = None
    notes: str | None = None


@dataclass
class Pricing:
    subtotal_cents: int
    discount_cents: int
    shipping_cents: int
    total_cents: int
    free_shipping_applied: bool = False
    quote: DeliveryQuote | None = None
    entitlement: DiscountEntitlement | None = None
    lines: list[CartItem] = field(default_factory=list)


async def find_by_idempotency_key(db: AsyncSession, user_id: uuid.UUID, key: str) -> Order | None:
    return (
        await db.execute(
            select(Order)
            .where(Order.user_id == user_id, Order.idempotency_key == key)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def _locked_cart(db: AsyncSession, user_id: uuid.UUID) -> list[CartItem]:
    return list(
        (
            await db.execute(
                select(CartItem)
                .where(CartItem.user_id == user_id)
                .options(selectinload(CartItem.product))
                .order_by(CartItem.product_id)
                .with_for_update(of=CartItem)
                .execution_options(populate_existing=True)
            )
        ).scalars()
    )


def _validate_lines(lines: list[CartItem]) -> None:
    if not lines:
        raise AppError(422, "cart_empty", "Your cart is empty")
    inactive = [str(i.product_id) for i in lines if not i.product.is_active]
    if inactive:
        raise AppError(
            409,
            "product_unavailable",
            "Some products in your cart are no longer available",
            extra={"product_ids": inactive},
        )
    short = [str(i.product_id) for i in lines if i.quantity > i.product.stock_quantity]
    if short:
        raise AppError(
            409,
            "insufficient_stock",
            "Some products in your cart do not have enough stock",
            extra={"product_ids": short},
        )


async def _bound_quote(
    db: AsyncSession, user_id: uuid.UUID, req: CheckoutRequest, lines: list[CartItem]
) -> DeliveryQuote:
    if req.quote_id is None:
        raise AppError(422, "quote_required", "A delivery quote is required for this delivery type")
    quote = (
        await db.execute(
            select(DeliveryQuote)
            .where(DeliveryQuote.id == req.quote_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if quote is None or quote.user_id != user_id:
        raise AppError(404, "quote_not_found", "Delivery quote not found")
    if quote.delivery_type != req.delivery_type:
        raise AppError(422, "quote_type_mismatch", "This quote is for a different delivery type")
    if quote.used_by_order_id is not None:
        raise AppError(409, "quote_used", "This delivery quote has already been used")
    if quote.expires_at <= utcnow():
        raise AppError(
            409, "quote_expired", "This delivery quote has expired. Please get a new quote."
        )
    if quote.cart_fingerprint != shipping_quotes.fingerprint_of(lines):
        raise AppError(
            409, "quote_cart_changed", "Your cart changed after this quote. Please get a new quote."
        )
    if not quote.destination:
        raise AppError(422, "invalid_destination", "This quote has no destination")
    return quote


async def price_checkout(db: AsyncSession, user_id: uuid.UUID, req: CheckoutRequest) -> Pricing:
    """Validate the cart + delivery choice and compute the amounts (locks the cart,
    quote and entitlement rows; changes nothing)."""
    settings = get_settings()
    lines = await _locked_cart(db, user_id)
    _validate_lines(lines)
    shipping_quotes.check_dangerous_goods(lines, req.delivery_type)

    subtotal = sum(effective_price_cents(i.product) * i.quantity for i in lines)
    quote: DeliveryQuote | None = None
    if req.delivery_type == "click_and_collect":
        if not settings.click_and_collect_enabled:
            raise AppError(
                422, "delivery_unavailable", "Click and collect is not available right now"
            )
        if req.quote_id is not None:
            raise AppError(
                422, "quote_not_applicable", "Click and collect does not use a delivery quote"
            )
    elif req.delivery_type == "courier":
        if req.shipping_address is None:
            raise AppError(
                422,
                "shipping_address_required",
                "A shipping address is required for courier delivery",
            )
        quote = await _bound_quote(db, user_id, req, lines)
        if quote.destination.get("postcode") != req.shipping_address.get("postcode"):
            raise AppError(
                422,
                "quote_destination_mismatch",
                "The shipping address postcode does not match the quoted destination",
            )
        if not shipping_quotes.courier_configured(settings):
            raise AppError(
                503, "courier_unavailable", "Courier delivery is not available right now"
            )
    elif req.delivery_type == "helm_dash":
        if req.helm_dash_contact is None:
            raise AppError(
                422,
                "helm_dash_contact_required",
                "Vessel contact details are required for Helm Dash",
            )
        quote = await _bound_quote(db, user_id, req, lines)
        area = (
            await db.get(OperatingArea, quote.operating_area_id)
            if quote.operating_area_id
            else None
        )
        if not settings.helm_dash_enabled or area is None or not area.enabled:
            raise AppError(503, "helm_dash_unavailable", "Helm Dash is not operating right now")
    else:  # pragma: no cover - schema restricts values
        raise AppError(422, "invalid_delivery_type", "Unknown delivery type")

    ent = None
    discount = 0
    if req.discount_entitlement_id is not None:
        ent = await entitlements.lock_for_checkout(
            db, user_id, req.discount_entitlement_id, subtotal
        )
        discount = ent.amount_cents

    shipping = 0
    free = False
    if quote is not None:
        shipping = quote.price_cents
        if (
            req.delivery_type == "courier"
            and subtotal - discount >= settings.free_shipping_threshold_cents
        ):
            shipping, free = 0, True
    total = subtotal - discount + shipping
    if total < settings.min_charge_cents:
        raise AppError(
            422,
            "below_minimum_charge",
            f"The order total must be at least {settings.min_charge_cents} cents",
            extra={"total_cents": total, "min_charge_cents": settings.min_charge_cents},
        )
    return Pricing(subtotal, discount, shipping, total, free, quote, ent, lines)


async def _lock_user(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Serialise checkouts of one user (double taps with or without the same key)."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"checkout:{user_id}"}
    )


async def checkout(
    db: AsyncSession, user_id: uuid.UUID, req: CheckoutRequest, idempotency_key: str
) -> tuple[Order, bool]:
    """Create the order. Returns ``(order, created)``; a repeated key returns the
    existing order with ``created=False`` and no side effects."""
    settings = get_settings()
    await _lock_user(db, user_id)
    existing = await find_by_idempotency_key(db, user_id, idempotency_key)
    if existing is not None:
        return existing, False

    provider = get_provider()  # 503 before anything is reserved
    pricing = await price_checkout(db, user_id, req)
    lines = pricing.lines

    failed = await reservations.decrement_stock(db, [(i.product_id, i.quantity) for i in lines])
    if failed:
        raise AppError(
            409,
            "insufficient_stock",
            "Some products in your cart are no longer in stock",
            extra={"product_ids": [str(p) for p in failed]},
        )

    now = utcnow()
    order = Order(
        id=uuid.uuid4(),
        order_number=new_order_number(),
        user_id=user_id,
        status="pending_payment",
        payment_status="unpaid",
        currency="NZD",
        subtotal_cents=pricing.subtotal_cents,
        discount_cents=pricing.discount_cents,
        shipping_cents=pricing.shipping_cents,
        total_cents=pricing.total_cents,
        refunded_cents=0,
        delivery_type=req.delivery_type,
        idempotency_key=idempotency_key,
        payment_provider=provider.name,
        expires_at=now + timedelta(minutes=settings.reservation_minutes),
        notes=req.notes,
    )
    if req.delivery_type == "click_and_collect":
        order.pickup_location = settings.click_and_collect_location
    elif req.delivery_type == "courier":
        order.shipping_address = {**req.shipping_address, "country": "NZ"}
    else:
        q = pricing.quote
        order.helm_dash_coordinates = {
            "lat": q.destination["lat"],
            "lng": q.destination["lng"],
            "location_name": q.destination.get("location_name"),
            "operating_area_id": q.operating_area_id,
            "nautical_miles": float(q.nautical_miles) if q.nautical_miles is not None else None,
            "estimated_minutes": q.estimated_minutes,
            **(req.helm_dash_contact or {}),
        }
    if pricing.quote is not None:
        order.delivery_quote_id = pricing.quote.id
    if pricing.entitlement is not None:
        order.discount_entitlement_id = pricing.entitlement.id
    for line in lines:
        unit = effective_price_cents(line.product)
        order.items.append(
            OrderItem(
                product_id=line.product_id,
                product_name=line.product.name,
                sku=line.product.sku,
                quantity=line.quantity,
                list_price_cents=line.product.price_cents,
                unit_price_cents=unit,
                line_total_cents=unit * line.quantity,
            )
        )
        order.reservations.append(
            StockReservation(product_id=line.product_id, quantity=line.quantity, status="reserved")
        )
    db.add(order)
    await db.flush()

    if pricing.entitlement is not None:
        await entitlements.reserve_for_order(db, pricing.entitlement, order)
    if pricing.quote is not None:
        pricing.quote.used_by_order_id = order.id
    await db.execute(delete(CartItem).where(CartItem.user_id == user_id))
    await db.flush()
    logger.info("Order %s created (%s, %d lines)", order.id, req.delivery_type, len(lines))
    return order, True
