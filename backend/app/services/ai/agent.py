"""One First Mate turn: route → provider (bounded tools) → grounding guard."""

from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.ai import KnowledgeSource
from app.models.product import Product
from app.models.vessel import Vessel
from app.services import fitment as fitment_service
from app.services.ai.grounding import apply_guard
from app.services.ai.providers import TurnInput, get_llm_provider
from app.services.ai.specialists import SPECIALISTS, route
from app.services.ai.tools import TurnRuntime
from app.services.rag.retrieval import applicability


@dataclass
class TurnResult:
    content: str
    grounding: dict
    citations: list[dict]
    products: list[dict]
    actions: list[dict]
    vessel: dict | None
    mode: str
    runtime: TurnRuntime


async def revalidate(db: AsyncSession, runtime: TurnRuntime, vessel: Vessel | None) -> None:
    """Answer-time revalidation (the model call can take many seconds).

    Passages whose source was revoked while the model was answering are withdrawn, and
    product fitment, stock and cart proposals are recomputed from the vessel and
    catalogue as they are now — the guard only sees current evidence."""
    if runtime.retrieved:
        source_ids = {c.source_id for c in runtime.retrieved.values()}
        admitted = set(
            (
                await db.execute(
                    select(KnowledgeSource.id).where(
                        KnowledgeSource.id.in_(source_ids), KnowledgeSource.admission_status == "admitted"
                    )
                )
            ).scalars()
        )
        for ref in [r for r, c in runtime.retrieved.items() if c.source_id not in admitted]:
            del runtime.retrieved[ref]
    if vessel is not None:
        current = (
            await db.execute(select(Vessel).where(Vessel.id == vessel.id).execution_options(populate_existing=True))
        ).scalar_one_or_none()
        runtime.profile = await fitment_service.load_vessel_profile(db, current) if current is not None else None
        # Passages are re-scoped against the vessel as it is now.
        for ref, chunk in list(runtime.retrieved.items()):
            fit = applicability(chunk.applies_to, runtime.profile)
            if fit is None:
                del runtime.retrieved[ref]
            else:
                runtime.retrieved[ref] = dataclasses.replace(chunk, applicability=fit)
    if runtime.products:
        fresh_products = {
            p.id: p
            for p in (
                await db.execute(
                    select(Product)
                    .where(Product.id.in_(list(runtime.products)))
                    .execution_options(populate_existing=True)
                )
            ).scalars()
        }
        for pid in [pid for pid in runtime.products if pid not in fresh_products]:
            del runtime.products[pid]
        fitments = await runtime._fitments(list(fresh_products.values()))
        for pid, ref in runtime.products.items():
            ref.product = fresh_products[pid]
            ref.fitment = fitments[pid]
    runtime.proposals = [
        p
        for p in runtime.proposals
        if (ref := runtime.products.get(uuid.UUID(str(p["product_id"])))) is not None
        and ref.positive
        and ref.product.is_active
        and p["quantity"] <= ref.product.stock_quantity
    ]
    if db.in_transaction():
        await db.commit()


def ai_available() -> bool:
    from app.services.ai.providers import llm_available
    from app.services.rag.embeddings import embeddings_available

    settings = get_settings()
    return settings.ai_available and llm_available(settings) and embeddings_available(settings)


async def run_turn(
    db: AsyncSession,
    user_id: uuid.UUID,
    vessel: Vessel | None,
    message: str,
    history: list[dict],
    *,
    provider=None,
) -> TurnResult:
    settings = get_settings()
    provider = provider or get_llm_provider(settings)
    profile = await fitment_service.load_vessel_profile(db, vessel) if vessel is not None else None
    runtime = TurnRuntime(db=db, user_id=user_id, vessel=vessel, profile=profile)
    routed = route(message, settings.ai_max_specialists)
    turn = TurnInput(
        message=message,
        history=history[-settings.ai_history_messages :] if settings.ai_history_messages > 0 else [],
        routed_domains=routed,
        vessel_label=profile.label if profile else None,
    )
    # Release the request's DB connection before any (possibly slow) model call.
    if db.in_transaction():
        await db.commit()
    draft = await provider.answer(turn, runtime)
    await revalidate(db, runtime, vessel)
    guarded = apply_guard(draft.content, runtime, runtime.profile, settings.ai_max_products)

    consulted: list[str] = []
    for domain in [
        *routed,
        *runtime.domains_requested,
        *(runtime.retrieved[r].domain for r in guarded.cited_refs),
    ]:
        if domain in SPECIALISTS and domain not in consulted:
            consulted.append(domain)
    return TurnResult(
        content=guarded.content,
        grounding={
            "status": guarded.status,
            "specialists_consulted": consulted,
            "note": guarded.note,
            "claims": guarded.claims,
            "removed_statements": guarded.removed_statements,
        },
        citations=guarded.citations,
        products=guarded.products,
        actions=guarded.actions,
        vessel=(
            {"id": str(vessel.id), "label": runtime.profile.label} if vessel is not None and runtime.profile else None
        ),
        mode=provider.mode,
        runtime=runtime,
    )
