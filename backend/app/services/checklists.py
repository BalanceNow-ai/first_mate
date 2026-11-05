"""Voyage spares checklists (RAG_and_Checklist_Design_Specification §2).

* Three tiers, ``grab_and_go`` ⊂ ``coastal_cruising`` ⊂ ``offshore_passage``. Each item is
  stored once, in the checklist of the tier that introduces it, so its checked state is
  shared by every higher tier that inherits it.
* Items are tailored to the vessel profile: an item that depends on equipment the vessel
  is known *not* to need is omitted; equipment of unknown presence gives
  ``applicability = "if_fitted"``.
* Product links come from *verified* fitment (``verified_fit``/``universal``), never from
  name matching. With no verified candidate the item stays ``unlinked`` and carries a
  catalogue search hint.

These lists are practical spares lists, not a certified safety-equipment or regulatory
compliance assessment.
"""

from __future__ import annotations

import csv
import html
import io
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlencode

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.core.errors import AppError, not_found
from app.database import utcnow
from app.models.checklist import TIERS, ChecklistItem, VoyageChecklist
from app.models.product import Product
from app.models.vessel import Vessel
from app.schemas.checklist import (
    ChecklistItemResponse,
    ChecklistSetResponse,
    SearchHint,
    TierResponse,
)
from app.schemas.product import FitmentResult, VesselRef
from app.services import cart_service, fitment
from app.services.catalogue import product_response
from app.services.pricing import effective_price_cents

TEMPLATE_VERSION = "2026.11-1"
TIER_LEVEL = {t: i for i, t in enumerate(TIERS)}
TIER_NAMES = {
    "grab_and_go": "Grab & Go Kit (day trips)",
    "coastal_cruising": "Coastal Cruising Kit (weekend & multi-day trips)",
    "offshore_passage": "Offshore Passage Kit (blue water & extended voyages)",
}
DISCLAIMER = (
    "This is a practical spares list to help you prepare. It is NOT a certified safety-equipment "
    "list or a regulatory-compliance assessment. Check the safety equipment legally required for "
    "your vessel and trip with Maritime NZ and your local regional council."
)

MOTOR_PROPULSION = {"outboard", "inboard", "sterndrive", "jet"}
PROPELLER_PROPULSION = {"outboard", "inboard", "sterndrive", "electric"}


@dataclass(frozen=True)
class TemplateItem:
    key: str
    tier: str
    system: str
    item_name: str
    quantity: int
    unit: str
    part_role: str | None
    condition: str  # see applicability()


def _t(key, tier, system, name, qty, unit, role, cond="always") -> TemplateItem:
    return TemplateItem(key, tier, system, name, qty, unit, role, cond)


