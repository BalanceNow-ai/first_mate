"""First Mate chat API.

The assistant is bound to the authenticated user and to a vessel the user owns.
Answers are grounded in admitted knowledge, products carry the central fitment
result, and cart actions are proposals only — the client performs the explicit add
through ``POST /cart/items`` (same server checks as any other add).
"""

import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError, not_found
from app.core.rate_limit import mutation_limit, user_rate_limit
from app.database import get_db, utcnow
from app.middleware.auth import CurrentUser, CurrentUserId
from app.models.ai import AIConversation
from app.models.vessel import Vessel
from app.routers.vessels import get_owned_vessel
from app.schemas.ai import (
    ChatRequest,
    ChatResponse,
    ConversationDetail,
    ConversationSummary,
    SpecialistInfo,
)
from app.services.ai import agent, specialists

router = APIRouter(prefix="/ai", tags=["AI - First Mate"])


async def require_ai() -> None:
    if not agent.ai_available():
        raise AppError(503, "ai_unavailable", "First Mate is not available right now")


@router.get("/specialists", response_model=list[SpecialistInfo])
async def list_specialists() -> list[dict]:
    """The specialist domains the First Mate can consult (public)."""
    return specialists.public_list()


async def _owned_conversation(
    db: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID, *, lock: bool = False
) -> AIConversation:
    stmt = select(AIConversation).where(AIConversation.id == conversation_id, AIConversation.user_id == user_id)
    if lock:
        stmt = stmt.with_for_update()
    conversation = (await db.execute(stmt)).scalar_one_or_none()
    if conversation is None:
        raise not_found("Conversation")
    return conversation


async def _resolve_vessel(
    db: AsyncSession, user_id: uuid.UUID, body: ChatRequest, conversation: AIConversation | None
) -> Vessel | None:
    if body.vessel_id is not None:
        return await get_owned_vessel(db, body.vessel_id, user_id)
    if conversation is not None:
        if conversation.vessel_id is None:
            return None
        # Re-check ownership every turn; a deleted/transferred vessel gives no context.
        return (
            await db.execute(select(Vessel).where(Vessel.id == conversation.vessel_id, Vessel.user_id == user_id))
        ).scalar_one_or_none()
    return (
        await db.execute(
            select(Vessel)
            .where(Vessel.user_id == user_id, Vessel.is_primary.is_(True))
            .order_by(Vessel.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()


@router.post(
    "/chat",
    response_model=ChatResponse,
    dependencies=[
        Depends(require_ai),
        Depends(user_rate_limit("ai_chat_minute", lambda: get_settings().rate_limit_ai_per_minute, 60)),
        Depends(user_rate_limit("ai_chat_day", lambda: get_settings().rate_limit_ai_per_day, 86_400)),
    ],
)
async def chat(
    body: ChatRequest, user: CurrentUser, db: AsyncSession = Depends(get_db, scope="function")
) -> ChatResponse:
    """Ask the First Mate. Uses ``vessel_id`` (must be owned), else the conversation's
    vessel (re-checked), else the primary vessel."""
    settings = get_settings()
    message = body.message.strip()
    if not message:
        raise AppError(422, "empty_message", "Message must not be empty")
    if len(message) > settings.ai_max_message_chars:
        raise AppError(
            422,
            "message_too_long",
            f"Message is limited to {settings.ai_max_message_chars} characters",
        )
    conversation = await _owned_conversation(db, body.conversation_id, user.id) if body.conversation_id else None
    existing = list(conversation.messages or []) if conversation else []
    if len(existing) + 2 > settings.ai_max_conversation_messages:
        raise AppError(409, "conversation_full", "This conversation is full. Please start a new conversation.")
    vessel = await _resolve_vessel(db, user.id, body, conversation)
    history = [
        {"role": m.get("role"), "content": m.get("content", "")}
        for m in existing[-settings.ai_history_messages :]
        if settings.ai_history_messages > 0
    ]

    result = await agent.run_turn(db, user.id, vessel, message, history)

    now = utcnow()
    response = ChatResponse(
        conversation_id=conversation.id if conversation else uuid.uuid4(),
        message={"role": "assistant", "content": result.content, "created_at": now},
        grounding=result.grounding,
        citations=result.citations,
        products=result.products,
        actions=result.actions,
        vessel=result.vessel,
        mode=result.mode,
    )
    stored_user = {"role": "user", "content": message, "created_at": now.isoformat()}
    stored_assistant = {
        "role": "assistant",
        "content": result.content,
        "created_at": now.isoformat(),
        **response.model_dump(mode="json", include={"grounding", "citations", "products", "actions", "vessel", "mode"}),
    }
    # Save in a short transaction: re-lock, re-check ownership and size against the
    # latest stored messages, and re-check the vessel (it may have been deleted meanwhile).
    if (
        vessel is not None
        and (await db.execute(select(Vessel.id).where(Vessel.id == vessel.id, Vessel.user_id == user.id))).first()
        is None
    ):
        vessel = None
    if conversation is not None:
        conversation = await _owned_conversation(db, conversation.id, user.id, lock=True)
        existing = list(conversation.messages or [])
        if len(existing) + 2 > settings.ai_max_conversation_messages:
            raise AppError(409, "conversation_full", "This conversation is full. Please start a new conversation.")
    if conversation is None:
        conversation = AIConversation(
            id=response.conversation_id,
            user_id=user.id,
            vessel_id=vessel.id if vessel else None,
            title=message[:80],
            messages=[stored_user, stored_assistant],
        )
        db.add(conversation)
    else:
        conversation.messages = [*existing, stored_user, stored_assistant]
        conversation.vessel_id = vessel.id if vessel else None
        conversation.updated_at = now
    await db.flush()
    return response


def _summary(c: AIConversation) -> dict:
    return {
        "id": c.id,
        "title": c.title,
        "vessel_id": c.vessel_id,
        "message_count": len(c.messages or []),
        "created_at": c.created_at,
        "updated_at": c.updated_at,
    }


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> list[dict]:
    """The current user's conversations (most recent first)."""
    rows = (
        await db.execute(
            select(AIConversation)
            .where(AIConversation.user_id == user_id)
            .order_by(AIConversation.updated_at.desc())
            .limit(100)
        )
    ).scalars()
    return [_summary(c) for c in rows]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> dict:
    """One of the current user's conversations with its stored messages."""
    c = await _owned_conversation(db, conversation_id, user_id)
    return {**_summary(c), "messages": list(c.messages or [])}


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(mutation_limit())],
)
async def delete_conversation(
    conversation_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> Response:
    c = await _owned_conversation(db, conversation_id, user_id)
    await db.delete(c)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
