"""Tests: Session management via /v1/view endpoint."""

import pytest
from .conftest import create_session, get_view


@pytest.mark.asyncio
async def test_get_view_no_session(client):
    """get_view with no session returns empty state."""
    view = await get_view(client)
    assert view["type"] == "view"
    assert view["active_session"] is None
    assert view["sessions"] == []
    assert view["messages"] == []


@pytest.mark.asyncio
async def test_create_session_returns_active_session(client):
    """create_session returns ViewData with active_session populated."""
    view = await client.post("/v1/view", json={"action": "create_session", "model": "mock-model"})
    data = view.json()
    assert data["type"] == "view"
    session = data["active_session"]
    assert session is not None
    assert session["id"].startswith("sess_")
    assert session["model"] == "mock-model"
    assert session["permission_mode"] == "default"
    assert session["status"] == "idle"


@pytest.mark.asyncio
async def test_create_session_has_tool_rules(client):
    """create_session returns default tool rules."""
    sid = await create_session(client)
    view = await get_view(client, sid)
    assert len(view["tool_rules"]) > 0
    rules_by_tool = {r["tool"]: r["rule"] for r in view["tool_rules"]}
    assert rules_by_tool["Bash"] == "ask"
    assert rules_by_tool["Read"] == "allow"


@pytest.mark.asyncio
async def test_get_view_with_session(client):
    """get_view with session_id returns that session's data."""
    sid = await create_session(client)
    view = await get_view(client, sid)
    assert view["active_session"]["id"] == sid
    assert view["messages"] == []


@pytest.mark.asyncio
async def test_delete_session(client):
    """delete_session removes the session."""
    sid = await create_session(client)
    r = await client.post("/v1/view", json={"action": "delete_session", "session_id": sid})
    assert r.status_code == 200
    view = await get_view(client, sid)
    assert view["active_session"] is None


@pytest.mark.asyncio
async def test_switch_session(client):
    """switch_session restores a session by ID."""
    sid = await create_session(client)
    # Delete from memory
    await client.post("/v1/view", json={"action": "delete_session", "session_id": sid})
    # Switch back
    r = await client.post("/v1/view", json={"action": "switch_session", "session_id": sid})
    assert r.status_code == 200
    data = r.json()
    assert data["active_session"]["id"] == sid


@pytest.mark.asyncio
async def test_session_list_empty_initially(client):
    """Session list is empty before any sessions created."""
    view = await get_view(client)
    assert view["sessions"] == []


@pytest.mark.asyncio
async def test_session_list_after_create(client):
    """Session list includes newly created session."""
    sid = await create_session(client)
    view = await get_view(client)
    assert len(view["sessions"]) >= 1
    assert any(s["id"] == sid for s in view["sessions"])


@pytest.mark.asyncio
async def test_session_list_multiple(client):
    """Session list shows multiple sessions."""
    sid1 = await create_session(client, model="m1")
    sid2 = await create_session(client, model="m2")
    view = await get_view(client)
    ids = [s["id"] for s in view["sessions"]]
    assert sid1 in ids
    assert sid2 in ids


@pytest.mark.asyncio
async def test_session_list_after_delete(client):
    """Deleted session removed from list."""
    sid = await create_session(client)
    await client.post("/v1/view", json={"action": "delete_session", "session_id": sid})
    view = await get_view(client)
    assert all(s["id"] != sid for s in view["sessions"])


@pytest.mark.asyncio
async def test_delete_nonexistent_session_is_idempotent(client):
    """Deleting a nonexistent session doesn't error."""
    r = await client.post("/v1/view", json={"action": "delete_session", "session_id": "nope"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_get_view_nonexistent_session(client):
    """get_view with bad session_id returns no active_session."""
    view = await get_view(client, "nonexistent")
    assert view["active_session"] is None