# Spec §2.3 (example for a 6 m trailer boat), with stable template keys.
TEMPLATES: list[TemplateItem] = [
    # ---- Tier 1: Grab & Go
    _t(
        "g_propeller",
        "grab_and_go",
        "Engine",
        "Spare propeller with prop nut and split pin",
        1,
        "each",
        "propeller",
        "propeller_driven",
    ),
    _t(
        "g_fuel_filter",
        "grab_and_go",
        "Engine",
        "Spare engine fuel filter (primary)",
        2,
        "each",
        "fuel_filter",
        "combustion_engine",
    ),
    _t("g_spark_plugs", "grab_and_go", "Engine", "Spare spark plugs", 1, "set", "spark_plug", "petrol_engine"),
    _t(
        "g_kill_switch",
        "grab_and_go",
        "Engine",
        "Spare kill switch lanyard",
        1,
        "each",
        "kill_switch_lanyard",
        "outboard",
    ),
    _t(
        "g_nav_bulbs",
        "grab_and_go",
        "Electrical",
        "Spare navigation light bulbs (if not LED)",
        1,
        "set",
        "nav_light_bulb",
        "if_fitted",
    ),
    _t("g_fuses", "grab_and_go", "Electrical", "Assorted fuses (5A, 10A, 15A)", 1, "pack", "fuse_assortment"),
    _t("g_duct_tape", "grab_and_go", "General", "Duct tape", 1, "roll", "duct_tape"),
    _t("g_zip_ties", "grab_and_go", "General", "Zip ties (assorted sizes)", 1, "pack", "zip_ties"),
    _t(
        "g_hose_clamps",
        "grab_and_go",
        "General",
        "Stainless steel hose clamps (assorted sizes)",
        1,
        "pack",
        "hose_clamp_assortment",
    ),
    _t("g_bungs", "grab_and_go", "General", "Emergency wooden bungs (tapered)", 1, "set", "wooden_bungs"),
    _t(
        "g_tools",
        "grab_and_go",
        "Tools",
        "Shifting spanner, pliers, screwdriver set, prop spanner, spark plug spanner",
        1,
        "kit",
        "basic_toolkit",
    ),
    # ---- Tier 2: Coastal Cruising (adds to Tier 1)
    _t(
        "c_impeller",
        "coastal_cruising",
        "Engine",
        "Spare water pump impeller & gasket",
        1,
        "each",
        "impeller",
        "combustion_engine",
    ),
    _t(
        "c_thermostat",
        "coastal_cruising",
        "Engine",
        "Spare thermostat & gasket",
        1,
        "each",
        "thermostat",
        "combustion_engine",
    ),
    _t(
        "c_belt",
        "coastal_cruising",
        "Engine",
        "Spare alternator / serpentine belt",
        1,
        "each",
        "drive_belt",
        "inboard_engine",
    ),
    _t(
        "c_engine_oil",
        "coastal_cruising",
        "Engine",
        "Engine oil (1 L top-up)",
        1,
        "each",
        "engine_oil",
        "combustion_engine",
    ),
    _t(
        "c_bilge_pump",
        "coastal_cruising",
        "Plumbing",
        "Spare bilge pump (cartridge or complete)",
        1,
        "each",
        "bilge_pump",
        "equipment:bilge_pump",
    ),
    _t(
        "c_toilet_valves",
        "coastal_cruising",
        "Plumbing",
        "Spare toilet duckbill / joker valves",
        1,
        "set",
        "toilet_valve",
        "recorded:toilet",
    ),
    _t(
        "c_battery_terminals", "coastal_cruising", "Electrical", "Spare battery terminals", 1, "set", "battery_terminal"
    ),
    _t(
        "c_wire",
        "coastal_cruising",
        "Electrical",
        "Small spool of marine-grade electrical wire",
        1,
        "each",
        "marine_wire",
    ),
    _t("c_crimp_kit", "coastal_cruising", "Electrical", "Butt connectors & crimper", 1, "kit", "crimp_kit"),
    _t(
        "c_tools",
        "coastal_cruising",
        "Tools",
        "Full socket set, multimeter, strap wrench (for filters)",
        1,
        "kit",
        "coastal_toolkit",
    ),
    # ---- Tier 3: Offshore Passage (adds to Tiers 1 & 2)
    _t(
        "o_fuel_pump",
        "offshore_passage",
        "Engine",
        "Spare fuel pump (lift or high-pressure)",
        1,
        "each",
        "fuel_pump",
        "combustion_engine",
    ),
    _t(
        "o_ignition_coil",
        "offshore_passage",
        "Engine",
        "Spare ignition coil",
        1,
        "each",
        "ignition_coil",
        "petrol_engine",
    ),
    _t("o_gasket_set", "offshore_passage", "Engine", "Full gasket set", 1, "set", "gasket_set", "combustion_engine"),
    _t(
        "o_oil_change",
        "offshore_passage",
        "Engine",
        "Engine oil for a full change",
        1,
        "set",
        "engine_oil",
        "combustion_engine",
    ),
    _t(
        "o_oil_filter",
        "offshore_passage",
        "Engine",
        "Oil filter for a full change",
        1,
        "each",
        "oil_filter",
        "combustion_engine",
    ),
    _t(
        "o_freshwater_pump",
        "offshore_passage",
        "Plumbing",
        "Complete spare freshwater pump",
        1,
        "each",
        "freshwater_pump",
        "equipment:freshwater_pump",
    ),
    _t(
        "o_bilge_rebuild",
        "offshore_passage",
        "Plumbing",
        "Major bilge pump rebuild kit",
        1,
        "kit",
        "bilge_pump_rebuild_kit",
        "equipment:bilge_pump",
    ),
    _t("o_hose_fittings", "offshore_passage", "Plumbing", "Assorted hose & fittings", 1, "kit", "hose_fittings_kit"),
    _t(
        "o_vhf_antenna",
        "offshore_passage",
        "Electrical",
        "Spare VHF antenna",
        1,
        "each",
        "vhf_antenna",
        "equipment:vhf_radio",
    ),
    _t(
        "o_gps_antenna",
        "offshore_passage",
        "Electrical",
        "Spare GPS antenna",
        1,
        "each",
        "gps_antenna",
        "equipment:chartplotter",
    ),
    _t(
        "o_inverter",
        "offshore_passage",
        "Electrical",
        "Spare inverter / charger",
        1,
        "each",
        "inverter_charger",
        "recorded:inverter",
    ),
    _t(
        "o_steering_fluid",
        "offshore_passage",
        "Steering",
        "Spare hydraulic steering fluid & bleed kit",
        1,
        "kit",
        "hydraulic_steering_fluid",
        "recorded:steering_hydraulic",
    ),
    _t(
        "o_sail_repair",
        "offshore_passage",
        "Sails",
        "Sail repair kit (needles, waxed thread, patches)",
        1,
        "kit",
        "sail_repair_kit",
        "sail",
    ),
    _t(
        "o_sail_hardware",
        "offshore_passage",
        "Sails",
        "Spare blocks, shackles and cleats",
        1,
        "assorted",
        "sail_hardware",
        "sail",
    ),
]
TEMPLATE_BY_KEY = {t.key: t for t in TEMPLATES}


