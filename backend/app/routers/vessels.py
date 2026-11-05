"""Vessel (My Vessel Garage) CRUD. Every lookup is scoped to the owner."""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import not_found
from app.core.rate_limit import mutation_limit
from app.database import get_db
from app.middleware.auth import CurrentUserId
from app.models.vessel import Vessel
from app.schemas.vessel import VesselCreate, VesselResponse, VesselUpdate
from app.services import vessel_hooks

router = APIRouter(prefix="/vessels", tags=["Vessels"])


async def get_owned_vessel(db: AsyncSession, vessel_id: uuid.UUID, user_id: uuid.UUID) -> Vessel:
    """Return the vessel if it belongs to ``user_id``; 404 otherwise (no existence leak)."""
    vessel = (
        await db.execute(select(Vessel).where(Vessel.id == vessel_id, Vessel.user_id == user_id))
    ).scalar_one_or_none()
    if vessel is None:
        raise not_found("Vessel")
    return vessel


async def _clear_other_primary(db: AsyncSession, user_id: uuid.UUID, keep: uuid.UUID | None) -> None:
    q = update(Vessel).where(Vessel.user_id == user_id, Vessel.is_primary.is_(True))
    if keep is not None:
        q = q.where(Vessel.id != keep)
    await db.execute(q.values(is_primary=False))


@router.get("/", response_model=list[VesselResponse])
async def list_vessels(user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")) -> list[Vessel]:
    """List the current user's vessels (primary first)."""
    result = await db.execute(
        select(Vessel)
        .where(Vessel.user_id == user_id)
        .order_by(Vessel.is_primary.desc(), Vessel.created_at.desc())
    )
    return list(result.scalars())


@router.post(
    "/", response_model=VesselResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(mutation_limit())],
)
async def create_vessel(
    vessel_data: VesselCreate, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> Vessel:
    """Add a vessel. The first vessel becomes primary automatically."""
    has_any = (await db.execute(select(Vessel.id).where(Vessel.user_id == user_id).limit(1))).first()
    data = vessel_data.model_dump()
    if not has_any:
        data["is_primary"] = True
    if data["is_primary"]:
        await _clear_other_primary(db, user_id, None)
    vessel = Vessel(user_id=user_id, **data)
    await vessel_hooks.before_save(db, vessel, changed=set(data))
    db.add(vessel)
    await db.flush()
    await db.refresh(vessel)
    return vessel


@router.get("/{vessel_id}", response_model=VesselResponse)
async def get_vessel(vessel_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")) -> Vessel:
    """Get one of the current user's vessels."""
    return await get_owned_vessel(db, vessel_id, user_id)


@router.patch("/{vessel_id}", response_model=VesselResponse, dependencies=[Depends(mutation_limit())])
async def update_vessel(
    vessel_id: uuid.UUID, updates: VesselUpdate, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> Vessel:
    """Update a vessel. Setting ``is_primary`` clears it on the owner's other vessels."""
    vessel = await get_owned_vessel(db, vessel_id, user_id)
    data = updates.model_dump(exclude_unset=True)
    for required in ("nickname", "make", "model", "year", "is_primary"):
        if required in data and data[required] is None:
            data.pop(required)
    if data.get("is_primary"):
        await _clear_other_primary(db, user_id, vessel.id)
    for field, value in data.items():
        setattr(vessel, field, value)
    await vessel_hooks.before_save(db, vessel, changed=set(data))
    await db.flush()
    await db.refresh(vessel)
    return vessel


@router.delete("/{vessel_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(mutation_limit())])
async def delete_vessel(vessel_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")) -> None:
    """Remove a vessel (and its equipment, checklists and service history)."""
    vessel = await get_owned_vessel(db, vessel_id, user_id)
    await db.delete(vessel)
    await db.flush()
