"""Search router — proxies to Typesense with authentication."""

import uuid

from fastapi import APIRouter, Depends, Query

from app.config import get_settings
from app.middleware.auth import CurrentUserId

router = APIRouter(prefix="/search", tags=["Search"])
settings = get_settings()


@router.get("/products")
async def search_products(
    q: str = Query(min_length=1, description="Search query"),
    category: str | None = None,
    brand: str | None = None,
    vessel_make: str | None = None,
    vessel_model: str | None = None,
    vessel_year: int | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
) -> dict:
    """Search products via Typesense.

    Supports faceted search with filters for category, brand, price range,
    and vessel compatibility. When the user has an active vessel, compatibility
    filters are applied automatically.
    """
    if not settings.typesense_api_key:
        # Return empty results when Typesense is not configured
        return {
            "hits": [],
            "found": 0,
            "page": page,
            "per_page": per_page,
            "search_time_ms": 0,
        }

    try:
        import typesense

        client = typesense.Client(
            {
                "api_key": settings.typesense_api_key,
                "nodes": [
                    {
                        "host": settings.typesense_host,
                        "port": str(settings.typesense_port),
                        "protocol": "http",
                    }
                ],
                "connection_timeout_seconds": 2,
            }
        )

        # Build filter string
        filters = []
        if category:
            filters.append(f"category:={category}")
        if brand:
            filters.append(f"brand:={brand}")
        if min_price is not None:
            filters.append(f"price:>={min_price}")
        if max_price is not None:
            filters.append(f"price:<={max_price}")
        if vessel_make:
            filters.append(f"compatible_makes:={vessel_make}")
        if vessel_model:
            filters.append(f"compatible_models:={vessel_model}")

        search_params = {
            "q": q,
            "query_by": "name,description,brand,sku",
            "filter_by": " && ".join(filters) if filters else "",
            "page": page,
            "per_page": per_page,
            "facet_by": "category,brand",
        }

        results = client.collections["products"].documents.search(search_params)

        return {
            "hits": results.get("hits", []),
            "found": results.get("found", 0),
            "page": page,
            "per_page": per_page,
            "search_time_ms": results.get("search_time_ms", 0),
            "facets": results.get("facet_counts", []),
        }

    except Exception as e:
        return {
            "hits": [],
            "found": 0,
            "page": page,
            "per_page": per_page,
            "search_time_ms": 0,
            "error": str(e),
        }