@dataclass
class TailorContext:
    propulsion: str | None
    has_engine: bool
    facts: set[str] = field(default_factory=set)
    uncertain: set[str] = field(default_factory=set)

    @classmethod
    def from_profile(cls, vessel: Vessel, profile: fitment.VesselProfile) -> TailorContext:
        return cls(
            propulsion=(vessel.propulsion_type or "").strip().lower() or None,
            has_engine=bool(profile.engines),
            facts={f.category for f in profile.facts},
            uncertain=set(profile.uncertain_categories),
        )


def applicability(condition: str, ctx: TailorContext) -> str | None:
    """``applies``, ``if_fitted`` (presence unknown) or ``None`` (omit for this vessel)."""
    p = ctx.propulsion
    if condition == "always":
        return "applies"
    if condition == "if_fitted":
        return "if_fitted"
    if condition == "combustion_engine":
        if ctx.has_engine or p in MOTOR_PROPULSION:
            return "applies"
        return None if p == "electric" else "if_fitted"
    if condition == "petrol_engine":
        if p == "outboard":
            return "applies"  # outboards here are petrol unless the owner records otherwise
        if p == "electric" and not ctx.has_engine:
            return None
        return "if_fitted"  # inboard/sterndrive/jet/sail auxiliaries may be diesel
    if condition == "outboard":
        if p == "outboard":
            return "applies"
        return "if_fitted" if p is None else None
    if condition == "inboard_engine":
        if p in ("inboard", "sterndrive"):
            return "applies"
        if p == "electric" and not ctx.has_engine:
            return None
        return "if_fitted"
    if condition == "propeller_driven":
        if p in PROPELLER_PROPULSION:
            return "applies"
        return None if p == "jet" else "if_fitted"
    if condition == "sail":
        if p == "sail" or "sail_rig" in ctx.facts:
            return "applies"
        return "if_fitted" if "sail_rig" in ctx.uncertain else None
    kind, _, slug = condition.partition(":")
    if kind == "equipment":  # include; mark if_fitted unless recorded
        return "applies" if slug in ctx.facts else "if_fitted"
    if kind == "recorded":  # only when recorded (uncertain factory data → if_fitted)
        if slug in ctx.facts:
            return "applies"
        return "if_fitted" if slug in ctx.uncertain else None
    raise ValueError(f"Unknown checklist condition {condition!r}")


