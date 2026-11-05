"""Content (The Boat Ramp articles) contracts."""

from __future__ import annotations

from app.schemas.common import APIModel


class ArticleSummary(APIModel):
    id: str
    slug: str
    title: str
    summary: str
    category: str | None = None
    author: str | None = None
    published_at: str | None = None
    image_url: str | None = None
    is_synthetic: bool


class Article(ArticleSummary):
    body: str


class ArticleList(APIModel):
    available: bool
    provider: str
    items: list[ArticleSummary]
    reason: str | None
