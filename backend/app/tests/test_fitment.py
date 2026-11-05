"""Central fitment evaluation: verified fit / verified mismatch / unknown."""

from sqlalchemy import update

from app.database import async_session
from app.models.vessel import Vessel
from app.services import fitment
from app.tests.conftest import add_fitment_rule, create_product, create_vessel


async def _eval(product, vessel):
    async with async_session() as db:
        v = await db.get(Vessel, vessel.id)
        profile = await fitment.load_vessel_profile(db, v)
        return await fitment.evaluate_product(db, product, profile)


async def test_verified_engine_rule_fits_and_engine_change_flips(customer):
    vessel = await create_vessel(customer.id, engine_make="Yamaha", engine_model="F150")
    p = await create_product(fitment_scope="specific")
    await add_fitment_rule(p.id, engine_make="Yamaha", engine_model="f-150")
    r = await _eval(p, vessel)
    assert r.status == "verified_fit" and "Fits My Stabi" in r.message
    async with async_session() as db:
        await db.execute(
            update(Vessel).where(Vessel.id == vessel.id).values(engine_make="Suzuki", engine_model="DF140")
        )
        await db.commit()
    assert (await _eval(p, vessel)).status == "verified_mismatch"
    async with async_session() as db:
        await db.execute(update(Vessel).where(Vessel.id == vessel.id).values(engine_make=None, engine_model=None))
        await db.commit()
    assert (await _eval(p, vessel)).status == "unknown"


async def test_unverified_or_low_confidence_rules_are_unknown(customer):
    vessel = await create_vessel(customer.id)
    p = await create_product(fitment_scope="specific")
    await add_fitment_rule(p.id, verification_status="unverified")
    await add_fitment_rule(p.id, confidence_score=0.5)
    r = await _eval(p, vessel)
    assert r.status == "unknown"
    assert any("unverified" in reason for reason in r.reasons)


async def test_missing_vessel_fact_is_unknown_not_fit(customer):
    vessel = await create_vessel(customer.id, engine_model=None, engine_year=None)
    p = await create_product(fitment_scope="specific")
    await add_fitment_rule(p.id, engine_make="Yamaha", engine_model="F150")
    assert (await _eval(p, vessel)).status == "unknown"
    q = await create_product(fitment_scope="specific")
    await add_fitment_rule(q.id, engine_make="Yamaha", engine_model=None, engine_year_from=2018, engine_year_to=2020)
    vessel2 = await create_vessel(customer.id, nickname="B", engine_year=None, is_primary=False)
    assert (await _eval(q, vessel2)).status == "unknown"


async def test_vessel_rule_year_range_and_universal(customer):
    vessel = await create_vessel(customer.id, make="Stabicraft", model="2050 Supercab", year=2022)
    p = await create_product(fitment_scope="specific")
    await add_fitment_rule(
        p.id,
        engine_make=None,
        engine_model=None,
        vessel_make="Stabicraft",
        vessel_model="2050 Supercab",
        year_from=2015,
        year_to=2020,
    )
    assert (await _eval(p, vessel)).status == "verified_mismatch"
    u = await create_product(fitment_scope="universal")
    assert (await _eval(u, vessel)).status == "universal"
    none = await create_product(fitment_scope="unspecified")
    assert (await _eval(none, vessel)).status == "unknown"


async def test_candidate_clause_prefilters_by_make(customer):
    from sqlalchemy import select

    from app.models.product import Product

    vessel = await create_vessel(customer.id, engine_make=None, engine_model=None)
    fit = await create_product(fitment_scope="specific", name="Hull rule product")
    await add_fitment_rule(fit.id, engine_make=None, engine_model=None, vessel_make="Stabicraft")
    other = await create_product(fitment_scope="specific", name="Other make")
    await add_fitment_rule(other.id, engine_make=None, engine_model=None, vessel_make="Rayglass")
    universal = await create_product(fitment_scope="universal", name="Zip ties")
    async with async_session() as db:
        v = await db.get(Vessel, vessel.id)
        profile = await fitment.load_vessel_profile(db, v)
        ids = set((await db.execute(select(Product.id).where(fitment.candidate_clause(profile)))).scalars())
    assert ids == {fit.id, universal.id}
