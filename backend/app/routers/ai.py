"""First Mate AI chat router."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.middleware.auth import CurrentUserId
from app.models.ai import AIConversation
from app.models.vessel import Vessel
from app.schemas.ai import ChatMessage, ChatRequest, ChatResponse, ConversationResponse

router = APIRouter(prefix="/ai", tags=["AI - First Mate"])
settings = get_settings()


async def _get_vessel_context(vessel_id: uuid.UUID, db: AsyncSession) -> str:
    """Build a vessel context string for the AI agent."""
    result = await db.execute(select(Vessel).where(Vessel.id == vessel_id))
    vessel = result.scalar_one_or_none()
    if not vessel:
        return ""

    context_parts = [
        f"Vessel: {vessel.nickname}",
        f"Make: {vessel.make}",
        f"Model: {vessel.model}",
        f"Year: {vessel.year}",
    ]
    if vessel.hull_type:
        context_parts.append(f"Hull Type: {vessel.hull_type}")
    if vessel.engine_make:
        context_parts.append(f"Engine: {vessel.engine_make} {vessel.engine_model or ''}")
    if vessel.engine_hours:
        context_parts.append(f"Engine Hours: {vessel.engine_hours}")

    return "\n".join(context_parts)


FIRST_MATE_SYSTEM_PROMPT = """You are the First Mate, an expert AI assistant for the Helm marine
platform in New Zealand. You help boat owners with technical questions, product
recommendations, maintenance advice, and voyage planning.

You have access to tools to search for products in the Helm catalogue, look up
vessel data, and query the marine knowledge base. Use these tools to provide
accurate, specific answers rather than guessing.

Always be helpful, specific, and safety-conscious. When recommending products,
mention specific part numbers and prices when available. For safety-critical
topics, always recommend consulting a qualified marine professional.

