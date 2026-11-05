"""Serialisation helpers that apply the central pricing rules to products."""

from __future__ import annotations

from app.models.product import Product
from app.schemas.cart import CartProductSummary
from app.schemas.product import FitmentResult, ProductAdminResponse, ProductResponse
from app.services.pricing import CURRENCY, effective_price_cents, is_on_sale


def _common(p: Product) -> dict:
    return {
        "id": p.id,
        "sku": p.sku,
        "name": p.name,
        "description": p.description,
        "brand": p.brand,
        "category": p.category,
        "sub_category": p.sub_category,
        "currency": CURRENCY,
        "price_cents": p.price_cents,
        "sale_price_cents": p.sale_price_cents,
        "effective_price_cents": effective_price_cents(p),
        "on_sale": is_on_sale(p),
        "stock_quantity": p.stock_quantity,
        "in_stock": p.is_active and p.stock_quantity > 0,
        "weight_grams": p.weight_grams,
        "images": list(p.images or []),
        "specifications": p.specifications,
        "oem_part_numbers": list(p.oem_part_numbers or []),
        "part_role": p.part_role,
        "fitment_scope": p.fitment_scope,
        "dangerous_goods": p.dangerous_goods,
        "is_active": p.is_active,
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }


def product_response(p: Product, fitment: FitmentResult | None = None) -> ProductResponse:
    return ProductResponse(**_common(p), fitment=fitment)


def product_admin_response(p: Product) -> ProductAdminResponse:
    return ProductAdminResponse(**_common(p), cost_price_cents=p.cost_price_cents)


def cart_product_summary(p: Product) -> CartProductSummary:
    return CartProductSummary(
        id=p.id,
        sku=p.sku,
        name=p.name,
        brand=p.brand,
        images=list(p.images or []),
        price_cents=p.price_cents,
        sale_price_cents=p.sale_price_cents,
        effective_price_cents=effective_price_cents(p),
        stock_quantity=p.stock_quantity,
        is_active=p.is_active,
        dangerous_goods=p.dangerous_goods,
        weight_grams=p.weight_grams,
    )
