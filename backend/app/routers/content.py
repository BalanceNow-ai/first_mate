"""Content hub articles served through the CMS adapter (Strapi or a synthetic fixture).

The Phase-7 boat make/model proxies were removed: the boat database lives in
PostgreSQL and is served by the vessel-intelligence endpoints.
"""

from fastapi import APIRouter

from app.core.errors import AppError, not_found
from app.schemas.content import Article, ArticleList
from app.services import cms

router = APIRouter(prefix="/content", tags=["Content"])


@router.get("/articles", response_model=ArticleList)
async def list_articles(category: str | None = None) -> dict:
    """Articles, or ``{"available": false, "items": []}`` when the CMS is unavailable."""
    result = (await cms.fetch_articles()).as_dict()
    if category and result["available"]:
        result["items"] = [a for a in result["items"] if (a.get("category") or "").lower() == category.lower()]
    return result


@router.get("/articles/{slug}", response_model=Article)
async def get_article(slug: str) -> dict:
    result = await cms.fetch_articles()
    if not result.available:
        raise AppError(503, "content_unavailable", "Content is unavailable right now", extra={"reason": result.reason})
    article = next((a for a in result.items if a["slug"] == slug), None)
    if article is None:
        raise not_found("Article")
    return article
