"""Product catalogue: public browse with vessel fitment, admin product & fitment curation.

Fit statements always come from :mod:`app.services.fitment`. Passing ``vessel_id``
requires a valid token and ownership of that vessel (no token → 401; someone else's
vessel → 404). ``unknown`` is never presented as a fit.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError, not_found
from app.core.rate_limit import mutation_limit
from app.database import get_db, utcnow
from app.middleware.auth import AdminUser, OptionalPrincipal, Principal
from app.models.boat_db import EquipmentCategory
from app.models.product import Product, ProductCompatibility
from app.schemas.product import (
    AdminProductListResponse,
    BrandCount,
    CategoryCount,
    CompatibilityResponse,
    FitmentResult,
    FitmentRuleAdminResponse,
    FitmentRuleCreate,
    FitmentRuleReject,
    FitmentRuleVerify,
    KnownFit,
    ProductAdminResponse,
    ProductCreate,
    ProductListResponse,
    ProductResponse,
    ProductUpdate,
    StockAdjust,
    SubCategoryCount,
)
from app.services import audit, boat_db, fitment, search_index
from app.services.catalogue import product_admin_response, product_response
from app.services.product_catalogue import (
    ProductFilters,
    get_active_product,
    list_products,
    resolve_vessel,
    vessel_profile,
)

router = APIRouter(prefix="/products", tags=["Products"])

SortParam = Literal["name", "price_asc", "price_desc", "newest", "relevance"]


def _page_limit(limit: int | None) -> int:
    s = get_settings()
    return min(limit or s.catalogue_default_page_size, s.catalogue_max_page_size)


def filters_dependency(
    category: str | None = Query(None, max_length=100),
    sub_category: str | None = Query(None, max_length=100),
    brand: str | None = Query(None, max_length=100),
    min_price_cents: int | None = Query(None, ge=0),
    max_price_cents: int | None = Query(None, ge=0),
    in_stock: bool | None = None,
    on_sale: bool | None = None,
    part_role: str | None = Query(None, max_length=60),
    q: str | None = Query(None, max_length=200),
) -> ProductFilters:
    return ProductFilters(
        category=category,
        sub_category=sub_category,
        brand=brand,
        min_price_cents=min_price_cents,
        max_price_cents=max_price_cents,
        in_stock=in_stock,
        on_sale=on_sale,
        part_role=part_role,
        q=q,
    )


# =========================================================================== public
@router.get("/", response_model=ProductListResponse)
async def list_catalogue(
    principal: OptionalPrincipal,
    filters: ProductFilters = Depends(filters_dependency),
    vessel_id: uuid.UUID | None = None,
    compatible_only: bool = False,
    sort: SortParam = "name",
    offset: int = Query(0, ge=0),
    limit: int | None = Query(None, ge=1),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> ProductListResponse:
    """Browse active products. With ``vessel_id`` every item carries ``fitment``;
    ``compatible_only=true`` keeps only ``verified_fit``/``universal`` items."""
    if compatible_only and vessel_id is None:
        raise AppError(422, "vessel_required", "compatible_only requires vessel_id")
    limit = _page_limit(limit)
    profile, vessel_ref = await vessel_profile(db, principal, vessel_id)
    page = await list_products(
        db, filters, sort=sort, offset=offset, limit=limit, profile=profile, compatible_only=compatible_only
    )
    return ProductListResponse(
        items=[product_response(p, page.fitment.get(p.id)) for p in page.items],
        total=page.total,
        offset=offset,
        limit=limit,
        vessel=vessel_ref,
    )


@router.get("/categories", response_model=list[CategoryCount])
async def list_categories(db: AsyncSession = Depends(get_db, scope="function")) -> list[CategoryCount]:
    """Categories (with sub-categories) of active products and their counts."""
    rows = (
        await db.execute(
            select(Product.category, Product.sub_category, func.count())
            .where(Product.is_active.is_(True))
            .group_by(Product.category, Product.sub_category)
            .order_by(Product.category, Product.sub_category)
        )
    ).all()
    out: dict[str, CategoryCount] = {}
    for category, sub, count in rows:
        entry = out.setdefault(category, CategoryCount(category=category, count=0, sub_categories=[]))
        entry.count += count
        if sub:
            entry.sub_categories.append(SubCategoryCount(name=sub, count=count))
    return list(out.values())


@router.get("/brands", response_model=list[BrandCount])
async def list_brands(db: AsyncSession = Depends(get_db, scope="function")) -> list[BrandCount]:
    rows = (
        await db.execute(
            select(Product.brand, func.count())
            .where(Product.is_active.is_(True), Product.brand.isnot(None))
            .group_by(Product.brand)
            .order_by(Product.brand)
        )
    ).all()
    return [BrandCount(brand=b, count=c) for b, c in rows]


# =========================================================================== admin
async def _admin_product(db: AsyncSession, product_id: uuid.UUID, *, lock: bool = False) -> Product:
    q = select(Product).where(Product.id == product_id)
    if lock:
        q = q.with_for_update()
    product = (await db.execute(q)).scalar_one_or_none()
    if product is None:
        raise not_found("Product")
    return product


async def _commit_and_sync(db: AsyncSession, product_ids: list[uuid.UUID]) -> None:
    """Commit first so the worker sees the change, then queue the index update."""
    await db.commit()
    search_index.enqueue_product_sync(product_ids)


@router.get("/admin", response_model=AdminProductListResponse)
async def admin_list_products(
    admin: AdminUser,
    filters: ProductFilters = Depends(filters_dependency),
    include_inactive: bool = True,
    sort: SortParam = "name",
    offset: int = Query(0, ge=0),
    limit: int | None = Query(None, ge=1),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> AdminProductListResponse:
    filters.include_inactive = include_inactive
    limit = _page_limit(limit)
    page = await list_products(db, filters, sort=sort, offset=offset, limit=limit)
    return AdminProductListResponse(
        items=[product_admin_response(p) for p in page.items], total=page.total, offset=offset, limit=limit
    )


@router.post("/", response_model=ProductAdminResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    body: ProductCreate, admin: AdminUser, db: AsyncSession = Depends(get_db, scope="function")
) -> ProductAdminResponse:
    if (await db.execute(select(Product.id).where(func.lower(Product.sku) == body.sku.lower()))).first():
        raise AppError(409, "duplicate_sku", "A product with this SKU exists")
    data = body.model_dump()
    data["images"] = data["images"] or []
    product = Product(**data)
    db.add(product)
    await db.flush()
    await audit.record(db, admin.id, "product.create", "product", product.id, {"sku": product.sku})
    await db.refresh(product)
    response = product_admin_response(product)
    await _commit_and_sync(db, [product.id])
    return response


@router.patch("/{product_id}", response_model=ProductAdminResponse)
async def update_product(
    product_id: uuid.UUID, body: ProductUpdate, admin: AdminUser, db: AsyncSession = Depends(get_db, scope="function")
) -> ProductAdminResponse:
    product = await _admin_product(db, product_id, lock=True)
    data = body.model_dump(exclude_unset=True)
    for required in (
        "name",
        "category",
        "price_cents",
        "stock_quantity",
        "fitment_scope",
        "dangerous_goods",
        "is_active",
        "oem_part_numbers",
    ):
        if required in data and data[required] is None:
            raise AppError(422, "invalid_value", f"{required} cannot be null")
    price = data.get("price_cents", product.price_cents)
    sale = data.get("sale_price_cents", product.sale_price_cents)
    if sale is not None and sale >= price:
        raise AppError(422, "invalid_sale_price", "sale_price_cents must be lower than price_cents")
    before = {k: getattr(product, k) for k in data}
    for k, v in data.items():
        setattr(product, k, v)
    await db.flush()
    await audit.record(
        db,
        admin.id,
        "product.update",
        "product",
        product.id,
        {"changes": {k: {"from": before[k], "to": v} for k, v in data.items() if before[k] != v}},
    )
    await db.refresh(product)
    response = product_admin_response(product)
    await _commit_and_sync(db, [product.id])
    return response


@router.post("/{product_id}/stock", response_model=ProductAdminResponse, dependencies=[Depends(mutation_limit())])
async def adjust_stock(
    product_id: uuid.UUID, body: StockAdjust, admin: AdminUser, db: AsyncSession = Depends(get_db, scope="function")
) -> ProductAdminResponse:
    """Atomically adjust stock by ``delta``; refuses to go below zero."""
    await _admin_product(db, product_id)
    row = (
        await db.execute(
            text(
                "UPDATE products SET stock_quantity = stock_quantity + :delta, updated_at = now() "
                "WHERE id = :id AND stock_quantity + :delta >= 0 RETURNING stock_quantity"
            ),
            {"delta": body.delta, "id": product_id},
        )
    ).first()
    if row is None:
        raise AppError(409, "insufficient_stock", "Stock cannot go below zero")
    await audit.record(
        db,
        admin.id,
        "product.stock_adjust",
        "product",
        product_id,
        {"delta": body.delta, "reason": body.reason, "stock_after": row[0], "stock_before": row[0] - body.delta},
    )
    product = await _admin_product(db, product_id)
    await db.refresh(product)
    response = product_admin_response(product)
    await _commit_and_sync(db, [product_id])
    return response


@router.delete("/{product_id}", response_model=ProductAdminResponse)
async def deactivate_product(
    product_id: uuid.UUID, admin: AdminUser, db: AsyncSession = Depends(get_db, scope="function")
) -> ProductAdminResponse:
    """Deactivate (soft delete): hidden publicly, kept for order history."""
    product = await _admin_product(db, product_id, lock=True)
    if product.is_active:
        product.is_active = False
        await db.flush()
        await audit.record(db, admin.id, "product.deactivate", "product", product.id, {"sku": product.sku})
    await db.refresh(product)
    response = product_admin_response(product)
    await _commit_and_sync(db, [product.id])
    return response


# --------------------------------------------------------------------------- fitment rules
async def _slug_map(db: AsyncSession) -> dict[uuid.UUID, str]:
    return {c.id: c.slug for c in (await db.execute(select(EquipmentCategory))).scalars()}


def _rule_response(r: ProductCompatibility, slugs: dict[uuid.UUID, str]) -> FitmentRuleAdminResponse:
    return FitmentRuleAdminResponse(
        **{
            k: getattr(r, k)
            for k in (
                "id",
                "product_id",
                "vessel_make",
                "vessel_model",
                "year_from",
                "year_to",
                "engine_make",
                "engine_model",
                "engine_year_from",
                "engine_year_to",
                "equipment_category_id",
                "equipment_make",
                "equipment_model",
                "fitment_type",
                "verification_status",
                "data_source",
                "source_url",
                "notes",
                "verified_at",
                "verified_by",
                "created_at",
            )
        },
        confidence_score=float(r.confidence_score),
        equipment_category=slugs.get(r.equipment_category_id) if r.equipment_category_id else None,
    )


async def _rule(db: AsyncSession, rule_id: uuid.UUID) -> ProductCompatibility:
    rule = (
        await db.execute(select(ProductCompatibility).where(ProductCompatibility.id == rule_id).with_for_update())
    ).scalar_one_or_none()
    if rule is None:
        raise not_found("Fitment rule")
    return rule


def _rule_snapshot(r: ProductCompatibility) -> dict:
    return {
        "product_id": str(r.product_id),
        "vessel_make": r.vessel_make,
        "vessel_model": r.vessel_model,
        "engine_make": r.engine_make,
        "engine_model": r.engine_model,
        "equipment_category_id": str(r.equipment_category_id) if r.equipment_category_id else None,
        "verification_status": r.verification_status,
        "confidence_score": str(r.confidence_score),
    }


@router.get("/fitment-rules", response_model=list[FitmentRuleAdminResponse])
async def list_fitment_rules(
    admin: AdminUser,
    verification_status: Literal["unverified", "verified", "rejected"] | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> list[FitmentRuleAdminResponse]:
    """Admin review queue (e.g. ``?verification_status=unverified``)."""
    q = select(ProductCompatibility).order_by(ProductCompatibility.created_at, ProductCompatibility.id)
    if verification_status:
        q = q.where(ProductCompatibility.verification_status == verification_status)
    slugs = await _slug_map(db)
    return [_rule_response(r, slugs) for r in (await db.execute(q.offset(offset).limit(limit))).scalars()]


@router.post("/fitment-rules/{rule_id}/verify", response_model=FitmentRuleAdminResponse)
async def verify_fitment_rule(
    rule_id: uuid.UUID,
    admin: AdminUser,
    body: FitmentRuleVerify | None = None,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> FitmentRuleAdminResponse:
    """Verify a rule (needs confidence ≥ FITMENT_MIN_CONFIDENCE). Only verified rules can produce a fit."""
    rule = await _rule(db, rule_id)
    body = body or FitmentRuleVerify()
    confidence = (
        Decimal(str(body.confidence_score))
        if body.confidence_score is not None
        else Decimal(str(rule.confidence_score))
    )
    minimum = get_settings().fitment_min_confidence
    if confidence < Decimal(str(minimum)):
        raise AppError(422, "confidence_too_low", f"A rule needs confidence ≥ {minimum} to be verified")
    rule.confidence_score = confidence
    if body.notes is not None:
        rule.notes = body.notes
    if body.source_url is not None:
        rule.source_url = body.source_url
    rule.verification_status = "verified"
    rule.verified_by = admin.id
    rule.verified_at = utcnow()
    await db.flush()
    await audit.record(db, admin.id, "fitment_rule.verify", "product_compatibility", rule.id, _rule_snapshot(rule))
    response = _rule_response(rule, await _slug_map(db))
    await _commit_and_sync(db, [rule.product_id])
    return response


@router.post("/fitment-rules/{rule_id}/reject", response_model=FitmentRuleAdminResponse)
async def reject_fitment_rule(
    rule_id: uuid.UUID,
    admin: AdminUser,
    body: FitmentRuleReject | None = None,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> FitmentRuleAdminResponse:
    rule = await _rule(db, rule_id)
    rule.verification_status = "rejected"
    rule.verified_by = admin.id
    rule.verified_at = utcnow()
    if body and body.notes is not None:
        rule.notes = body.notes
    await db.flush()
    await audit.record(db, admin.id, "fitment_rule.reject", "product_compatibility", rule.id, _rule_snapshot(rule))
    response = _rule_response(rule, await _slug_map(db))
    await _commit_and_sync(db, [rule.product_id])
    return response


@router.delete("/fitment-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fitment_rule(
    rule_id: uuid.UUID, admin: AdminUser, db: AsyncSession = Depends(get_db, scope="function")
) -> None:
    rule = await _rule(db, rule_id)
    product_id = rule.product_id
    await audit.record(db, admin.id, "fitment_rule.delete", "product_compatibility", rule.id, _rule_snapshot(rule))
    await db.delete(rule)
    await db.flush()
    await _commit_and_sync(db, [product_id])


@router.get("/{product_id}/fitment-rules", response_model=list[FitmentRuleAdminResponse])
async def product_fitment_rules(
    product_id: uuid.UUID, admin: AdminUser, db: AsyncSession = Depends(get_db, scope="function")
) -> list[FitmentRuleAdminResponse]:
    await _admin_product(db, product_id)
    slugs = await _slug_map(db)
    rules = (
        await db.execute(
            select(ProductCompatibility)
            .where(ProductCompatibility.product_id == product_id)
            .order_by(ProductCompatibility.created_at, ProductCompatibility.id)
        )
    ).scalars()
    return [_rule_response(r, slugs) for r in rules]


@router.post(
    "/{product_id}/fitment-rules", response_model=FitmentRuleAdminResponse, status_code=status.HTTP_201_CREATED
)
async def create_fitment_rule(
    product_id: uuid.UUID,
    body: FitmentRuleCreate,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> FitmentRuleAdminResponse:
    """New rules are always ``unverified`` (no fit until an admin verifies them)."""
    await _admin_product(db, product_id)
    data = body.model_dump()
    slug = data.pop("equipment_category")
    category_id = None
    if slug:
        cat = await boat_db.category_by_slug(db, slug)
        if cat is None:
            raise AppError(422, "unknown_equipment_category", f"Unknown equipment category '{slug}'")
        category_id = cat.id
    for lo, hi in (("year_from", "year_to"), ("engine_year_from", "engine_year_to")):
        if data[lo] is not None and data[hi] is not None and data[lo] > data[hi]:
            raise AppError(422, "invalid_range", f"{lo} must not be after {hi}")
    data["confidence_score"] = Decimal(str(data["confidence_score"]))
    rule = ProductCompatibility(
        product_id=product_id, equipment_category_id=category_id, verification_status="unverified", **data
    )
    db.add(rule)
    await db.flush()
    await db.refresh(rule)
    await audit.record(db, admin.id, "fitment_rule.create", "product_compatibility", rule.id, _rule_snapshot(rule))
    response = _rule_response(rule, await _slug_map(db))
    await _commit_and_sync(db, [product_id])
    return response


# =========================================================================== public detail
@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: uuid.UUID,
    principal: OptionalPrincipal,
    vessel_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> ProductResponse:
    product = await get_active_product(db, product_id)
    profile, _ = await vessel_profile(db, principal, vessel_id)
    result = await fitment.evaluate_product(db, product, profile) if profile else None
    return product_response(product, result)


async def _fitment_for(
    db: AsyncSession, principal: Principal | None, product_id: uuid.UUID, vessel_id: uuid.UUID
) -> FitmentResult:
    product = await get_active_product(db, product_id)
    vessel = await resolve_vessel(db, principal, vessel_id)
    profile = await fitment.load_vessel_profile(db, vessel)
    return await fitment.evaluate_product(db, product, profile)


@router.get("/{product_id}/fitment", response_model=FitmentResult)
async def product_fitment(
    product_id: uuid.UUID,
    principal: OptionalPrincipal,
    vessel_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> FitmentResult:
    """Compatibility check for one of the caller's vessels (auth + ownership required)."""
    return await _fitment_for(db, principal, product_id, vessel_id)