def tailor(ctx: TailorContext) -> list[tuple[TemplateItem, str]]:
    out = []
    for t in TEMPLATES:
        a = applicability(t.condition, ctx)
        if a is not None:
            out.append((t, a))
    return out


# =========================================================================== persistence
async def load_checklists(db: AsyncSession, vessel_id: uuid.UUID) -> list[VoyageChecklist]:
    rows = list(
        (
            await db.execute(
                select(VoyageChecklist)
                .where(VoyageChecklist.vessel_id == vessel_id)
                .options(selectinload(VoyageChecklist.items))
            )
        ).scalars()
    )
    return sorted(rows, key=lambda c: TIER_LEVEL.get(c.tier, 99))


async def generate(db: AsyncSession, vessel: Vessel, *, regenerate: bool = False) -> list[VoyageChecklist]:
    existing = await load_checklists(db, vessel.id)
    if existing and not regenerate:
        raise AppError(409, "checklists_exist", "Checklists already exist for this vessel; use regenerate=true")
    preserved: dict[str, ChecklistItem] = {i.template_key: i for c in existing for i in c.items if i.template_key}
    snapshot = {k: (i.is_checked, i.checked_at, i.product_id, i.link_status) for k, i in preserved.items()}
    if existing:
        await db.execute(delete(VoyageChecklist).where(VoyageChecklist.vessel_id == vessel.id))
        for c in existing:
            db.expunge(c)  # cascades to its items
    profile = await fitment.load_vessel_profile(db, vessel)
    ctx = TailorContext.from_profile(vessel, profile)
    selected = tailor(ctx)
    checklists: list[VoyageChecklist] = []
    for tier in TIERS:
        checklist = VoyageChecklist(
            vessel_id=vessel.id, tier=tier, name=TIER_NAMES[tier], template_version=TEMPLATE_VERSION
        )
        db.add(checklist)
        await db.flush()
        position = 0
        for t, appl in selected:
            if t.tier != tier:
                continue
            item = ChecklistItem(
                checklist_id=checklist.id,
                template_key=t.key,
                position=position,
                system=t.system,
                item_name=t.item_name,
                description=f"{t.quantity} {t.unit}",
                quantity=t.quantity,
                part_role=t.part_role,
                applicability=appl,
                link_status="unlinked",
            )
            prev = snapshot.get(t.key)
            if prev:
                item.is_checked, item.checked_at = prev[0], prev[1]
                if prev[3] == "user_linked_unverified" and prev[2]:
                    item.product_id, item.link_status = prev[2], "user_linked_unverified"
            db.add(item)
            position += 1
        checklists.append(checklist)
    await db.flush()
    return await load_checklists(db, vessel.id)


# =========================================================================== linking
@dataclass
class LinkInfo:
    product: Product | None
    fitment: FitmentResult | None
    alternatives: list[tuple[Product, FitmentResult]]


def _rank(p: Product) -> tuple:
    in_stock = p.is_active and p.stock_quantity > 0
    return (not in_stock, effective_price_cents(p), p.name, str(p.id))


