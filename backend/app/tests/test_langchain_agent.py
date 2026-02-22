"""Tests for the LangChain-based First Mate AI agent."""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_ai_chat_dev_fallback(client: AsyncClient, db_session: AsyncSession, test_user):
    """Without OpenAI key, should return development fallback message."""
    response = await client.post("/api/v1/ai/chat", json={
        "message": "What oil does my engine need?",
    })
    assert response.status_code == 200
    data = response.json()
    assert "conversation_id" in data
    assert data["message"]["role"] == "assistant"
    # Dev fallback mentions the user's message
    assert "What oil does my engine need?" in data["message"]["content"]


@pytest.mark.asyncio
async def test_ai_chat_with_vessel_context(
    client: AsyncClient, db_session: AsyncSession, test_user, test_vessel
):
    """Chat with a vessel should include vessel context in the response."""
    response = await client.post("/api/v1/ai/chat", json={
        "message": "What maintenance does my boat need?",
        "vessel_id": str(test_vessel.id),
    })
    assert response.status_code == 200
    data = response.json()
    assert data["message"]["role"] == "assistant"
    assert len(data["message"]["content"]) > 0


@pytest.mark.asyncio
async def test_ai_conversation_continuity(client: AsyncClient, db_session: AsyncSession, test_user):
    """Continuing a conversation should use the existing conversation ID."""
    # First message
    response1 = await client.post("/api/v1/ai/chat", json={
        "message": "Tell me about anchors",
    })
    assert response1.status_code == 200
    conv_id = response1.json()["conversation_id"]

    # Second message in same conversation
    response2 = await client.post("/api/v1/ai/chat", json={
        "message": "What size should I get?",
        "conversation_id": conv_id,
    })
    assert response2.status_code == 200
    assert response2.json()["conversation_id"] == conv_id


@pytest.mark.asyncio
async def test_ai_list_conversations(client: AsyncClient, db_session: AsyncSession, test_user):
    """Should list the user's conversations."""
    # Create a conversation
    await client.post("/api/v1/ai/chat", json={
        "message": "Hello First Mate!",
    })

    response = await client.get("/api/v1/ai/conversations")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_ai_delete_conversation(client: AsyncClient, db_session: AsyncSession, test_user):
    """Should be able to delete a conversation."""
    # Create a conversation
    create_response = await client.post("/api/v1/ai/chat", json={
        "message": "Hello",
    })
    conv_id = create_response.json()["conversation_id"]

    # Delete it
    delete_response = await client.delete(f"/api/v1/ai/conversations/{conv_id}")
    assert delete_response.status_code == 204

    # Should be gone
    get_response = await client.get(f"/api/v1/ai/conversations/{conv_id}")
    assert get_response.status_code == 404
