"""Tests: Legacy endpoint compatibility — old endpoints still work."""

import pytest


@pytest.mark.asyncio
async def test_legacy_create_session(client):
    """POST /v1/sessions still creates sessions."""
    r = await client.post("/v1/sessions", json={"cwd": "/tmp", "model": "mock-model"})
    assert r.status_code == 200
    data = r.json()
    assert "session_id" in data
    assert data["model"] == "mock-model"


@pytest.mark.asyncio
async def test_legacy_list_sessions(client):
    """GET /v1/sessions still lists sessions."""
    await client.post("/v1/sessions", json={"cwd": "/tmp"})
    r = await client.get("/v1/sessions")
    assert r.status_code == 200
    assert isinstance(r.json()["sessions"], list)


@pytest.mark.asyncio
async def test_legacy_close_session(client):
    """DELETE /v1/sessions/{id} still closes sessions."""
    create_r = await client.post("/v1/sessions", json={"cwd": "/tmp"})
    sid = create_r.json()["session_id"]
    r = await client.delete(f"/v1/sessions/{sid}")
    assert r.status_code == 200
    assert r.json()["closed"] is True


@pytest.mark.asyncio
async def test_legacy_close_nonexistent(client):
    """DELETE /v1/sessions/{id} returns 404 for unknown session."""
    r = await client.delete("/v1/sessions/nonexistent")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_legacy_tool_defaults(client):
    """GET /v1/tool-defaults returns canonical tool list."""
    r = await client.get("/v1/tool-defaults")
    assert r.status_code == 200
    data = r.json()
    assert "Bash" in data["tools"]
    assert "Read" in data["tools"]
    assert len(data["rules"]) > 0


@pytest.mark.asyncio
async def test_legacy_session_tool_rules(client):
    """GET /v1/sessions/{id}/tool-rules returns rules."""
    create_r = await client.post("/v1/sessions", json={"cwd": "/tmp"})
    sid = create_r.json()["session_id"]
    r = await client.get(f"/v1/sessions/{sid}/tool-rules")
    assert r.status_code == 200
    data = r.json()
    assert "tools" in data
    assert "rules" in data


@pytest.mark.asyncio
async def test_legacy_pending_permissions(client):
    """GET /v1/sessions/{id}/pending-permissions returns list."""
    create_r = await client.post("/v1/sessions", json={"cwd": "/tmp"})
    sid = create_r.json()["session_id"]
    r = await client.get(f"/v1/sessions/{sid}/pending-permissions")
    assert r.status_code == 200
    assert "permissions" in r.json()