async def refresh_links(
    db: AsyncSession, profile: fitment.VesselProfile, items: list[ChecklistItem]
) -> dict[uuid.UUID, LinkInfo]:
    """Re-validate every item's product link against current verified fitment."""
    roles = {i.part_role for i in items if i.part_role}
    linked_ids = {i.product_id for i in items if i.product_id}
    products: dict[uuid.UUID, Product] = {}
    if roles:
        for p in (
            await db.execute(select(Product).where(Product.is_active.is_(True), Product.part_role.in_(roles)))
        ).scalars():
            products[p.id] = p
    missing = linked_ids - set(products)
    if missing:
        for p in (await db.execute(select(Product).where(Product.id.in_(missing)))).scalars():
            products[p.id] = p
    results = await fitment.evaluate_products(db, list(products.values()), profile)
    by_role: dict[str, list[Product]] = {}
    for p in products.values():
        if p.is_active and p.part_role in roles and results[p.id].status in fitment.POSITIVE_STATUSES:
            by_role.setdefault(p.part_role, []).append(p)
    for lst in by_role.values():
        lst.sort(key=_rank)

    n_alt = get_settings().checklist_link_alternatives
    info: dict[uuid.UUID, LinkInfo] = {}
    for item in items:
        current = products.get(item.product_id) if item.product_id else None
        res = results.get(current.id) if current is not None else None
        usable = current is not None and current.is_active
        if item.link_status == "user_linked_unverified" and usable and res.status != "verified_mismatch":
            if res.status in fitment.POSITIVE_STATUSES:
                item.link_status = res.status
        elif usable and res.status in fitment.POSITIVE_STATUSES:
            item.link_status = res.status
        else:
            candidates = by_role.get(item.part_role, []) if item.part_role else []
            if candidates:
                current = candidates[0]
                res = results[current.id]
                item.product_id, item.link_status = current.id, res.status
            else:
                current, res = None, None
                item.product_id, item.link_status = None, "unlinked"
        alternatives = (
            [(p, results[p.id]) for p in by_role.get(item.part_role, []) if current is None or p.id != current.id][
                :n_alt
            ]
            if item.part_role
            else []
        )
        info[item.id] = LinkInfo(product=current, fitment=res, alternatives=alternatives)
    await db.flush()
    return info


async def manual_link(
    db: AsyncSession, profile: fitment.VesselProfile, item: ChecklistItem, product_id: uuid.UUID
) -> str | None:
    """Link a product chosen by the owner. Returns a warning for unverified fit."""
    product = await db.get(Product, product_id)
    if product is None or not product.is_active:
        raise AppError(404, "product_unavailable", "This product is not available")
    res = await fitment.evaluate_product(db, product, profile)
    if res.status == "verified_mismatch":
        raise AppError(409, "fitment_mismatch", res.message, extra={"fitment": res.model_dump(mode="json")})
    item.product_id = product.id
    if res.status in fitment.POSITIVE_STATUSES:
        item.link_status = res.status
        warning = None
    else:
        item.link_status = "user_linked_unverified"
        warning = f"Fit for {profile.label} has not been verified — check before buying"
    await db.flush()
    return warning


# =========================================================================== responses
def cumulative_items(checklists: list[VoyageChecklist], tier: str) -> list[tuple[str, ChecklistItem]]:
    level = TIER_LEVEL[tier]
    out = []
    for c in checklists:
        if TIER_LEVEL.get(c.tier, 99) <= level:
            out.extend((c.tier, i) for i in sorted(c.items, key=lambda i: (i.position, str(i.id))))
    return out


def _hint(item: ChecklistItem, vessel_id: uuid.UUID) -> SearchHint:
    prefix = get_settings().api_v1_prefix
    params = {"vessel_id": str(vessel_id)}
    if item.part_role:
        params["part_role"] = item.part_role
    else:
        params["q"] = item.item_name
    return SearchHint(
        q=item.item_name,
        part_role=item.part_role,
        vessel_id=vessel_id,
        path=f"{prefix}/search/products?{urlencode(params)}",
    )


def item_response(
    introduced_in: str,
    item: ChecklistItem,
    link: LinkInfo | None,
    vessel: Vessel,
    profile: fitment.VesselProfile,
    warning: str | None = None,
) -> ChecklistItemResponse:
    product = link.product if link else None
    res = link.fitment if link else None
    if item.link_status == "user_linked_unverified" and warning is None:
        warning = f"Fit for {profile.label} has not been verified — check before buying"
    return ChecklistItemResponse(
        id=item.id,
        template_key=item.template_key,
        introduced_in=introduced_in,
        position=item.position,
        system=item.system,
        item_name=item.item_name,
        description=item.description,
        quantity=item.quantity,
        part_role=item.part_role,
        applicability=item.applicability,
        is_checked=item.is_checked,
        checked_at=item.checked_at,
        link_status=item.link_status,
        product=product_response(product, res) if product else None,
        fitment=res,
        alternatives=[product_response(p, r) for p, r in (link.alternatives if link else [])],
        search_hint=_hint(item, vessel.id) if product is None else None,
        warning=warning,
    )


