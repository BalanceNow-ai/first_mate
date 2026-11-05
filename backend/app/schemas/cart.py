"""Cart schemas."""

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel, StrictInput


class CartItemCreate(StrictInput):
    product_id: uuid.UUID
    quantity: int = Field(1, ge=1, le=99)


class CartItemUpdate(StrictInput):
    quantity: int = Field(ge=1, le=99)


class CartProductSummary(APIModel):
    id: uuid.UUID
    sku: str
    name: str
    brand: str | None
    images: list[str] = []
    price_cents: int
    sale_price_cents: int | None
    effective_price_cents: int
    stock_quantity: int
    is_active: bool
    dangerous_goods: bool
    weight_grams: int | None


class CartItemResponse(APIModel):
    id: uuid.UUID
    product_id: uuid.UUID
    quantity: int
    unit_price_cents: int
    line_total_cents: int
    product: CartProductSummary
    issues: list[str] = []
    created_at: datetime


class CartResponse(APIModel):
    currency: str = "NZD"
    items: list[CartItemResponse]
    subtotal_cents: int
    item_count: int
    has_issues: bool


class BulkAddLine(APIModel):
    product_id: uuid.UUID
    requested: int
    added: int
    quantity_in_cart: int
    status: str
    message: str | None = None


class BulkAddResponse(APIModel):
    added_count: int
    lines: list[BulkAddLine]
