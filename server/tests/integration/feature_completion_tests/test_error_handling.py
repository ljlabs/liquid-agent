"""Tests: Error handling for invalid requests."""

import pytest
from .conftest import get_view


@pytest.mark.asyncio
async def test_invalid_action_returns_422(client):
    """Invalid action name returns 422."""
    r = await client.post("/v1/view", json={"action": "invalid_action"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_missing_action_returns_422(client):
    """Missing action field returns 422."""
    r = await client.post("/v1/view", json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_empty_body_returns_422(client):
    """Empty body returns 422."""
    r = await client.post("/v1/view", json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_respond_permission_invalid_request_id(client):
    """Responding to nonexistent permission returns 404."""
    from .conftest import create_session
    sid = await create_session(client)
    r = await client.post("/v1/view", json={
        "action": "respond_permission",
        "session_id": sid,
        "request_id": "nonexistent_req",
        "approved": True,
    })
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_health_endpoint(client):
    """Health endpoint returns 200 with expected fields."""
    r = await client.get("/v1/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "sdk_available" in data
    assert "active_sessions" in data


@pytest.mark.asyncio
async def test_tool_defaults_endpoint(client):
    """Tool defaults endpoint returns canonical tool list."""
    r = await client.get("/v1/tool-defaults")
    assert r.status_code == 200
    data = r.json()
    assert "tools" in data
    assert "rules" in data
    assert "Bash" in data["tools"]
    assert "Read" in data["tools"]