def tier_response(
    checklists: list[VoyageChecklist],
    tier: str,
    links: dict[uuid.UUID, LinkInfo],
    vessel: Vessel,
    profile: fitment.VesselProfile,
) -> TierResponse:
    own = next(c for c in checklists if c.tier == tier)
    items = [item_response(t, i, links.get(i.id), vessel, profile) for t, i in cumulative_items(checklists, tier)]
    return TierResponse(
        tier=tier,
        name=own.name,
        checklist_id=own.id,
        items=items,
        total=len(items),
        checked=sum(1 for i in items if i.is_checked),
        unchecked_linked=sum(1 for i in items if not i.is_checked and i.product is not None),
    )


async def build_set(db: AsyncSession, vessel: Vessel) -> ChecklistSetResponse:
    profile = await fitment.load_vessel_profile(db, vessel)
    ref = VesselRef(id=vessel.id, label=profile.label)
    checklists = await load_checklists(db, vessel.id)
    if not checklists:
        return ChecklistSetResponse(vessel=ref, generated=False, template_version=None, disclaimer=DISCLAIMER, tiers=[])
    links = await refresh_links(db, profile, [i for c in checklists for i in c.items])
    return ChecklistSetResponse(
        vessel=ref,
        generated=True,
        template_version=checklists[0].template_version,
        disclaimer=DISCLAIMER,
        tiers=[tier_response(checklists, c.tier, links, vessel, profile) for c in checklists],
    )


async def require_checklists(db: AsyncSession, vessel: Vessel) -> list[VoyageChecklist]:
    checklists = await load_checklists(db, vessel.id)
    if not checklists:
        raise AppError(404, "checklists_not_generated", "Generate checklists for this vessel first")
    return checklists


