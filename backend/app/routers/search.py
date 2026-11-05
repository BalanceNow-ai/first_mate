"""Product search: PostgreSQL ILIKE ranking or Typesense, always followed by central fitment.

``SEARCH_BACKEND=typesense`` queries the index (pre-filtered by verified fitment keys when
``compatible_only``) and loads the hits from PostgreSQL so prices/stock are current. Any
Typesense failure falls back to PostgreSQL and the response says so (``engine``).
"""

from __future__ import annotations

import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError
from app.core.rate_limit import rate_limit
from app.database import get_db
from app.middleware.auth import OptionalPrincipal
from app.models.product import Product
from app.routers.products import filters_dependency
from app.schemas.search import FacetValue, SearchResponse
from app.services import fitment, search_index
from app.services.catalogue import product_response
from app.services.product_catalogue import ProductFilters, list_products, vessel_profile

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/search", tags=["Search"])

SearchSort = Literal["relevance", "name", "price_asc", "price_desc", "newest"]


async def _postgres_facets(db: AsyncSession, filters: ProductFilters) -> dict[str, list[FacetValue]]:
    clauses = filters.clauses()
    out: dict[str, list[FacetValue]] = {}
    for name, col in (("category", Product.category), ("brand", Product.brand), ("part_role", Product.part_role)):
        rows = (
            await db.execute(
                select(col, func.count())
                .where(*clauses, col.isnot(None))
                .group_by(col)
                .order_by(func.count().desc(), col)
            )
        ).all()
        out[name] = [FacetValue(value=v, count=c) for v, c in rows]
    in_stock = Product.stock_quantity > 0
    rows = (await db.execute(select(in_stock, func.count()).where(*clauses).group_by(in_stock))).all()
    out["in_stock"] = [FacetValue(value=bool(v), count=c) for v, c in sorted(rows, key=lambda r: not r[0])]
    return out


async def _postgres_search(db, filters, sort, offset, limit, profile, compatible_only):
    page = await list_products(
        db, filters, sort=sort, offset=offset, limit=limit, profile=profile, compatible_only=compatible_only
    )
    return page.items, page.total, page.fitment, await _postgres_facets(db, filters)


async def _typesense_search(db, filters, sort, offset, limit, profile, compatible_only, client=None):
    settings = get_settings()
    own = client is None
    client = client or search_index.TypesenseClient.from_settings(settings)
    notice = None
    try:
        window = settings.typesense_compatible_window if (profile is not None and compatible_only) else None
        params = {
            "q": (filters.q or "").strip() or "*",
            "query_by": search_index.QUERY_BY,
            "facet_by": ",".join(search_index.FACET_FIELDS),
            "offset": 0 if window else offset,
            "limit": window or limit,
        }
        fb = search_index.filter_by(filters, profile, compatible_only)
        if fb:
            params["filter_by"] = fb
        if sort == "price_asc":
            params["sort_by"] = "effective_price_cents:asc"
        elif sort == "price_desc":
            params["sort_by"] = "effective_price_cents:desc"
        raw = await client.search(params)
    finally:
        if own:
            await client.close()

    try:
        hit_ids = [uuid.UUID(h["document"]["id"]) for h in raw.get("hits", [])]
        found = int(raw.get("found", 0))
    except (KeyError, TypeError, ValueError) as exc:
        raise search_index.TypesenseError("Malformed Typesense hits") from exc
    rows = (
        {
            p.id: p
            for p in (
                await db.execute(select(Product).where(Product.id.in_(hit_ids), Product.is_active.is_(True)))
            ).scalars()
        }
        if hit_ids
        else {}
    )
    products = [rows[i] for i in hit_ids if i in rows]  # index order; stale/inactive hits dropped
    facets = {
        k: [FacetValue(value=v["value"], count=v["count"]) for v in vals]
        for k, vals in search_index.parse_facets(raw).items()
    }
    if profile is None:
        return products, max(found - (len(hit_ids) - len(products)), 0), {}, facets, notice
    results = await fitment.evaluate_products(db, products, profile)
    if not compatible_only:
        return products, max(found - (len(hit_ids) - len(products)), 0), results, facets, notice
    exact = [p for p in products if results[p.id].status in fitment.POSITIVE_STATUSES]
    if found > len(hit_ids):
        notice = f"Compatible results limited to the top {len(hit_ids)} search matches"
    return exact[offset : offset + limit], len(exact), results, facets, notice


@router.get(
    "/products",
    response_model=SearchResponse,
    dependencies=[Depends(rate_limit("search", lambda: get_settings().rate_limit_search_per_minute))],
)
async def search_products(
    principal: OptionalPrincipal,
    filters: ProductFilters = Depends(filters_dependency),
    vessel_id: uuid.UUID | None = None,
    compatible_only: bool = False,
    sort: SearchSort = "relevance",
    offset: int = Query(0, ge=0),
    limit: int | None = Query(None, ge=1),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> SearchResponse:
    """Search active products (``q`` + filters). With ``vessel_id`` results carry fitment."""
    settings = get_settings()
    if compatible_only and vessel_id is None:
        raise AppError(422, "vessel_required", "compatible_only requires vessel_id")
    limit = min(limit or settings.catalogue_default_page_size, settings.catalogue_max_page_size)
    profile, vessel_ref = await vessel_profile(db, principal, vessel_id)
    engine, notice = "postgres", None
    if settings.search_backend == "typesense":
        try:
            products, total, results, facets, notice = await _typesense_search(
                db, filters, sort, offset, limit, profile, compatible_only
            )
            return SearchResponse(
                items=[product_response(p, results.get(p.id)) for p in products],
                total=total,
                offset=offset,
                limit=limit,
                engine="typesense",
                notice=notice,
                facets=facets,
                vessel=vessel_ref,
            )
        except search_index.TypesenseError as exc:
            logger.warning("Typesense search failed (%s); falling back to PostgreSQL", exc)
            engine = "postgres_fallback"
            notice = "The search index is unavailable; showing database search results"
    products, total, results, facets = await _postgres_search(
        db, filters, sort, offset, limit, profile, compatible_only
    )
    return SearchResponse(
        items=[product_response(p, results.get(p.id)) for p in products],
        total=total,
        offset=offset,
        limit=limit,
        engine=engine,
        notice=notice,
        facets=facets,
        vessel=vessel_ref,
    )
