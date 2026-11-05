"""Central fitment evaluation — the single source of "does this part fit this vessel?".

Used by catalogue filters, product detail checks, search, First Mate tools and
checklist linking. Three outcomes (plus ``universal``):

* ``verified_fit``      — a *verified* rule with sufficient confidence matches every
                          specified dimension of the vessel's known facts.
* ``verified_mismatch`` — verified rules exist and the vessel's known facts contradict
                          all of them.
* ``unknown``           — anything else: no verified data, vessel facts missing (e.g. no
                          engine model, no engine year where the rule needs one),
                          low-confidence OEM data, or only unverified rules.

``unknown`` is never presented or treated as a fit.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import and_, exists, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models.boat_db import EquipmentCategory
from app.models.product import Product, ProductCompatibility
from app.models.vessel import Vessel, VesselEquipment
from app.schemas.product import FitmentResult

ENGINE_CATEGORY = "engine"


def norm(value: str | None) -> str:
    """Normalise make/model strings: case-, space-, hyphen- and dot-insensitive."""
    return re.sub(r"[\s\-_.\/]+", "", value or "").upper()


@dataclass(frozen=True)
class EquipmentFact:
    category: str
    make: str
    model: str | None
    year: int | None
    confidence: Decimal
    provenance: str  # vessel_record | owner_declared | oem_database | staff_verified
    equipment_id: uuid.UUID | None = None


@dataclass
class VesselProfile:
    vessel_id: uuid.UUID
    nickname: str
    make: str
    model: str
    year: int
    facts: list[EquipmentFact] = field(default_factory=list)
    # Equipment known to be installed but whose data is too uncertain to match on.
    uncertain_categories: set[str] = field(default_factory=set)

    @property
    def label(self) -> str:
        return f"{self.nickname} ({self.year} {self.make} {self.model})"

    def facts_for(self, category: str) -> list[EquipmentFact]:
        return [f for f in self.facts if f.category == category]

    @property
    def engines(self) -> list[EquipmentFact]:
        return self.facts_for(ENGINE_CATEGORY)

    def fingerprint(self) -> str:
        """Stable string describing the facts that drive fitment (for caching/tests)."""
        parts = [norm(self.make), norm(self.model), str(self.year)]
        parts += sorted(f"{f.category}:{norm(f.make)}:{norm(f.model)}:{f.year}" for f in self.facts)
        return "|".join(parts)


async def load_vessel_profile(db: AsyncSession, vessel: Vessel) -> VesselProfile:
    """Collect the vessel facts usable for fitment.

    The primary engine on the vessel record and owner-declared equipment are the
    owner's statements about their own boat and are used as facts. OEM-database
    equipment is only used when its confidence meets the configured threshold;
    otherwise the category is marked uncertain (and fitment for it is ``unknown``).
    Removed or rejected equipment is ignored.
    """
    threshold = Decimal(str(get_settings().fitment_min_confidence))
    profile = VesselProfile(
        vessel_id=vessel.id, nickname=vessel.nickname, make=vessel.make, model=vessel.model, year=vessel.year
    )
    if vessel.engine_make:
        profile.facts.append(
            EquipmentFact(
                category=ENGINE_CATEGORY,
                make=vessel.engine_make,
                model=vessel.engine_model,
                year=vessel.engine_year,
                confidence=Decimal("1.0"),
                provenance="vessel_record",
            )
        )
    rows = (
        await db.execute(
            select(VesselEquipment)
            .where(
                VesselEquipment.vessel_id == vessel.id,
                VesselEquipment.removed_at.is_(None),
                VesselEquipment.verification_status != "rejected",
            )
            .options(selectinload(VesselEquipment.category))
        )
    ).scalars()
    for eq in rows:
        slug = eq.category.slug
        usable = eq.provenance in ("owner_declared", "staff_verified") or (
            eq.verification_status == "verified" or eq.confidence_score >= threshold
        )
        if not usable:
            profile.uncertain_categories.add(slug)
            continue
        fact = EquipmentFact(
            category=slug,
            make=eq.make,
            model=eq.model,
            year=eq.year,
            confidence=eq.confidence_score,
            provenance=eq.provenance,
            equipment_id=eq.id,
        )
        # Do not duplicate the vessel-record engine.
        if slug == ENGINE_CATEGORY and any(
            f.provenance == "vessel_record" and norm(f.make) == norm(fact.make) and norm(f.model) == norm(fact.model)
            for f in profile.facts
        ):
            continue
        profile.facts.append(fact)
    return profile


_EQUIPMENT_OUTCOME_TEXT = {"match": "matches", "mismatch": "does not match", "unknown": "details needed"}


def _range_outcome(lo: int | None, hi: int | None, value: int | None) -> str:
    if lo is None and hi is None:
        return "match"
    if value is None:
        return "unknown"
    if lo is not None and value < lo:
        return "mismatch"
    if hi is not None and value > hi:
        return "mismatch"
    return "match"


def _fact_outcome(
    rule_make: str | None, rule_model: str | None, lo: int | None, hi: int | None, fact: EquipmentFact
) -> str:
    if rule_make and norm(rule_make) != norm(fact.make):
        return "mismatch"
    if rule_model:
        if not fact.model:
            return "unknown"
        if norm(rule_model) != norm(fact.model):
            return "mismatch"
    return _range_outcome(lo, hi, fact.year)


def _combine_facts(outcomes: list[str]) -> str:
    if "match" in outcomes:
        return "match"
    if "unknown" in outcomes:
        return "unknown"
    return "mismatch"


def _rule_outcome(rule: ProductCompatibility, profile: VesselProfile, category_slugs: dict) -> tuple[str, str]:
    """Return (outcome, reason) for one rule against the profile."""
    dims: list[tuple[str, str]] = []
    if rule.vessel_make:
        if norm(rule.vessel_make) != norm(profile.make):
            dims.append(("mismatch", f"made for {rule.vessel_make} vessels"))
        elif rule.vessel_model and norm(rule.vessel_model) != norm(profile.model):
            dims.append(("mismatch", f"made for the {rule.vessel_make} {rule.vessel_model}"))
        else:
            o = _range_outcome(rule.year_from, rule.year_to, profile.year)
            dims.append((o, "vessel model year outside the verified range" if o == "mismatch" else "vessel matches"))
    if rule.engine_make:
        engines = profile.engines
        if not engines:
            dims.append(("unknown", "no engine recorded for this vessel"))
        else:
            o = _combine_facts(
                [
                    _fact_outcome(rule.engine_make, rule.engine_model, rule.engine_year_from, rule.engine_year_to, e)
                    for e in engines
                ]
            )
            reason = {
                "match": "engine matches verified fitment",
                "mismatch": f"verified for {rule.engine_make} {rule.engine_model or ''}".strip() + " engines",
                "unknown": "engine model or year needed to confirm fit",
            }[o]
            dims.append((o, reason))
    if rule.equipment_category_id:
        slug = category_slugs.get(rule.equipment_category_id, "equipment")
        facts = profile.facts_for(slug)
        if not facts:
            why = (
                "installed equipment data is unverified"
                if slug in profile.uncertain_categories
                else (f"no {slug.replace('_', ' ')} recorded for this vessel")
            )
            dims.append(("unknown", why))
        else:
            o = _combine_facts([_fact_outcome(rule.equipment_make, rule.equipment_model, None, None, f) for f in facts])
            dims.append(
                (
                    o,
                    f"{slug.replace('_', ' ')} {_EQUIPMENT_OUTCOME_TEXT[o]}",
                )
            )
    outcomes = [d[0] for d in dims]
    if "mismatch" in outcomes:
        return "mismatch", next(r for o, r in dims if o == "mismatch")
    if "unknown" in outcomes:
        return "unknown", next(r for o, r in dims if o == "unknown")
    return "match", "; ".join(r for _, r in dims)


def evaluate(
    product: Product,
    rules: list[ProductCompatibility],
    profile: VesselProfile,
    category_slugs: dict[uuid.UUID, str] | None = None,
) -> FitmentResult:
    """Pure evaluation of one product against one vessel profile."""
    threshold = Decimal(str(get_settings().fitment_min_confidence))
    category_slugs = category_slugs or {}
    if product.fitment_scope == "universal":
        return FitmentResult(
            status="universal",
            vessel_id=profile.vessel_id,
            message=f"Suitable for any vessel, including {profile.label}",
            reasons=["product is verified as universal"],
        )
    usable = [r for r in rules if r.verification_status == "verified" and Decimal(str(r.confidence_score)) >= threshold]
    unverified = [r for r in rules if r not in usable and r.verification_status != "rejected"]
    if not usable:
        reasons = ["no verified fitment data for this product"]
        if unverified:
            reasons.append("unverified fitment data exists and is awaiting review")
        return FitmentResult(
            status="unknown",
            vessel_id=profile.vessel_id,
            message=f"Fit for {profile.label} is unknown — no verified fitment data",
            reasons=reasons,
        )
    results = [(r, *_rule_outcome(r, profile, category_slugs)) for r in usable]
    matches = [r for r, o, _ in results if o == "match"]
    if matches:
        return FitmentResult(
            status="verified_fit",
            vessel_id=profile.vessel_id,
            message=f"Fits {profile.label}",
            reasons=[reason for r, o, reason in results if o == "match"][:3],
            matched_rule_ids=[r.id for r in matches],
        )
    unknowns = [(r, reason) for r, o, reason in results if o == "unknown"]
    if unknowns:
        return FitmentResult(
            status="unknown",
            vessel_id=profile.vessel_id,
            message=f"Fit for {profile.label} is unknown — {unknowns[0][1]}",
            reasons=[reason for _, reason in unknowns][:3],
        )
    return FitmentResult(
        status="verified_mismatch",
        vessel_id=profile.vessel_id,
        message=f"Does not fit {profile.label}",
        reasons=[reason for _, _, reason in results][:3],
    )


async def _category_slugs(db: AsyncSession) -> dict[uuid.UUID, str]:
    return {c.id: c.slug for c in (await db.execute(select(EquipmentCategory))).scalars()}


async def evaluate_products(
    db: AsyncSession, products: list[Product], profile: VesselProfile
) -> dict[uuid.UUID, FitmentResult]:
    """Evaluate many products for one vessel with a single rules query."""
    if not products:
        return {}
    ids = [p.id for p in products]
    rules_by_product: dict[uuid.UUID, list[ProductCompatibility]] = defaultdict(list)
    for rule in (
        await db.execute(select(ProductCompatibility).where(ProductCompatibility.product_id.in_(ids)))
    ).scalars():
        rules_by_product[rule.product_id].append(rule)
    slugs = await _category_slugs(db)
    return {p.id: evaluate(p, rules_by_product[p.id], profile, slugs) for p in products}


async def evaluate_product(db: AsyncSession, product: Product, profile: VesselProfile) -> FitmentResult:
    return (await evaluate_products(db, [product], profile))[product.id]


def candidate_clause(profile: VesselProfile):
    """SQL pre-filter: products that *could* be ``verified_fit``/``universal``.

    It narrows by make only; callers must still run :func:`evaluate_products` and keep
    only ``verified_fit``/``universal`` results.
    """
    threshold = get_settings().fitment_min_confidence
    engine_makes = sorted({norm(e.make) for e in profile.engines})
    fact_makes = sorted({norm(f.make) for f in profile.facts})

    def n(col):
        return func.upper(func.regexp_replace(col, r"[\s\-_./]+", "", "g"))

    rule_match = or_(
        n(ProductCompatibility.vessel_make) == norm(profile.make),
        n(ProductCompatibility.engine_make).in_(engine_makes) if engine_makes else false(),
        and_(
            ProductCompatibility.equipment_category_id.isnot(None),
            or_(ProductCompatibility.equipment_make.is_(None), n(ProductCompatibility.equipment_make).in_(fact_makes))
            if fact_makes
            else ProductCompatibility.equipment_make.is_(None),
        ),
    )
    return or_(
        Product.fitment_scope == "universal",
        exists().where(
            ProductCompatibility.product_id == Product.id,
            ProductCompatibility.verification_status == "verified",
            ProductCompatibility.confidence_score >= threshold,
            rule_match,
        ),
    )


POSITIVE_STATUSES = frozenset({"verified_fit", "universal"})
