"""Voyage checklist management router."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.middleware.auth import CurrentUserId
from app.models.checklist import ChecklistItem, VoyageChecklist
from app.models.product import Product
from app.models.vessel import Vessel

router = APIRouter(prefix="/checklists", tags=["Voyage Checklists"])

# Default checklist templates for each tier
GRAB_AND_GO_ITEMS = [
    {"system": "Engine (Outboard)", "item_name": "Spare Propeller & Prop Nut/Split Pin", "quantity": 1},
    {"system": "Engine (Outboard)", "item_name": "Spare Engine Fuel Filter (primary)", "quantity": 2},
    {"system": "Engine (Outboard)", "item_name": "Spare Spark Plugs", "quantity": 1},
    {"system": "Engine (Outboard)", "item_name": "Spare Kill Switch Lanyard", "quantity": 1},
    {"system": "Electrical", "item_name": "Spare Navigation Light Bulbs", "quantity": 1},
    {"system": "Electrical", "item_name": "Assorted Fuses (5A, 10A, 15A)", "quantity": 1},
    {"system": "General", "item_name": "Duct Tape", "quantity": 1},
    {"system": "General", "item_name": "Zip Ties (assorted sizes)", "quantity": 1},
    {"system": "General", "item_name": "Stainless Steel Hose Clamps (assorted)", "quantity": 1},
    {"system": "General", "item_name": "Emergency Wooden Bungs (tapered)", "quantity": 1},
    {"system": "Tools", "item_name": "Shifting Spanner, Pliers, Screwdriver Set, Prop Spanner, Spark Plug Spanner", "quantity": 1},
]

COASTAL_CRUISING_ITEMS = [
    {"system": "Engine (Outboard)", "item_name": "Spare Water Pump Impeller & Gasket", "quantity": 1},
    {"system": "Engine (Outboard)", "item_name": "Spare Thermostat & Gasket", "quantity": 1},
    {"system": "Engine (Outboard)", "item_name": "Spare Alternator/Serpentine Belt", "quantity": 1},
    {"system": "Engine (Outboard)", "item_name": "Engine Oil (1L top-up)", "quantity": 1},
    {"system": "Plumbing", "item_name": "Spare Bilge Pump (cartridge or complete)", "quantity": 1},
    {"system": "Plumbing", "item_name": "Spare Toilet Duckbill/Joker Valves", "quantity": 1},
    {"system": "Electrical", "item_name": "Spare Battery Terminals", "quantity": 1},
    {"system": "Electrical", "item_name": "Small Spool of Marine-Grade Electrical Wire", "quantity": 1},
    {"system": "Electrical", "item_name": "Butt Connectors & Crimper", "quantity": 1},
    {"system": "Tools", "item_name": "Full Socket Set, Multimeter, Strap Wrench", "quantity": 1},
]

OFFSHORE_PASSAGE_ITEMS = [
    {"system": "Engine (Outboard)", "item_name": "Spare Fuel Pump", "quantity": 1},
    {"system": "Engine (Outboard)", "item_name": "Spare Ignition Coil", "quantity": 1},
    {"system": "Engine (Outboard)", "item_name": "Full Gasket Set", "quantity": 1},
    {"system": "Engine (Outboard)", "item_name": "Engine Oil & Filters for full change", "quantity": 1},
    {"system": "Plumbing", "item_name": "Complete Spare Freshwater Pump", "quantity": 1},
    {"system": "Plumbing", "item_name": "Major Bilge Pump Rebuild Kit", "quantity": 1},
    {"system": "Plumbing", "item_name": "Assorted Hose & Fittings", "quantity": 1},
    {"system": "Electrical", "item_name": "Spare VHF Antenna", "quantity": 1},
    {"system": "Electrical", "item_name": "Spare GPS Antenna", "quantity": 1},
    {"system": "Steering", "item_name": "Spare Hydraulic Steering Fluid & Bleed Kit", "quantity": 1},
]


def _extract_search_keywords(item_name: str) -> list[str]:
    """Extract meaningful search keywords from a checklist item name.

    Strips common prefixes like 'Spare', 'Complete', 'Full' and returns
    the core keywords for product matching.
    """
    noise = {"spare", "complete", "full", "assorted", "small", "major", "emergency"}
    words = item_name.split(",")[0].split("&")[0].strip().split()
    keywords = [w for w in words if w.lower().strip("()") not in noise]
    return keywords


async def _find_product_match(db: AsyncSession, item_name: str) -> uuid.UUID | None:
    """Search for a single unambiguous product match for a checklist item.

    Uses ILIKE keyword search against the Product name. Returns the product_id
    only if exactly one active product matches; otherwise returns None.
    """
    keywords = _extract_search_keywords(item_name)
    if not keywords:
        return None

    # Build a query that matches ALL keywords
    query = select(Product).where(Product.is_active.is_(True))
    for keyword in keywords[:3]:  # Use up to 3 keywords to avoid over-filtering
        query = query.where(Product.name.ilike(f"%{keyword}%"))

    result = await db.execute(query)
    matches = result.scalars().all()

    if len(matches) == 1:
        return matches[0].id

    # If too many matches, try more keywords to narrow down
    if len(matches) > 1 and len(keywords) > 3:
        narrow_query = select(Product).where(Product.is_active.is_(True))
        for keyword in keywords:
            narrow_query = narrow_query.where(Product.name.ilike(f"%{keyword}%"))
        narrow_result = await db.execute(narrow_query)
        narrow_matches = narrow_result.scalars().all()
        if len(narrow_matches) == 1:
            return narrow_matches[0].id

    return None


class LinkProductRequest(BaseModel):
    product_id: uuid.UUID


@router.get("/vessel/{vessel_id}", response_model=list[dict])
async def get_vessel_checklists(
    vessel_id: uuid.UUID,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Get all voyage checklists for a vessel."""
    # Verify vessel belongs to user
    vessel_result = await db.execute(
        select(Vessel).where(Vessel.id == vessel_id, Vessel.user_id == user_id)
    )
    if not vessel_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vessel not found")

    result = await db.execute(
        select(VoyageChecklist)
        .where(VoyageChecklist.vessel_id == vessel_id)
        .options(selectinload(VoyageChecklist.items))
        .order_by(VoyageChecklist.tier)
    )
    checklists = result.scalars().all()

    return [
        {
            "id": c.id,
            "vessel_id": c.vessel_id,
            "tier": c.tier,
            "name": c.name,
            "items": [
                {
                    "id": item.id,
                    "system": item.system,
                    "item_name": item.item_name,
                    "description": item.description,
                    "quantity": item.quantity,
                    "product_id": item.product_id,
                    "is_checked": item.is_checked,
                }
                for item in c.items
            ],
            "created_at": c.created_at,
        }
        for c in checklists
    ]


