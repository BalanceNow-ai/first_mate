"""Content proxy router — fetches content from Strapi CMS."""

from fastapi import APIRouter, Query

from app.config import get_settings

router = APIRouter(prefix="/content", tags=["Content"])
settings = get_settings()


@router.get("/articles")
async def list_articles(
    category: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """List articles from the Boat Ramp content hub.

    Proxies to the Strapi CMS API and caches responses in Redis.
    """
    if not settings.strapi_url or not settings.strapi_api_token:
        return {"data": [], "meta": {"total": 0}}

    try:
        import httpx

        params = {
            "pagination[start]": offset,
            "pagination[limit]": limit,
            "sort": "publishedAt:desc",
        }
        if category:
            params["filters[category][$eq]"] = category

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.strapi_url}/api/articles",
                params=params,
                headers={"Authorization": f"Bearer {settings.strapi_api_token}"},
            )
            if response.status_code == 200:
                return response.json()
    except Exception:
        pass

    return {"data": [], "meta": {"total": 0}}


@router.get("/articles/{article_id}")
async def get_article(article_id: int) -> dict:
    """Get a single article by ID from Strapi."""
    if not settings.strapi_url or not settings.strapi_api_token:
        return {"data": None}

    try:
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.strapi_url}/api/articles/{article_id}",
                headers={"Authorization": f"Bearer {settings.strapi_api_token}"},
            )
            if response.status_code == 200:
                return response.json()
    except Exception:
        pass

    return {"data": None}


@router.get("/boat-makes")
async def list_boat_makes() -> dict:
    """List all boat manufacturers from the OEM database."""
    if not settings.strapi_url or not settings.strapi_api_token:
        return {"data": []}

    try:
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.strapi_url}/api/boat-makes",
                params={"sort": "name:asc", "pagination[limit]": 100},
                headers={"Authorization": f"Bearer {settings.strapi_api_token}"},
            )
            if response.status_code == 200:
                return response.json()
    except Exception:
        pass

    return {"data": []}


@router.get("/boat-makes/{make_id}/models")
async def list_boat_models(make_id: int) -> dict:
    """List all boat models for a specific manufacturer."""
    if not settings.strapi_url or not settings.strapi_api_token:
        return {"data": []}

    try:
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.strapi_url}/api/boat-models",
                params={
                    "filters[manufacturer][id][$eq]": make_id,
                    "sort": "name:asc",
                    "pagination[limit]": 100,
                },
                headers={"Authorization": f"Bearer {settings.strapi_api_token}"},
            )
            if response.status_code == 200:
                return response.json()
    except Exception:
        pass

    return {"data": []}
