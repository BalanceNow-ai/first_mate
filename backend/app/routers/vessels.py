"""Vessel (My Vessel Garage) CRUD router."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import CurrentUserId
from app.models.vessel import Vessel
from app.schemas.vessel import VesselCreate, VesselResponse, VesselUpdate

router = APIRouter(prefix="/vessels", tags=["Vessels"])


@router.get("/", response_model=list[VesselResponse])
async def list_vessels(
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> list[Vessel]:
    """List all vessels in the current user's garage."""
    result = await db.execute(
        select(Vessel).where(Vessel.user_id == user_id).order_by(Vessel.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/", response_model=VesselResponse, status_code=status.HTTP_201_CREATED)
async def create_vessel(
    vessel_data: VesselCreate,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> Vessel:
    """Add a new vessel to the user's garage."""
    # If this is set as primary, unset any existing primary vessel
    if vessel_data.is_primary:
        result = await db.execute(
            select(Vessel).where(Vessel.user_id == user_id, Vessel.is_primary.is_(True))
        )
        for existing_primary in result.scalars().all():
            existing_primary.is_primary = False

    vessel = Vessel(user_id=user_id, **vessel_data.model_dump())
    db.add(vessel)
    await db.flush()
    return vessel


@router.get("/{vessel_id}", response_model=VesselResponse)
async def get_vessel(
    vessel_id: uuid.UUID,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> Vessel:
    """Get a specific vessel from the user's garage."""
    result = await db.execute(
        select(Vessel).where(Vessel.id == vessel_id, Vessel.user_id == user_id)
    )
    vessel = result.scalar_one_or_none()
    if not vessel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vessel not found")
    return vessel


@router.patch("/{vessel_id}", response_model=VesselResponse)
async def update_vessel(
    vessel_id: uuid.UUID,
    updates: VesselUpdate,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> Vessel:
    """Update a vessel in the user's garage."""
    result = await db.execute(
        select(Vessel).where(Vessel.id == vessel_id, Vessel.user_id == user_id)
    )
    vessel = result.scalar_one_or_none()
    if not vessel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vessel not found")

    update_data = updates.model_dump(exclude_unset=True)

    # Handle primary vessel switching
    if update_data.get("is_primary"):
        primary_result = await db.execute(
            select(Vessel).where(Vessel.user_id == user_id, Vessel.is_primary.is_(True))
        )
        for existing_primary in primary_result.scalars().all():
            if existing_primary.id != vessel_id:
                existing_primary.is_primary = False

    for field, value in update_data.items():
        setattr(vessel, field, value)

    await db.flush()
    return vessel


@router.delete("/{vessel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vessel(
    vessel_id: uuid.UUID,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a vessel from the user's garage."""
    result = await db.execute(
        select(Vessel).where(Vessel.id == vessel_id, Vessel.user_id == user_id)
    )
    vessel = result.scalar_one_or_none()
    if not vessel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vessel not found")

    await db.delete(vessel)
    await db.flush()
