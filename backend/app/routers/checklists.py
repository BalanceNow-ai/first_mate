"""Voyage checklist management router."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.middleware.auth import CurrentUserId
from app.models.checklist import ChecklistItem, VoyageChecklist
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
    for tier_key, tier_name, items in tiers:
        checklist = VoyageChecklist(vessel_id=vessel_id, tier=tier_key, name=tier_name)
        db.add(checklist)
        await db.flush()

        for item_data in items:
            item = ChecklistItem(
                checklist_id=checklist.id,
                system=item_data["system"],
                item_name=item_data["item_name"],
                quantity=item_data["quantity"],
            )
            db.add(item)

        created.append({"tier": tier_key, "name": tier_name, "items_count": len(items)})

    await db.flush()
    return {"message": "Checklists generated", "checklists": created}


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