@router.post("/vessel/{vessel_id}/generate", status_code=status.HTTP_201_CREATED)
async def generate_checklists(
    vessel_id: uuid.UUID,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Generate default voyage checklists for a vessel.

    Creates three tiered checklists (Grab & Go, Coastal Cruising, Offshore
    Passage) pre-populated with recommended spare parts and equipment.
    Performs keyword search against the product catalogue to auto-link
    matching products to checklist items.
    """
    # Verify vessel belongs to user
    vessel_result = await db.execute(
        select(Vessel).where(Vessel.id == vessel_id, Vessel.user_id == user_id)
    )
    vessel = vessel_result.scalar_one_or_none()
    if not vessel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vessel not found")

    # Check if checklists already exist
    existing = await db.execute(
        select(VoyageChecklist).where(VoyageChecklist.vessel_id == vessel_id)
    )
    if existing.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Checklists already exist for this vessel. Delete them first to regenerate.",
        )

    tiers = [
        ("grab_and_go", "Grab & Go Kit (Day Trips)", GRAB_AND_GO_ITEMS),
        ("coastal_cruising", "Coastal Cruising Kit (Weekend & Multi-Day)", COASTAL_CRUISING_ITEMS),
        ("offshore_passage", "Offshore Passage Kit (Extended Voyages)", OFFSHORE_PASSAGE_ITEMS),
    ]

    created = []
    linked_count = 0
    for tier_key, tier_name, items in tiers:
        checklist = VoyageChecklist(vessel_id=vessel_id, tier=tier_key, name=tier_name)
        db.add(checklist)
        await db.flush()

        for item_data in items:
            product_id = await _find_product_match(db, item_data["item_name"])
            if product_id:
                linked_count += 1

            item = ChecklistItem(
                checklist_id=checklist.id,
                system=item_data["system"],
                item_name=item_data["item_name"],
                quantity=item_data["quantity"],
                product_id=product_id,
            )
            db.add(item)

        created.append({"tier": tier_key, "name": tier_name, "items_count": len(items)})

    await db.flush()
    return {
        "message": "Checklists generated",
        "checklists": created,
        "products_linked": linked_count,
    }


@router.patch("/items/{item_id}/toggle")
async def toggle_checklist_item(
    item_id: uuid.UUID,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Toggle the checked state of a checklist item."""
    result = await db.execute(
        select(ChecklistItem)
        .join(VoyageChecklist)
        .join(Vessel)
        .where(ChecklistItem.id == item_id, Vessel.user_id == user_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Checklist item not found",
        )

    item.is_checked = not item.is_checked
    await db.flush()
    return {"is_checked": item.is_checked}


@router.patch("/items/{item_id}/link-product")
async def link_product_to_item(
    item_id: uuid.UUID,
    body: LinkProductRequest,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Link a product to a checklist item."""
    # Verify ownership via joins
    result = await db.execute(
        select(ChecklistItem)
        .join(VoyageChecklist)
        .join(Vessel)
        .where(ChecklistItem.id == item_id, Vessel.user_id == user_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Checklist item not found",
        )

    # Verify product exists
    product_result = await db.execute(
        select(Product).where(Product.id == body.product_id, Product.is_active.is_(True))
    )
    if not product_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    item.product_id = body.product_id
    await db.flush()
    return {"product_id": str(item.product_id), "item_name": item.item_name}


@router.post("/vessel/{vessel_id}/add-unchecked-to-cart")
async def add_unchecked_to_cart(
    vessel_id: uuid.UUID,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Add all unchecked checklist items with linked products to the cart."""
    from app.models.cart import CartItem

    # Verify vessel belongs to user
    vessel_result = await db.execute(
        select(Vessel).where(Vessel.id == vessel_id, Vessel.user_id == user_id)
    )
    if not vessel_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vessel not found")

    # Get unchecked items with linked products
    result = await db.execute(
        select(ChecklistItem)
        .join(VoyageChecklist)
        .where(
            VoyageChecklist.vessel_id == vessel_id,
            ChecklistItem.is_checked.is_(False),
            ChecklistItem.product_id.isnot(None),
        )
    )
    unchecked_items = result.scalars().all()

    if not unchecked_items:
        return {"message": "No items to add", "added_count": 0}

    added_count = 0
    for checklist_item in unchecked_items:
        # Check if already in cart
        existing_result = await db.execute(
            select(CartItem).where(
                CartItem.user_id == user_id,
                CartItem.product_id == checklist_item.product_id,
            )
        )
        existing = existing_result.scalar_one_or_none()

        if existing:
            existing.quantity += checklist_item.quantity
        else:
            cart_item = CartItem(
                user_id=user_id,
                product_id=checklist_item.product_id,
                quantity=checklist_item.quantity,
            )
            db.add(cart_item)

        added_count += 1

    await db.flush()
    return {"message": f"Added {added_count} items to cart", "added_count": added_count}
