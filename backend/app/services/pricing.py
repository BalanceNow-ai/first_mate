"""Central money and price rules. All amounts are integer NZD cents."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.models.product import Product

CURRENCY = "NZD"


def effective_price_cents(product: Product) -> int:
    """The price a customer pays for one unit right now (sale price when valid)."""
    sale = product.sale_price_cents
    if sale is not None and 0 < sale < product.price_cents:
        return sale
    return product.price_cents


def is_on_sale(product: Product) -> bool:
    return effective_price_cents(product) < product.price_cents


def line_total_cents(unit_price_cents: int, quantity: int) -> int:
    return unit_price_cents * quantity


def dollars_to_cents(amount: Decimal | str | int | float) -> int:
    """Convert a decimal NZD amount to cents, rounding half-up (input boundary only)."""
    value = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(value * 100)


def format_nzd(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"
