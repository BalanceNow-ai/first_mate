"""Tests for the First Mate AI chat API."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_chat_with_first_mate(client: AsyncClient, test_user):
    """Test sending a message to the First Mate."""
    response = await client.post(
        "/api/v1/ai/chat",
        json={"message": "What oil does a Yamaha F200 need?"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "conversation_id" in data
    assert data["message"]["role"] == "assistant"
    assert len(data["message"]["content"]) > 0


@pytest.mark.asyncio
async def test_chat_with_vessel_context(client: AsyncClient, test_user, test_vessel):
    """Test that the First Mate uses vessel context."""
    response = await client.post(
        "/api/v1/ai/chat",
        json={
            "message": "When is my next engine service due?",
            "vessel_id": str(test_vessel.id),
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["message"]["role"] == "assistant"


@pytest.mark.asyncio
async def test_list_conversations(client: AsyncClient, test_user):
    """Test listing conversation history."""
    # Create a conversation first
    await client.post(
        "/api/v1/ai/chat",
        json={"message": "Hello, First Mate!"},
    )

    response = await client.get("/api/v1/ai/conversations")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_continue_conversation(client: AsyncClient, test_user):
    """Test continuing an existing conversation."""
    # Start a conversation
    first_response = await client.post(
        "/api/v1/ai/chat",
        json={"message": "Tell me about engine maintenance"},
    )
    conversation_id = first_response.json()["conversation_id"]

    # Continue it
    second_response = await client.post(
        "/api/v1/ai/chat",
        json={
            "message": "What about the oil filter?",
            "conversation_id": conversation_id,
        },
    )
    assert second_response.status_code == 200
    assert second_response.json()["conversation_id"] == conversation_id
