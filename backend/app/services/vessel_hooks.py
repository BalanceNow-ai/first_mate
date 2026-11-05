"""Extension point called whenever a vessel is created or edited.

The vessel-intelligence workstream implements HIN decoding / model-year linking here.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vessel import Vessel


async def before_save(db: AsyncSession, vessel: Vessel, changed: set[str]) -> None:  # noqa: ARG001
    """Normalise and enrich a vessel before it is flushed."""
    return None
