"""One First Mate turn: route → provider (bounded tools) → grounding guard."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.vessel import Vessel
from app.services import fitment as fitment_service
from app.services.ai.grounding import apply_guard
from app.services.ai.providers import TurnInput, get_llm_provider
from app.services.ai.specialists import SPECIALISTS, route
from app.services.ai.tools import TurnRuntime


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
        history=history[-settings.ai_history_messages :]
        if settings.ai_history_messages > 0
        else [],
        routed_domains=routed,
        vessel_label=profile.label if profile else None,
    )
    draft = await provider.answer(turn, runtime)
    guarded = apply_guard(draft.content, runtime, profile, settings.ai_max_products)

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
        },
        citations=guarded.citations,
        products=guarded.products,
        actions=guarded.actions,
        vessel={"id": str(vessel.id), "label": profile.label}
        if vessel is not None and profile
        else None,
        mode=provider.mode,
        runtime=runtime,
    )
