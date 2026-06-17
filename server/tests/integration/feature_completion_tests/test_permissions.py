"""Tests: Permission modes and tool rules via /v1/view endpoint."""

import pytest
from .conftest import create_session, get_view


@pytest.mark.asyncio
async def test_set_mode_accept_edits(client):
    """set_mode changes permission mode to acceptEdits."""
    sid = await create_session(client)
    r = await client.post("/v1/view", json={
        "action": "set_mode",
        "session_id": sid,
        "permission_mode": "acceptEdits",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["active_session"]["permission_mode"] == "acceptEdits"
    assert data["ui_state"]["mode"] == "acceptEdits"


@pytest.mark.asyncio
async def test_set_mode_plan(client):
    """set_mode changes permission mode to plan."""
    sid = await create_session(client)
    r = await client.post("/v1/view", json={
        "action": "set_mode",
        "session_id": sid,
        "permission_mode": "plan",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["active_session"]["permission_mode"] == "plan"
    assert data["ui_state"]["mode"] == "plan"


@pytest.mark.asyncio
async def test_set_mode_bypass(client):
    """set_mode changes permission mode to bypassPermissions."""
    sid = await create_session(client)
    r = await client.post("/v1/view", json={
        "action": "set_mode",
        "session_id": sid,
        "permission_mode": "bypassPermissions",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["active_session"]["permission_mode"] == "bypassPermissions"


@pytest.mark.asyncio
async def test_set_mode_back_to_default(client):
    """Mode can be cycled back to default."""
    sid = await create_session(client)
    await client.post("/v1/view", json={
        "action": "set_mode", "session_id": sid, "permission_mode": "plan",
    })
    r = await client.post("/v1/view", json={
        "action": "set_mode", "session_id": sid, "permission_mode": "default",
    })
    data = r.json()
    assert data["active_session"]["permission_mode"] == "default"
    assert data["ui_state"]["mode"] == "default"


@pytest.mark.asyncio
async def test_default_tool_rules(client):
    """New session has correct default tool rules."""
    sid = await create_session(client)
    view = await get_view(client, sid)
    rules = {r["tool"]: r["rule"] for r in view["tool_rules"]}
    assert rules["Bash"] == "ask"
    assert rules["Read"] == "allow"
    assert rules["Write"] == "ask"
    assert rules["Glob"] == "allow"
    assert rules["Grep"] == "allow"
    assert rules["WebFetch"] == "allow"


@pytest.mark.asyncio
async def test_update_tool_rule_allow(client):
    """update_tool_rule changes a rule to allow."""
    sid = await create_session(client)
    r = await client.post("/v1/view", json={
        "action": "update_tool_rule",
        "session_id": sid,
        "tool_name": "Bash",
        "tool_rule": "allow",
    })
    assert r.status_code == 200
    data = r.json()
    bash_rule = next(r for r in data["tool_rules"] if r["tool"] == "Bash")
    assert bash_rule["rule"] == "allow"


@pytest.mark.asyncio
async def test_update_tool_rule_deny(client):
    """update_tool_rule changes a rule to deny."""
    sid = await create_session(client)
    r = await client.post("/v1/view", json={
        "action": "update_tool_rule",
        "session_id": sid,
        "tool_name": "Bash",
        "tool_rule": "deny",
    })
    assert r.status_code == 200
    data = r.json()
    bash_rule = next(r for r in data["tool_rules"] if r["tool"] == "Bash")
    assert bash_rule["rule"] == "deny"


@pytest.mark.asyncio
async def test_update_tool_rule_back_to_ask(client):
    """update_tool_rule can reset to ask."""
    sid = await create_session(client)
    await client.post("/v1/view", json={
        "action": "update_tool_rule", "session_id": sid, "tool_name": "Bash", "tool_rule": "allow",
    })
    r = await client.post("/v1/view", json={
        "action": "update_tool_rule", "session_id": sid, "tool_name": "Bash", "tool_rule": "ask",
    })
    data = r.json()
    bash_rule = next(r for r in data["tool_rules"] if r["tool"] == "Bash")
    assert bash_rule["rule"] == "ask"


@pytest.mark.asyncio
async def test_update_tool_rule_persists_in_db(client):
    """Tool rule change persists in the database."""
    sid = await create_session(client)
    await client.post("/v1/view", json={
        "action": "update_tool_rule", "session_id": sid, "tool_name": "Bash", "tool_rule": "deny",
    })
    r = await client.get(f"/v1/sessions/{sid}/tool-rules")
    assert r.status_code == 200
    rules = {rule["tool"]: rule["rule"] for rule in r.json()["rules"]}
    assert rules["Bash"] == "deny"


@pytest.mark.asyncio
async def test_mode_persists_in_db(client):
    """Permission mode change persists in the database."""
    sid = await create_session(client)
    await client.post("/v1/view", json={
        "action": "set_mode", "session_id": sid, "permission_mode": "plan",
    })
    r = await client.get(f"/v1/db/sessions/{sid}")
    assert r.status_code == 200
    assert r.json()["permission_mode"] == "plan"


@pytest.mark.asyncio
async def test_set_mode_no_session_ignored(client):
    """set_mode with no active session doesn't crash."""
    r = await client.post("/v1/view", json={
        "action": "set_mode", "session_id": None, "permission_mode": "plan",
    })
    assert r.status_code == 200
