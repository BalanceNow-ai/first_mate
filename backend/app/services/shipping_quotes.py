"""Server-owned delivery pricing and quotes.

Every delivery price that can be charged comes from a persisted ``DeliveryQuote``
computed here from the user's *current* cart. Quotes expire, are single use and carry
a fingerprint of the cart they were computed for, so checkout can prove the quote
still describes what is being bought.

* courier: an explicitly configured merchant rate card by total parcel weight. A
  product without a recorded weight cannot be quoted (the weight is never guessed).
* helm_dash: base fee + per-nautical-mile fee from the warehouse, only inside an
  enabled operating area.
* click_and_collect: always free, no quote.

Dangerous-goods products may only use ``settings.dg_delivery_types``; no carrier
approval is asserted by this code.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.errors import AppError
from app.database import utcnow
from app.models.helm_dash import OperatingArea
from app.models.product import Product
from app.models.shipping import DeliveryQuote
from app.services import cart_service
from app.services.geo import haversine_nm
from app.services.pricing import effective_price_cents

DELIVERY_LABELS = {
    "courier": "courier",
    "helm_dash": "Helm Dash",
    "click_and_collect": "click and collect",
}


class Line(Protocol):
    product: Product
    quantity: int


@dataclass
class SimpleLine:
    product: Product
    quantity: int


# --------------------------------------------------------------------------- helpers
def cart_fingerprint(lines: Iterable[tuple[uuid.UUID, int]]) -> str:
    """sha256 over the sorted ``product_id:quantity`` pairs of a cart."""
    parts = sorted(f"{pid}:{qty}" for pid, qty in lines)
    return hashlib.sha256(",".join(parts).encode()).hexdigest()


def fingerprint_of(lines: Sequence[Line]) -> str:
    return cart_fingerprint((line.product.id, line.quantity) for line in lines)


def merchandise_subtotal_cents(lines: Sequence[Line]) -> int:
    return sum(effective_price_cents(line.product) * line.quantity for line in lines)


def _product_ref(p: Product) -> dict:
    return {"product_id": str(p.id), "name": p.name, "sku": p.sku}


def missing_weight_products(lines: Sequence[Line]) -> list[Product]:
    return [line.product for line in lines if line.product.weight_grams is None]


def known_weight_grams(lines: Sequence[Line]) -> int:
    return sum((line.product.weight_grams or 0) * line.quantity for line in lines)


def dangerous_goods_products(lines: Sequence[Line]) -> list[Product]:
    return [line.product for line in lines if line.product.dangerous_goods]


def dg_allowed(delivery_type: str, settings: Settings | None = None) -> bool:
    return delivery_type in (settings or get_settings()).dg_delivery_types


def check_dangerous_goods(lines: Sequence[Line], delivery_type: str) -> None:
    """Raise 422 ``dangerous_goods_restricted`` naming the restricted products."""
    settings = get_settings()
    dg = dangerous_goods_products(lines)
    if dg and not dg_allowed(delivery_type, settings):
        allowed = ", ".join(DELIVERY_LABELS.get(t, t) for t in sorted(settings.dg_delivery_types))
        names = ", ".join(p.name for p in dg)
        raise AppError(
            422,
            "dangerous_goods_restricted",
            f"{names} cannot be sent by {DELIVERY_LABELS.get(delivery_type, delivery_type)}. "
            f"Dangerous goods are only available via: {allowed or 'no delivery method'}.",
            extra={
                "products": [_product_ref(p) for p in dg],
                "allowed_delivery_types": sorted(settings.dg_delivery_types),
            },
        )


def round_half_up(value: Decimal, places: str = "1") -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------- courier
def is_development_rate_card(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return s.is_local and not s.courier_rate_card


def courier_configured(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return s.courier_rate_mode == "rate_card" and bool(s.courier_rate_table())


@dataclass
class CourierPrice:
    price_cents: int
    weight_grams: int


def courier_price(lines: Sequence[Line]) -> CourierPrice:
    """Rate-card price for the parcel, or raise the precise reason it is unavailable."""
    settings = get_settings()
    if not courier_configured(settings):
        raise AppError(503, "courier_unavailable", "Courier delivery is not available right now")
    missing = missing_weight_products(lines)
    if missing:
        raise AppError(
            422,
            "weight_unknown",
            "Courier delivery cannot be priced because these products have no recorded "
            "weight: " + ", ".join(p.name for p in missing),
            extra={"products": [_product_ref(p) for p in missing]},
        )
    grams = known_weight_grams(lines)
    for row in settings.courier_rate_table():
        if grams <= row["max_grams"]:
            return CourierPrice(price_cents=row["price_cents"], weight_grams=grams)
    raise AppError(
        422,
        "parcel_too_heavy",
        "This order is too heavy for courier delivery. Choose another delivery method.",
        extra={"weight_grams": grams},
    )


# --------------------------------------------------------------------------- Helm Dash
@dataclass
class HelmDashPrice:
    area: OperatingArea
    nautical_miles: Decimal
    price_cents: int
    estimated_minutes: int


async def enabled_areas(db: AsyncSession) -> list[OperatingArea]:
    return list(
        (
            await db.execute(
                select(OperatingArea)
                .where(OperatingArea.enabled.is_(True))
                .order_by(OperatingArea.id)
            )
        ).scalars()
    )


async def find_operating_area(db: AsyncSession, lat: float, lng: float) -> OperatingArea | None:
    """The enabled area containing the point (nearest centre first)."""
    best: tuple[float, OperatingArea] | None = None
    for area in await enabled_areas(db):
        d = haversine_nm(area.center_lat, area.center_lng, lat, lng)
        if d <= area.radius_nm and (best is None or d < best[0]):
            best = (d, area)
    return best[1] if best else None


async def helm_dash_price(db: AsyncSession, lat: float, lng: float) -> HelmDashPrice:
    settings = get_settings()
    if not settings.helm_dash_enabled:
        raise AppError(503, "helm_dash_unavailable", "Helm Dash is not operating right now")
    area = await find_operating_area(db, lat, lng)
    if area is None:
        raise AppError(
            422,
            "outside_operating_area",
            "This location is outside the Helm Dash operating areas.",
        )
    nm = round_half_up(
        Decimal(str(haversine_nm(settings.warehouse_lat, settings.warehouse_lng, lat, lng))), "0.01"
    )
    fee = settings.helm_dash_base_fee_cents + int(
        round_half_up(Decimal(settings.helm_dash_per_nm_fee_cents) * nm)
    )
    speed = Decimal(str(settings.helm_dash_speed_knots))
    eta = int(round_half_up(nm / speed * 60)) + 15
    return HelmDashPrice(area=area, nautical_miles=nm, price_cents=fee, estimated_minutes=eta)


# --------------------------------------------------------------------------- quotes
@dataclass
class QuoteView:
    quote: DeliveryQuote
    merchandise_subtotal_cents: int
    area_name: str | None = None


def quote_payload(view: QuoteView) -> dict:
    q = view.quote
    settings = get_settings()
    return {
        "id": q.id,
        "delivery_type": q.delivery_type,
        "provider": q.provider,
        "service_name": q.service_name,
        "price_cents": q.price_cents,
        "currency": q.currency,
        "destination": q.destination,
        "parcel_weight_grams": q.parcel_weight_grams,
        "merchandise_subtotal_cents": view.merchandise_subtotal_cents,
        "free_shipping_threshold_cents": (
            settings.free_shipping_threshold_cents if q.delivery_type == "courier" else None
        ),
        "operating_area_id": q.operating_area_id,
        "operating_area_name": view.area_name,
        "nautical_miles": float(q.nautical_miles) if q.nautical_miles is not None else None,
        "estimated_minutes": q.estimated_minutes,
        "estimated_days": q.estimated_days,
        "development_rate_card": q.provider == "development_rate_card",
        "expires_at": q.expires_at,
        "created_at": q.created_at,
    }


async def create_quote(
    db: AsyncSession, user_id: uuid.UUID, delivery_type: str, destination: dict
) -> QuoteView:
    """Price the user's current cart and persist a single-use, expiring quote."""
    settings = get_settings()
    lines = await cart_service.load_cart(db, user_id)
    if not lines:
        raise AppError(422, "cart_empty", "Your cart is empty")
    check_dangerous_goods(lines, delivery_type)
    now = utcnow()
    common = {
        "user_id": user_id,
        "delivery_type": delivery_type,
        "currency": "NZD",
        "cart_fingerprint": fingerprint_of(lines),
        "expires_at": now + timedelta(minutes=settings.quote_ttl_minutes),
        "created_at": now,
    }
    area_name = None
    if delivery_type == "courier":
        if "postcode" not in destination:
            raise AppError(422, "invalid_destination", "Courier quotes need a postcode")
        price = courier_price(lines)
        quote = DeliveryQuote(
            **common,
            provider="development_rate_card" if is_development_rate_card(settings) else "rate_card",
            service_name=settings.courier_service_name,
            price_cents=price.price_cents,
            destination={k: v for k, v in destination.items() if v is not None},
            parcel_weight_grams=price.weight_grams,
            estimated_days=settings.courier_estimated_days,
        )
    else:
        if "lat" not in destination or "lng" not in destination:
            raise AppError(
                422, "invalid_destination", "Helm Dash quotes need a position (lat, lng)"
            )
        hd = await helm_dash_price(db, destination["lat"], destination["lng"])
        area_name = hd.area.name
        quote = DeliveryQuote(
            **common,
            provider="helm_dash",
            service_name="Helm Dash",
            price_cents=hd.price_cents,
            destination={k: v for k, v in destination.items() if v is not None},
            # Recorded for operations only; Helm Dash is priced by distance.
            parcel_weight_grams=known_weight_grams(lines),
            operating_area_id=hd.area.id,
            nautical_miles=hd.nautical_miles,
            estimated_minutes=hd.estimated_minutes,
        )
    db.add(quote)
    await db.flush()
    return QuoteView(
        quote=quote,
        merchandise_subtotal_cents=merchandise_subtotal_cents(lines),
        area_name=area_name,
    )


