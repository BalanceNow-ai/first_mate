"""Catalogue queries shared by the products router, Postgres search and checklists.

Every fit statement shown to a customer comes from :mod:`app.services.fitment`.
``compatible_only`` uses :func:`fitment.candidate_clause` as an SQL pre-filter and then
runs the exact evaluation, so pagination and totals reflect *exact* results.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import Text, and_, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError, not_found
from app.middleware.auth import Principal
from app.models.product import Product
from app.models.vessel import Vessel
from app.schemas.product import FitmentResult, VesselRef
from app.services import fitment

SortKey = Literal["relevance", "name", "price_asc", "price_desc", "newest"]

# SQL equivalent of pricing.effective_price_cents (the DB constraint guarantees
# 0 < sale < price whenever a sale price is set).
EFFECTIVE_PRICE = case(
    (
        and_(Product.sale_price_cents.isnot(None), Product.sale_price_cents < Product.price_cents),
        Product.sale_price_cents,
    ),
    else_=Product.price_cents,
)


@dataclass
class ProductFilters:
    category: str | None = None
    sub_category: str | None = None
    brand: str | None = None
    min_price_cents: int | None = None
    max_price_cents: int | None = None
    in_stock: bool | None = None
    on_sale: bool | None = None
    part_role: str | None = None
    q: str | None = None
    include_inactive: bool = False

    def clauses(self) -> list:
        out: list = []
        if not self.include_inactive:
            out.append(Product.is_active.is_(True))
        if self.category:
            out.append(func.lower(Product.category) == self.category.strip().lower())
        if self.sub_category:
            out.append(func.lower(Product.sub_category) == self.sub_category.strip().lower())
        if self.brand:
            out.append(func.lower(Product.brand) == self.brand.strip().lower())
        if self.min_price_cents is not None:
            out.append(EFFECTIVE_PRICE >= self.min_price_cents)
        if self.max_price_cents is not None:
            out.append(EFFECTIVE_PRICE <= self.max_price_cents)
        if self.in_stock is True:
            out.append(Product.stock_quantity > 0)
        elif self.in_stock is False:
            out.append(Product.stock_quantity <= 0)
        if self.on_sale is True:
            out.append(and_(Product.sale_price_cents.isnot(None), Product.sale_price_cents < Product.price_cents))
        elif self.on_sale is False:
            out.append(or_(Product.sale_price_cents.is_(None), Product.sale_price_cents >= Product.price_cents))
        if self.part_role:
            out.append(Product.part_role == self.part_role.strip())
        q = (self.q or "").strip()
        if q:
            out.append(text_match(q))
        return out


def _like(q: str) -> str:
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def text_match(q: str):
    """ILIKE across name, description, SKU, brand and OEM part numbers."""
    pattern = _like(q)
    return or_(
        Product.name.ilike(pattern, escape="\\"),
        Product.description.ilike(pattern, escape="\\"),
        Product.sku.ilike(pattern, escape="\\"),
        Product.brand.ilike(pattern, escape="\\"),
        cast(Product.oem_part_numbers, Text).ilike(pattern, escape="\\"),
    )


def relevance(q: str):
    """Simple deterministic ranking for the Postgres search backend."""
    q = q.strip()
    pattern = _like(q)
    prefix = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    return (
        case((func.lower(Product.sku) == q.lower(), 100), else_=0)
        + case((cast(Product.oem_part_numbers, Text).ilike(pattern, escape="\\"), 60), else_=0)
        + case((Product.name.ilike(prefix, escape="\\"), 40), else_=0)
        + case((Product.name.ilike(pattern, escape="\\"), 30), else_=0)
        + case((Product.sku.ilike(pattern, escape="\\"), 25), else_=0)
        + case((Product.brand.ilike(pattern, escape="\\"), 15), else_=0)
        + case((Product.description.ilike(pattern, escape="\\"), 5), else_=0)
    )


def order_by(sort: SortKey, q: str | None = None) -> list:
    if sort == "relevance" and q and q.strip():
        return [relevance(q).desc(), Product.name.asc(), Product.id.asc()]
    if sort == "price_asc":
        return [EFFECTIVE_PRICE.asc(), Product.id.asc()]
    if sort == "price_desc":
        return [EFFECTIVE_PRICE.desc(), Product.id.asc()]
    if sort == "newest":
        return [Product.created_at.desc(), Product.id.asc()]
    return [Product.name.asc(), Product.id.asc()]


@dataclass
class ProductPage:
    items: list[Product]
    total: int
    fitment: dict[uuid.UUID, FitmentResult] = field(default_factory=dict)


async def list_products(
    db: AsyncSession,
    filters: ProductFilters,
    *,
    sort: SortKey = "name",
    offset: int = 0,
    limit: int = 24,
    profile: fitment.VesselProfile | None = None,
    compatible_only: bool = False,
) -> ProductPage:
    """Filtered, stably ordered page of products, with fitment when a profile is given."""
    clauses = filters.clauses()
    ordering = order_by(sort, filters.q)

    if profile is not None and compatible_only:
        # 1) SQL pre-filter narrows to products that *could* fit; 2) exact evaluation.
        clauses.append(fitment.candidate_clause(profile))
        batch = get_settings().catalogue_fitment_batch_size
        matched: list[Product] = []
        results: dict[uuid.UUID, FitmentResult] = {}
        total = 0
        cursor = 0
        while True:
            chunk = list(
                (
                    await db.execute(select(Product).where(*clauses).order_by(*ordering).offset(cursor).limit(batch))
                ).scalars()
            )
            if not chunk:
                break
            cursor += len(chunk)
            evaluated = await fitment.evaluate_products(db, chunk, profile)
            for p in chunk:
                res = evaluated[p.id]
                if res.status not in fitment.POSITIVE_STATUSES:
                    continue
                if offset <= total < offset + limit:
                    matched.append(p)
                    results[p.id] = res
                total += 1
            if len(chunk) < batch:
                break
        return ProductPage(items=matched, total=total, fitment=results)

    total = (await db.execute(select(func.count()).select_from(Product).where(*clauses))).scalar_one()
    items = list(
        (await db.execute(select(Product).where(*clauses).order_by(*ordering).offset(offset).limit(limit))).scalars()
    )
    results = await fitment.evaluate_products(db, items, profile) if profile is not None else {}
    return ProductPage(items=items, total=total, fitment=results)


async def resolve_vessel(db: AsyncSession, principal: Principal | None, vessel_id: uuid.UUID | None) -> Vessel | None:
    """Owner-scoped vessel for personalised catalogue calls.

    No token → 401; a vessel that is not the caller's → 404 (no existence leak).
    """
    if vessel_id is None:
        return None
    if principal is None:
        raise AppError(
            401,
            "invalid_token",
            "Sign in to check fitment for a vessel",
            headers={"WWW-Authenticate": "Bearer"},
        )
    vessel = (
        await db.execute(select(Vessel).where(Vessel.id == vessel_id, Vessel.user_id == principal.subject))
    ).scalar_one_or_none()
    if vessel is None:
        raise not_found("Vessel")
    return vessel


async def vessel_profile(
    db: AsyncSession, principal: Principal | None, vessel_id: uuid.UUID | None
) -> tuple[fitment.VesselProfile | None, VesselRef | None]:
    vessel = await resolve_vessel(db, principal, vessel_id)
    if vessel is None:
        return None, None
    profile = await fitment.load_vessel_profile(db, vessel)
    return profile, VesselRef(id=vessel.id, label=profile.label)


async def get_active_product(db: AsyncSession, product_id: uuid.UUID) -> Product:
    product = await db.get(Product, product_id)
    if product is None or not product.is_active:
        raise not_found("Product")
    return product