async def owned_item(
    db: AsyncSession, item_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[ChecklistItem, VoyageChecklist, Vessel]:
    row = (
        await db.execute(
            select(ChecklistItem, VoyageChecklist, Vessel)
            .join(VoyageChecklist, ChecklistItem.checklist_id == VoyageChecklist.id)
            .join(Vessel, VoyageChecklist.vessel_id == Vessel.id)
            .where(ChecklistItem.id == item_id, Vessel.user_id == user_id)
            .with_for_update(of=ChecklistItem)
        )
    ).first()
    if row is None:
        raise not_found("Checklist item")
    return row[0], row[1], row[2]


def set_checked(item: ChecklistItem, checked: bool) -> None:
    if item.is_checked != checked:
        item.is_checked = checked
        item.checked_at = utcnow() if checked else None


async def add_missing_to_cart(db: AsyncSession, user_id: uuid.UUID, vessel: Vessel, tier: str):
    """Ensure the cart holds every unchecked, linked item of ``tier`` (idempotent, stock-safe)."""
    checklists = await require_checklists(db, vessel)
    profile = await fitment.load_vessel_profile(db, vessel)
    await refresh_links(db, profile, [i for c in checklists for i in c.items])
    items = [i for _, i in cumulative_items(checklists, tier) if not i.is_checked]
    linked = [i for i in items if i.product_id]
    result = await cart_service.ensure_quantities(db, user_id, [(i.product_id, i.quantity) for i in linked])
    by_product = {line.product_id: line for line in result.lines}
    lines = []
    for i in linked:
        line = by_product[i.product_id]
        lines.append(
            {
                "item_id": i.id,
                "template_key": i.template_key,
                "item_name": i.item_name,
                "product_id": i.product_id,
                "requested": line.requested,
                "added": line.added,
                "quantity_in_cart": line.quantity_in_cart,
                "status": line.status,
                "message": line.message,
            }
        )
    skipped = [{"item_id": i.id, "item_name": i.item_name, "reason": "unlinked"} for i in items if not i.product_id]
    return {"tier": tier, "added_count": result.added_count, "lines": lines, "skipped": skipped}


# =========================================================================== export
def export_rows(checklists: list[VoyageChecklist], tier: str, products: dict[uuid.UUID, Product]) -> list[dict]:
    rows = []
    for introduced, i in cumulative_items(checklists, tier):
        p = products.get(i.product_id) if i.product_id else None
        rows.append(
            {
                "introduced_in": introduced,
                "system": i.system,
                "item": i.item_name,
                "quantity": i.quantity,
                "unit": i.description or "",
                "applicability": i.applicability,
                "checked": i.is_checked,
                "product_sku": p.sku if p else "",
                "product_name": p.name if p else "",
                "link_status": i.link_status,
            }
        )
    return rows


def to_csv(rows: list[dict], vessel_label: str, tier: str) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["# Helm voyage spares checklist", vessel_label, TIER_NAMES[tier]])
    w.writerow(["# " + DISCLAIMER])
    w.writerow(
        [
            "tier_introduced",
            "system",
            "item",
            "quantity",
            "unit",
            "applicability",
            "checked",
            "product_sku",
            "product_name",
            "link_status",
        ]
    )
    for r in rows:
        w.writerow(
            [
                r["introduced_in"],
                r["system"],
                _csv_safe(r["item"]),
                r["quantity"],
                r["unit"],
                r["applicability"],
                "yes" if r["checked"] else "no",
                _csv_safe(r["product_sku"]),
                _csv_safe(r["product_name"]),
                r["link_status"],
            ]
        )
    return buf.getvalue()


def _csv_safe(value: str) -> str:
    """Neutralise spreadsheet formula injection."""
    return "'" + value if value and value[0] in "=+-@\t\r" else value


def to_html(rows: list[dict], vessel: Vessel, vessel_label: str, tier: str) -> str:
    e = html.escape
    body = []
    current = None
    for r in rows:
        if r["system"] != current:
            current = r["system"]
            body.append(f'<tr class="sys"><th colspan="5">{e(current)}</th></tr>')
        note = " <em>(if fitted)</em>" if r["applicability"] == "if_fitted" else ""
        product = f"{e(r['product_name'])} <small>({e(r['product_sku'])})</small>" if r["product_sku"] else "&mdash;"
        box = "&#9745;" if r["checked"] else "&#9744;"
        body.append(
            f'<tr><td class="box">{box}</td><td>{e(r["item"])}{note}</td>'
            f"<td>{e(str(r['quantity']))} {e(r['unit'].split(' ', 1)[-1] if r['unit'] else '')}</td>"
            f"<td>{product}</td><td>{e(TIER_NAMES[r['introduced_in']].split(' (')[0])}</td></tr>"
        )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{e(vessel.nickname)} — {e(TIER_NAMES[tier])}</title>
<style>
body{{font-family:system-ui,sans-serif;margin:24px;color:#111}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #999;padding:6px;text-align:left}}
tr.sys th{{background:#e8eef5}}td.box{{font-size:20px;width:28px;text-align:center}}
.disclaimer{{border:2px solid #b00;padding:10px;margin:12px 0;font-weight:600}}
@media print{{.noprint{{display:none}}}}
</style></head><body>
<h1>{e(TIER_NAMES[tier])}</h1>
<p><strong>Vessel:</strong> {e(vessel_label)}<br><strong>Generated:</strong> {e(utcnow().strftime("%d %b %Y"))}</p>
<p class="disclaimer">{e(DISCLAIMER)}</p>
<table><thead><tr><th></th><th>Item</th><th>Qty</th><th>Suggested product</th><th>From tier</th></tr></thead>
<tbody>
{chr(10).join(body)}
</tbody></table>
</body></html>
"""