@router.get("/{product_id}/compatibility", response_model=CompatibilityResponse)
async def product_compatibility(
    product_id: uuid.UUID, db: AsyncSession = Depends(get_db, scope="function")
) -> CompatibilityResponse:
    """Public "known to fit" list — verified rules at or above the confidence threshold only."""
    product = await get_active_product(db, product_id)
    threshold = Decimal(str(get_settings().fitment_min_confidence))
    slugs = await _slug_map(db)
    rules = (
        await db.execute(
            select(ProductCompatibility)
            .where(
                ProductCompatibility.product_id == product.id,
                ProductCompatibility.verification_status == "verified",
                ProductCompatibility.confidence_score >= threshold,
            )
            .order_by(
                ProductCompatibility.vessel_make,
                ProductCompatibility.engine_make,
                ProductCompatibility.engine_model,
                ProductCompatibility.id,
            )
        )
    ).scalars()
    known = [
        KnownFit(
            rule_id=r.id,
            vessel_make=r.vessel_make,
            vessel_model=r.vessel_model,
            year_from=r.year_from,
            year_to=r.year_to,
            engine_make=r.engine_make,
            engine_model=r.engine_model,
            engine_year_from=r.engine_year_from,
            engine_year_to=r.engine_year_to,
            equipment_category=slugs.get(r.equipment_category_id) if r.equipment_category_id else None,
            equipment_make=r.equipment_make,
            equipment_model=r.equipment_model,
            fitment_type=r.fitment_type,
            confidence_score=float(r.confidence_score),
            data_source=r.data_source,
            is_synthetic=r.data_source == "synthetic_fixture",
            notes=r.notes,
        )
        for r in rules
    ]
    return CompatibilityResponse(
        product_id=product.id,
        sku=product.sku,
        fitment_scope=product.fitment_scope,
        universal=product.fitment_scope == "universal",
        oem_part_numbers=list(product.oem_part_numbers or []),
        known_to_fit=known,
    )
