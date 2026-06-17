"""Tests: Database persistence through the view endpoint."""

import pytest
from .conftest import create_session, get_view


@pytest.mark.asyncio
async def test_session_created_in_db(client):
    """Session created via view endpoint appears in DB."""
    sid = await create_session(client)
    r = await client.get("/v1/db/sessions")
    assert r.status_code == 200
    sessions = r.json()["sessions"]
    assert any(s["id"] == sid for s in sessions)


@pytest.mark.asyncio
async def test_session_deleted_from_db(client):
    """Session deleted via view endpoint removed from DB."""
    sid = await create_session(client)
    await client.post("/v1/view", json={"action": "delete_session", "session_id": sid})
    r = await client.get("/v1/db/sessions")
    sessions = r.json()["sessions"]
    assert all(s["id"] != sid for s in sessions)


@pytest.mark.asyncio
async def test_user_message_persisted(client):
    """User message persisted in DB after send_message."""
    sid = await create_session(client)
    await client.post("/v1/view", json={
        "action": "send_message", "session_id": sid, "message": "persist me",
    })
    r = await client.get(f"/v1/db/sessions/{sid}/messages")
    msgs = r.json()["messages"]
    assert any(m["content"] == "persist me" and m["role"] == "user" for m in msgs)


@pytest.mark.asyncio
async def test_tool_rule_persisted(client):
    """Tool rule change persisted in DB."""
    sid = await create_session(client)
    await client.post("/v1/view", json={
        "action": "update_tool_rule", "session_id": sid, "tool_name": "Bash", "tool_rule": "allow",
    })
    r = await client.get(f"/v1/sessions/{sid}/tool-rules")
    rules = {rule["tool"]: rule["rule"] for rule in r.json()["rules"]}
    assert rules["Bash"] == "allow"


@pytest.mark.asyncio
async def test_permission_mode_persisted(client):
    """Permission mode change persisted in DB."""
    sid = await create_session(client)
    await client.post("/v1/view", json={
        "action": "set_mode", "session_id": sid, "permission_mode": "plan",
    })
    r = await client.get(f"/v1/db/sessions/{sid}")
    assert r.json()["permission_mode"] == "plan"


@pytest.mark.asyncio
async def test_db_session_not_found(client):
    """Fetching nonexistent DB session returns 404."""
    r = await client.get("/v1/db/sessions/nonexistent")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_db_messages_not_found(client):
    """Fetching messages for nonexistent session returns 404."""
    r = await client.get("/v1/db/sessions/nonexistent/messages")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_db_delete_not_found(client):
    """Deleting nonexistent DB session returns 404."""
    r = await client.delete("/v1/db/sessions/nonexistent")
    assert r.status_code == 404
