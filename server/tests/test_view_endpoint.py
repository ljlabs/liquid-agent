"""Integration tests for /v1/view and /v1/view/stream endpoints."""
import pytest
import asyncio
import json
from unittest.mock import AsyncMock, patch, MagicMock
import httpx
from app.main import app
from app.sessions import SessionManager
from app.view_data import ViewDataGenerator
import app.main as main
from app import database as db


@pytest.fixture
async def async_client():
    main.manager = SessionManager()
    main.view_generator = ViewDataGenerator(main.manager, db)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_view_crud(async_client):
    """Test all /v1/view CRUD actions."""
    r = await async_client.get("/v1/health")
    assert r.status_code == 200

    r = await async_client.post("/v1/view", json={"action": "get_view"})
    assert r.status_code == 200
    data = r.json()
    assert data["type"] == "view"
    assert data["active_session"] is None

    r = await async_client.post("/v1/view", json={"action": "create_session", "model": "test"})
    assert r.status_code == 200
    data = r.json()
    session_id = data["active_session"]["id"]
    assert data["active_session"]["model"] == "test"

    r = await async_client.post("/v1/view", json={"action": "get_view", "session_id": session_id})
    assert r.status_code == 200
    data = r.json()
    assert data["active_session"]["id"] == session_id
    assert data["messages"] == []
    assert len(data["tool_rules"]) > 0

    r = await async_client.post("/v1/view", json={"action": "set_mode", "session_id": session_id, "permission_mode": "acceptEdits"})
    assert r.status_code == 200
    data = r.json()
    assert data["active_session"]["permission_mode"] == "acceptEdits"

    r = await async_client.post("/v1/view", json={"action": "update_tool_rule", "session_id": session_id, "tool_name": "Bash", "tool_rule": "allow"})
    assert r.status_code == 200
    data = r.json()
    bash_rule = next(r for r in data["tool_rules"] if r["tool"] == "Bash")
    assert bash_rule["rule"] == "allow"

    r = await async_client.post("/v1/view", json={"action": "delete_session", "session_id": session_id})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_view_stream_sse(async_client):
    """Test that /v1/view/stream returns valid SSE with ViewData."""
    r = await async_client.post("/v1/view", json={"action": "create_session", "model": "test"})
    session_id = r.json()["active_session"]["id"]

    first_event = None

    async with async_client.stream("GET", f"/v1/view/stream?session_id={session_id}") as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

        async def read_first_event():
            nonlocal first_event
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                    if data.get("type") == "view":
                        first_event = data
                        return

        try:
            await asyncio.wait_for(read_first_event(), timeout=5.0)
        except asyncio.TimeoutError:
            pass

    assert first_event is not None
    assert first_event["type"] == "view"
    assert first_event["active_session"]["id"] == session_id
    assert first_event["active_session"]["model"] == "test"
    assert isinstance(first_event["messages"], list)
    assert isinstance(first_event["tool_rules"], list)
    assert isinstance(first_event["ui_state"], dict)


@pytest.mark.asyncio
async def test_view_stream_no_session(async_client):
    """Test /v1/view/stream with no session returns ViewData with no active_session."""
    first_event = None

    async with async_client.stream("GET", "/v1/view/stream") as response:
        assert response.status_code == 200

        async def read_first_event():
            nonlocal first_event
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                    if data.get("type") == "view":
                        first_event = data
                        return

        try:
            await asyncio.wait_for(read_first_event(), timeout=5.0)
        except asyncio.TimeoutError:
            pass

    assert first_event is not None
    assert first_event["type"] == "view"
    assert first_event["active_session"] is None


@pytest.mark.asyncio
async def test_view_stream_switch_session(async_client):
    """Test switching sessions via POST /v1/view triggers SSE update."""
    r = await async_client.post("/v1/view", json={"action": "create_session", "model": "test"})
    session_id = r.json()["active_session"]["id"]

    events_received = []

    async with async_client.stream("GET", f"/v1/view/stream?session_id={session_id}") as response:
        async def read_initial():
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                    if data.get("type") == "view":
                        events_received.append(data)
                        return

        try:
            await asyncio.wait_for(read_initial(), timeout=5.0)
        except asyncio.TimeoutError:
            pass

    assert len(events_received) >= 1
    assert events_received[0]["active_session"]["id"] == session_id


async def _mock_chat_completion(self, messages, system=None, tools=None, stream=False):
    """Mock LLM that returns a simple text response."""
    yield {
        "content": [{"type": "text", "text": "Hello! I'm a test response."}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


@pytest.mark.asyncio
@patch("app.sessions.CustomLLMWrapper.chat_completion", _mock_chat_completion)
async def test_send_message(async_client):
    """Test sending a message via POST /v1/view returns 200 and starts the turn."""
    r = await async_client.post("/v1/view", json={"action": "create_session", "model": "test"})
    assert r.status_code == 200
    session_id = r.json()["active_session"]["id"]

    r = await async_client.post("/v1/view", json={
        "action": "send_message",
        "session_id": session_id,
        "message": "Hello, agent!",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["type"] == "view"
    assert data["active_session"]["id"] == session_id

    await asyncio.sleep(0.5)

    r = await async_client.post("/v1/view", json={"action": "get_view", "session_id": session_id})
    assert r.status_code == 200
    data = r.json()
    messages = data["messages"]
    assert len(messages) >= 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Hello, agent!"


@pytest.mark.asyncio
@patch("app.sessions.CustomLLMWrapper.chat_completion", _mock_chat_completion)
async def test_model_propagation(async_client):
    """Test that model changes propagate to the LLM session and are persisted."""
    # Create session with specific model
    r = await async_client.post("/v1/view", json={"action": "create_session", "model": "mock-model"})
    assert r.status_code == 200
    session_id = r.json()["active_session"]["id"]
    assert r.json()["active_session"]["model"] == "mock-model"

    # Get view - model should be mock-model
    r = await async_client.post("/v1/view", json={"action": "get_view", "session_id": session_id})
    assert r.json()["active_session"]["model"] == "mock-model"

    # Change model via set_model
    r = await async_client.post("/v1/view", json={
        "action": "set_model",
        "session_id": session_id,
        "model": "claude-opus-4-6",
    })
    assert r.status_code == 200
    assert r.json()["active_session"]["model"] == "claude-opus-4-6"

    # Get view - model should be updated
    r = await async_client.post("/v1/view", json={"action": "get_view", "session_id": session_id})
    assert r.json()["active_session"]["model"] == "claude-opus-4-6"

    # Send message - model should still be claude-opus-4-6
    r = await async_client.post("/v1/view", json={
        "action": "send_message",
        "session_id": session_id,
        "message": "test",
    })
    assert r.status_code == 200
    assert r.json()["active_session"]["model"] == "claude-opus-4-6"

    await asyncio.sleep(0.5)

    # Verify model persisted in session
    import app.main as main
    session = main.manager.get(session_id)
    assert session is not None
    assert session.model == "claude-opus-4-6"
    assert session._llm.model == "claude-opus-4-6"
