"""Extension point called whenever a vessel is created or edited.

* HIN: normalised, decoded, ``hin_status`` stored (valid | invalid | unrecognised) and
  the decode stored in ``hin_decoded`` as a *suggestion only* — owner-entered make,
  model and year are never overwritten.
* Boat DB link: ``model_year_id`` is set when the owner's make/model/year exactly
  (normalised) match one boat-DB model year, and cleared when they no longer do.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vessel import Vessel
from app.services import boat_db, hin

_IDENTITY_FIELDS = {"make", "model", "year"}


async def before_save(db: AsyncSession, vessel: Vessel, changed: set[str]) -> None:
    """Normalise and enrich a vessel before it is flushed."""
    if "hin" in changed:
        await _apply_hin(db, vessel)
    if changed & _IDENTITY_FIELDS or vessel.id is None or vessel.model_year_id is None:
        await _link_model_year(db, vessel)


async def _apply_hin(db: AsyncSession, vessel: Vessel) -> None:
    raw = (vessel.hin or "").strip()
    if not raw:
        vessel.hin = None
        vessel.hin_status = None
        vessel.hin_decoded = None
        return
    decoded = await hin.decode(db, raw)
    if decoded.normalized:
        vessel.hin = decoded.normalized
    vessel.hin_status = decoded.status
    suggestion = decoded.as_dict()
    suggestion["note"] = "Suggestion decoded from the HIN; it does not change the details you entered."
    vessel.hin_decoded = suggestion


async def _link_model_year(db: AsyncSession, vessel: Vessel) -> None:
    if not (vessel.make and vessel.model and vessel.year):
        vessel.model_year_id = None
        return
    match = await boat_db.match_model_year(db, vessel.make, vessel.model, vessel.year)
    vessel.model_year_id = match.id if match else None
