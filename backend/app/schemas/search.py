"""Product search response."""

from typing import Literal

from app.schemas.common import APIModel
from app.schemas.product import ProductResponse, VesselRef


class FacetValue(APIModel):
    value: str | bool | None
    count: int


class SearchResponse(APIModel):
    items: list[ProductResponse]
    total: int
    offset: int
    limit: int
    # postgres | typesense | postgres_fallback (Typesense failed; database search used)
    engine: Literal["postgres", "typesense", "postgres_fallback"]
    notice: str | None = None
    facets: dict[str, list[FacetValue]] = {}
    vessel: VesselRef | None = None
