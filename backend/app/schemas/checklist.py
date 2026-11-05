"""Voyage checklist schemas."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import APIModel, StrictInput
from app.schemas.product import FitmentResult, ProductResponse, VesselRef

Tier = Literal["grab_and_go", "coastal_cruising", "offshore_passage"]


class SearchHint(APIModel):
    q: str
    part_role: str | None
    vessel_id: uuid.UUID
    path: str  # e.g. /api/v1/search/products?part_role=impeller&vessel_id=...


class ChecklistItemResponse(APIModel):
    id: uuid.UUID
    template_key: str | None
    introduced_in: Tier
    position: int
    system: str
    item_name: str
    description: str | None
    quantity: int
    part_role: str | None
    applicability: Literal["applies", "if_fitted"] | str
    is_checked: bool
    checked_at: datetime | None
    link_status: Literal["verified_fit", "universal", "user_linked_unverified", "unlinked"]
    product: ProductResponse | None = None
    fitment: FitmentResult | None = None
    alternatives: list[ProductResponse] = []
    search_hint: SearchHint | None = None
    warning: str | None = None


class TierResponse(APIModel):
    tier: Tier
    name: str
    checklist_id: uuid.UUID
    items: list[ChecklistItemResponse]
    total: int
    checked: int
    unchecked_linked: int


class ChecklistSetResponse(APIModel):
    vessel: VesselRef
    generated: bool
    template_version: str | None
    disclaimer: str
    tiers: list[TierResponse]


class ItemCheck(StrictInput):
    is_checked: bool


class ManualLink(StrictInput):
    product_id: uuid.UUID


class AddMissingRequest(StrictInput):
    tier: Tier


class AddMissingLine(APIModel):
    item_id: uuid.UUID
    template_key: str | None
    item_name: str
    product_id: uuid.UUID
    requested: int
    added: int
    quantity_in_cart: int
    status: str  # added | already_satisfied | insufficient_stock | unavailable | limited
    message: str | None = None


class SkippedItem(APIModel):
    item_id: uuid.UUID
    item_name: str
    reason: Literal["unlinked"]


class AddMissingResponse(APIModel):
    tier: Tier
    added_count: int
    lines: list[AddMissingLine]
    skipped: list[SkippedItem] = Field(default_factory=list)
