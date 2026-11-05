"""Voyage spares checklists — owner-scoped (another owner's vessel or item → 404)."""

from __future__ import annotations

import re
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import mutation_limit
from app.database import get_db
from app.middleware.auth import CurrentUserId
from app.models.checklist import VoyageChecklist
from app.models.product import Product
from app.routers.vessels import get_owned_vessel
from app.schemas.checklist import (
    AddMissingRequest,
    AddMissingResponse,
    ChecklistItemResponse,
    ChecklistSetResponse,
    ItemCheck,
    ManualLink,
    Tier,
    TierResponse,
)
from app.services import checklists as svc
from app.services import fitment

router = APIRouter(prefix="/checklists", tags=["Voyage Checklists"])


@router.post(
    "/vessel/{vessel_id}/generate",
    response_model=ChecklistSetResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(mutation_limit())],
)
async def generate_checklists(
    vessel_id: uuid.UUID,
    user_id: CurrentUserId,
    regenerate: bool = False,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> ChecklistSetResponse:
    """Create the three tiered checklists, tailored to the vessel (409 if they exist,
    unless ``regenerate=true`` which rebuilds them and keeps checked state by template key)."""
    vessel = await get_owned_vessel(db, vessel_id, user_id)
    await svc.generate(db, vessel, regenerate=regenerate)
    return await svc.build_set(db, vessel)


@router.get("/vessel/{vessel_id}", response_model=ChecklistSetResponse)
async def get_checklists(
    vessel_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> ChecklistSetResponse:
    """All tiers; each tier lists its cumulative items with ``introduced_in``."""
    vessel = await get_owned_vessel(db, vessel_id, user_id)
    return await svc.build_set(db, vessel)


@router.get("/vessel/{vessel_id}/tiers/{tier}", response_model=TierResponse)
async def get_tier(
    vessel_id: uuid.UUID, tier: Tier, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> TierResponse:
    vessel = await get_owned_vessel(db, vessel_id, user_id)
    checklists = await svc.require_checklists(db, vessel)
    profile = await fitment.load_vessel_profile(db, vessel)
    links = await svc.refresh_links(db, profile, [i for c in checklists for i in c.items])
    return svc.tier_response(checklists, tier, links, vessel, profile)


@router.delete("/vessel/{vessel_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(mutation_limit())])
async def delete_checklists(
    vessel_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> None:
    vessel = await get_owned_vessel(db, vessel_id, user_id)
    await db.execute(delete(VoyageChecklist).where(VoyageChecklist.vessel_id == vessel.id))


async def _item_view(db: AsyncSession, item, checklist, vessel, warning: str | None = None) -> ChecklistItemResponse:
    profile = await fitment.load_vessel_profile(db, vessel)
    links = await svc.refresh_links(db, profile, [item])
    return svc.item_response(checklist.tier, item, links[item.id], vessel, profile, warning)


@router.patch("/items/{item_id}", response_model=ChecklistItemResponse, dependencies=[Depends(mutation_limit())])
async def check_item(
    item_id: uuid.UUID, body: ItemCheck, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> ChecklistItemResponse:
    """Set the checked ("already on board") state; shared by every tier that includes it."""
    item, checklist, vessel = await svc.owned_item(db, item_id, user_id)
    svc.set_checked(item, body.is_checked)
    await db.flush()
    return await _item_view(db, item, checklist, vessel)


@router.post("/items/{item_id}/toggle", response_model=ChecklistItemResponse, dependencies=[Depends(mutation_limit())])
async def toggle_item(
    item_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> ChecklistItemResponse:
    item, checklist, vessel = await svc.owned_item(db, item_id, user_id)
    svc.set_checked(item, not item.is_checked)
    await db.flush()
    return await _item_view(db, item, checklist, vessel)


@router.put("/items/{item_id}/link", response_model=ChecklistItemResponse, dependencies=[Depends(mutation_limit())])
async def link_item(
    item_id: uuid.UUID, body: ManualLink, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> ChecklistItemResponse:
    """Owner-chosen product: verified mismatch → 409; unknown fit → ``user_linked_unverified`` + warning."""
    item, checklist, vessel = await svc.owned_item(db, item_id, user_id)
    profile = await fitment.load_vessel_profile(db, vessel)
    warning = await svc.manual_link(db, profile, item, body.product_id)
    return await _item_view(db, item, checklist, vessel, warning)


@router.post(
    "/vessel/{vessel_id}/add-missing-to-cart",
    response_model=AddMissingResponse,
    dependencies=[Depends(mutation_limit())],
)
async def add_missing_to_cart(
    vessel_id: uuid.UUID,
    body: AddMissingRequest,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> AddMissingResponse:
    """Ensure the cart holds the unchecked, linked items of a tier. Repeat calls do not add more."""
    vessel = await get_owned_vessel(db, vessel_id, user_id)
    return AddMissingResponse(**await svc.add_missing_to_cart(db, user_id, vessel, body.tier))


@router.get("/vessel/{vessel_id}/export")
async def export_checklist(
    vessel_id: uuid.UUID,
    user_id: CurrentUserId,
    tier: Tier = Query(...),
    format: Literal["csv", "html"] = Query("html"),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> Response:
    """Printable HTML or CSV of a tier (cumulative), with checkboxes and the disclaimer."""
    vessel = await get_owned_vessel(db, vessel_id, user_id)
    checklists = await svc.require_checklists(db, vessel)
    profile = await fitment.load_vessel_profile(db, vessel)
    await svc.refresh_links(db, profile, [i for c in checklists for i in c.items])
    ids = {i.product_id for c in checklists for i in c.items if i.product_id}
    products = (
        {p.id: p for p in (await db.execute(select(Product).where(Product.id.in_(ids)))).scalars()} if ids else {}
    )
    rows = svc.export_rows(checklists, tier, products)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", vessel.nickname).strip("-").lower() or "vessel"
    filename = f"{slug}-{tier}.{format}"
    if format == "csv":
        return Response(
            svc.to_csv(rows, profile.label, tier),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    return Response(
        svc.to_html(rows, vessel, profile.label, tier),
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
        },
    )