# --------------------------------------------------------------------------- options
def _reason(exc: AppError) -> tuple[str, str]:
    return exc.code, exc.message


async def delivery_options(db: AsyncSession, user_id: uuid.UUID) -> dict:
    """Availability of every delivery type for the user's current cart, with reasons."""
    settings = get_settings()
    lines = await cart_service.load_cart(db, user_id)
    dg = dangerous_goods_products(lines)
    missing = missing_weight_products(lines)
    options: list[dict] = []

    def blocked_by_dg(delivery_type: str) -> tuple[str, str] | None:
        try:
            check_dangerous_goods(lines, delivery_type)
        except AppError as exc:
            return _reason(exc)
        return None

    # click & collect
    cc = {
        "delivery_type": "click_and_collect",
        "requires_quote": False,
        "price_cents": 0,
        "pickup_location": settings.click_and_collect_location,
        "available": True,
    }
    if not settings.click_and_collect_enabled:
        cc.update(
            available=False,
            reason_code="delivery_unavailable",
            reason="Click and collect is not available right now",
        )
    elif (r := blocked_by_dg("click_and_collect")) is not None:
        cc.update(available=False, reason_code=r[0], reason=r[1])
    options.append(cc)

    # courier
    courier = {
        "delivery_type": "courier",
        "requires_quote": True,
        "available": True,
        "service_name": settings.courier_service_name,
        "estimated_days": settings.courier_estimated_days,
        "development_rate_card": courier_configured(settings)
        and is_development_rate_card(settings),
    }
    if not lines:
        courier.update(available=False, reason_code="cart_empty", reason="Your cart is empty")
    elif (r := blocked_by_dg("courier")) is not None:
        courier.update(available=False, reason_code=r[0], reason=r[1])
    else:
        try:
            courier["price_cents"] = courier_price(lines).price_cents
        except AppError as exc:
            courier.update(available=False, reason_code=exc.code, reason=exc.message)
    options.append(courier)

    # Helm Dash
    areas = await enabled_areas(db) if settings.helm_dash_enabled else []
    hd = {
        "delivery_type": "helm_dash",
        "requires_quote": True,
        "available": True,
        "service_name": "Helm Dash",
        "operating_areas": [
            {
                "id": a.id,
                "name": a.name,
                "center_lat": a.center_lat,
                "center_lng": a.center_lng,
                "radius_nm": a.radius_nm,
            }
            for a in areas
        ],
    }
    if not settings.helm_dash_enabled or not areas:
        hd.update(
            available=False,
            reason_code="helm_dash_unavailable",
            reason="Helm Dash is not operating right now",
        )
    elif not lines:
        hd.update(available=False, reason_code="cart_empty", reason="Your cart is empty")
    elif (r := blocked_by_dg("helm_dash")) is not None:
        hd.update(available=False, reason_code=r[0], reason=r[1])
    options.append(hd)

    return {
        "currency": "NZD",
        "merchandise_subtotal_cents": merchandise_subtotal_cents(lines),
        "total_weight_grams": None if missing else known_weight_grams(lines),
        "missing_weight_products": [_ref_obj(p) for p in missing],
        "dangerous_goods_products": [_ref_obj(p) for p in dg],
        "free_shipping_threshold_cents": settings.free_shipping_threshold_cents,
        "options": options,
    }