Respond in a conversational, friendly tone appropriate for New Zealand boaters.
Use NZD for all prices."""


def _build_agent_tools(db_session) -> list:
    """Build LangChain tools the First Mate agent can call."""
    from langchain_core.tools import tool

    @tool
    async def product_search(query: str) -> str:
        """Search the Helm Marine product catalogue by keyword. Returns matching products with names, prices, and SKUs."""
        from app.models.product import Product
        from sqlalchemy import or_

        search_filter = f"%{query}%"
        result = await db_session.execute(
            select(Product)
            .where(
                Product.is_active.is_(True),
                or_(
                    Product.name.ilike(search_filter),
                    Product.description.ilike(search_filter),
                    Product.brand.ilike(search_filter),
                    Product.sku.ilike(search_filter),
                ),
            )
            .limit(5)
        )
        products = result.scalars().all()
        if not products:
            return "No products found matching that query."

        lines = []
        for p in products:
            price_str = f"${p.price:.2f}"
            if p.sale_price:
                price_str = f"~~${p.price:.2f}~~ ${p.sale_price:.2f} (SALE)"
            stock = "In Stock" if p.stock_quantity > 0 else "Out of Stock"
            lines.append(
                f"- {p.name} ({p.brand or 'Unbranded'}) | SKU: {p.sku} | "
                f"{price_str} | {stock}"
            )
        return "\n".join(lines)

    @tool
    async def vessel_data(vessel_make: str, vessel_model: str) -> str:
        """Look up vessel specifications and compatible products for a given make and model."""
        from app.models.product import Product, ProductCompatibility

        result = await db_session.execute(
            select(Product)
            .join(ProductCompatibility)
            .where(
                Product.is_active.is_(True),
                ProductCompatibility.vessel_make == vessel_make,
                ProductCompatibility.vessel_model == vessel_model,
            )
            .limit(10)
        )
        products = result.scalars().all()
        if not products:
            return f"No specific compatible products found for {vessel_make} {vessel_model}."

        lines = [f"Compatible products for {vessel_make} {vessel_model}:"]
        for p in products:
            lines.append(f"- {p.name} (SKU: {p.sku}) — ${p.price:.2f}")
        return "\n".join(lines)

    @tool
    async def marine_knowledge_search(question: str) -> str:
        """Search the marine knowledge base (RAG) for technical information about boat maintenance, safety, and regulations."""
        # In production, this would query pgvector for semantic search.
        # For now, return a helpful response explaining the capability.
        from app.models.ai import RAGDocument

        try:
            result = await db_session.execute(
                select(RAGDocument)
                .where(RAGDocument.content.ilike(f"%{question}%"))
                .limit(3)
            )
            docs = result.scalars().all()
            if docs:
                return "\n\n".join(
                    f"[{d.title}]: {d.content[:500]}" for d in docs
                )
        except Exception:
            pass
        return (
            "No specific knowledge base articles found. "
            "I'll answer based on my general marine expertise."
        )

    return [product_search, vessel_data, marine_knowledge_search]


async def _run_first_mate_agent(
    message: str,
    vessel_context: str,
    conversation_history: list[dict],
    db_session=None,
) -> str:
    """Run the First Mate AI agent with LangChain.

    Uses a ReAct-style agent executor with domain-specialist tools
    for product search, vessel data lookup, and RAG knowledge base.
    Falls back to a dev stub if OpenAI is not configured.
    """
    system_prompt = FIRST_MATE_SYSTEM_PROMPT
    if vessel_context:
        system_prompt += f"\n\nUser's Active Vessel:\n{vessel_context}"

    if not settings.openai_api_key:
        # Development fallback
        return (
            f"I'm the First Mate, your AI marine assistant. I received your message: "
            f'"{message}". In production, I would use my full knowledge base and '
            f"domain-specialist agents to provide a detailed, vessel-specific response. "
            f"Please configure the OpenAI API key to enable full AI capabilities."
        )

    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
        from langchain.agents import create_tool_calling_agent, AgentExecutor
        from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

        llm = ChatOpenAI(
            model="gpt-4.1-mini",
            api_key=settings.openai_api_key,
            temperature=0.7,
            max_tokens=1024,
        )

        tools = _build_agent_tools(db_session) if db_session else []

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])

        # Build chat history from conversation
        chat_history = []
        for msg in conversation_history[-10:]:
            if msg["role"] == "user":
                chat_history.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                chat_history.append(AIMessage(content=msg["content"]))

        agent = create_tool_calling_agent(llm, tools, prompt)
        executor = AgentExecutor(
            agent=agent,
            tools=tools,
            verbose=False,
            max_iterations=5,
            handle_parsing_errors=True,
        )

        result = await executor.ainvoke({
            "input": message,
            "chat_history": chat_history,
        })

        return result.get("output", "I couldn't generate a response.")

    except ImportError:
        # LangChain not installed — fall back to direct OpenAI
        try:
            from openai import AsyncOpenAI

            messages = [{"role": "system", "content": system_prompt}]
            for msg in conversation_history[-10:]:
                messages.append({"role": msg["role"], "content": msg["content"]})
            messages.append({"role": "user", "content": message})

            client = AsyncOpenAI(api_key=settings.openai_api_key)
            response = await client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=messages,
                max_tokens=1024,
                temperature=0.7,
            )
            return response.choices[0].message.content or "I couldn't generate a response."
        except Exception as e:
            return f"I'm having trouble connecting to my AI backend: {e}"
    except Exception as e:
        return f"I'm having trouble connecting to my AI backend: {e}"


@router.post("/chat", response_model=ChatResponse)
async def chat_with_first_mate(
    request: ChatRequest,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """Send a message to the First Mate AI agent.

    The agent uses the user's vessel context and conversation history
    to provide specific, personalised advice. It can route to domain
    specialist agents for technical questions.
    """
    # Get or create conversation
    conversation = None
    if request.conversation_id:
        result = await db.execute(
            select(AIConversation).where(
                AIConversation.id == request.conversation_id,
                AIConversation.user_id == user_id,
            )
        )
        conversation = result.scalar_one_or_none()

    if not conversation:
        # Determine vessel context
        vessel_id = request.vessel_id
        if not vessel_id:
            # Try to get the user's primary vessel
            vessel_result = await db.execute(
                select(Vessel).where(
                    Vessel.user_id == user_id, Vessel.is_primary.is_(True)
                )
            )
            primary = vessel_result.scalar_one_or_none()
            if primary:
                vessel_id = primary.id

        conversation = AIConversation(
            user_id=user_id,
            vessel_id=vessel_id,
            messages=[],
        )
        db.add(conversation)
        await db.flush()

    # Get vessel context
    vessel_context = ""
    if conversation.vessel_id:
        vessel_context = await _get_vessel_context(conversation.vessel_id, db)

    # Add user message to history
    history = list(conversation.messages) if conversation.messages else []
    history.append({"role": "user", "content": request.message})

    # Run the AI agent with DB session for tool access
    response_text = await _run_first_mate_agent(
        message=request.message,
        vessel_context=vessel_context,
        conversation_history=history,
        db_session=db,
    )

    # Add assistant response to history
    history.append({"role": "assistant", "content": response_text})
    conversation.messages = history
    await db.flush()

    return ChatResponse(
        conversation_id=conversation.id,
        message=ChatMessage(role="assistant", content=response_text),
    )


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    user_id: CurrentUserId,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> list[AIConversation]:
    """List the user's AI conversation history."""
    result = await db.execute(
        select(AIConversation)
        .where(AIConversation.user_id == user_id)
        .order_by(AIConversation.updated_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all())


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: uuid.UUID,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> AIConversation:
    """Get a specific conversation by ID."""
    result = await db.execute(
        select(AIConversation).where(
            AIConversation.id == conversation_id,
            AIConversation.user_id == user_id,
        )
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    return conversation


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a conversation."""
    result = await db.execute(
        select(AIConversation).where(
            AIConversation.id == conversation_id,
            AIConversation.user_id == user_id,
        )
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    await db.delete(conversation)
    await db.flush()