def _ref_obj(p: Product) -> dict:
    return {"product_id": p.id, "name": p.name, "sku": p.sku}


# --------------------------------------------------------------------------- estimate
async def estimate(
    db: AsyncSession,
    delivery_type: str,
    items: list[tuple[uuid.UUID, int]],
    destination: dict | None,
) -> dict:
    """Informational, non-bindable price for a set of products (product pages)."""
    settings = get_settings()
    merged: dict[uuid.UUID, int] = {}
    for pid, qty in items:
        merged[pid] = min(merged.get(pid, 0) + qty, cart_service.MAX_LINE_QUANTITY)
    products = {
        p.id: p
        for p in (
            await db.execute(
                select(Product).where(Product.id.in_(merged), Product.is_active.is_(True))
            )
        ).scalars()
    }
    result: dict = {"delivery_type": delivery_type, "available": False, "bindable": False}
    if len(products) != len(merged):
        result.update(
            reason_code="product_unavailable", reason="One or more products are not available"
        )
        return result
    lines = [SimpleLine(products[pid], qty) for pid, qty in merged.items()]
    try:
        check_dangerous_goods(lines, delivery_type)
        if delivery_type == "courier":
            price = courier_price(lines)
            result.update(
                available=True,
                price_cents=price.price_cents,
                service_name=settings.courier_service_name,
                estimated_days=settings.courier_estimated_days,
                development_rate_card=is_development_rate_card(settings),
            )
        else:
            if destination is None:
                raise AppError(422, "invalid_destination", "Helm Dash estimates need a position")
            hd = await helm_dash_price(db, destination["lat"], destination["lng"])
            result.update(
                available=True,
                price_cents=hd.price_cents,
                service_name="Helm Dash",
                estimated_minutes=hd.estimated_minutes,
                nautical_miles=float(hd.nautical_miles),
            )
    except AppError as exc:
        result.update(reason_code=exc.code, reason=exc.message)
    return result
