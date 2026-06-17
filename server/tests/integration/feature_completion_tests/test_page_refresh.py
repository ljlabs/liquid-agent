"""Tests: Page refresh resumption — pending permissions survive session removal."""

import asyncio
import json
import pytest
from unittest import mock
from app.sessions import Session, SessionManager, PermissionResultAllow
from app.view_data import ViewDataGenerator
from app import database as db
import app.main as main

from .conftest import MockLLMClient, create_session, get_view, wait_for_session_idle


def _patch_mock_llm(sequence=None):
    client = MockLLMClient()
    if sequence:
        client.set_sequence(sequence)
    return mock.patch("app.sessions.CustomLLMWrapper", lambda **kw: client)


@pytest.mark.asyncio
async def test_pending_permission_survives_session_removal(client, manager, view_gen):
    """Pending permission persists in DB after in-memory session is removed."""
    main.manager = manager
    main.view_generator = view_gen

    p1 = _patch_mock_llm([
        {
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_refresh_001",
                    "name": "Bash",
                    "input": {"command": "pwd"},
                },
            ],
            "stop_reason": "tool_use",
        },
    ])

    with p1:
        sid = await create_session(client)
        await client.post("/v1/view", json={
            "action": "update_tool_rule", "session_id": sid, "tool_name": "Bash", "tool_rule": "ask",
        })

        await client.post("/v1/view", json={
            "action": "send_message", "session_id": sid, "message": "run pwd",
        })

        # Wait for permission
        request_id = None
        for _ in range(30):
            view = await get_view(client, sid)
            if view["pending_actions"]:
                request_id = view["pending_actions"][0]["request_id"]
                break
            await asyncio.sleep(0.05)

        assert request_id is not None

        # Simulate page refresh: drop all in-memory sessions
        sessions_resp = await client.get("/v1/sessions")
        for s in sessions_resp.json()["sessions"]:
            await client.delete(f"/v1/sessions/{s['session_id']}")

        # Verify no in-memory sessions
        sessions_resp = await client.get("/v1/sessions")
        assert len(sessions_resp.json()["sessions"]) == 0

        # Pending permission must survive in DB
        r = await client.get(f"/v1/sessions/{sid}/pending-permissions")
        assert r.status_code == 200
        db_perms = r.json()["permissions"]
        assert any(p["request_id"] == request_id for p in db_perms)


@pytest.mark.asyncio
async def test_approve_after_refresh_resumes_agent(client, manager, view_gen):
    """Approving permission after session removal restores session and resumes."""
    main.manager = manager
    main.view_generator = view_gen

    p1 = _patch_mock_llm([
        {
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_refresh2_001",
                    "name": "Bash",
                    "input": {"command": "pwd"},
                },
            ],
            "stop_reason": "tool_use",
        },
        {
            "content": [{"type": "text", "text": "Done after refresh"}],
            "stop_reason": "end_turn",
        },
    ])

    with p1:
        sid = await create_session(client)
        await client.post("/v1/view", json={
            "action": "update_tool_rule", "session_id": sid, "tool_name": "Bash", "tool_rule": "ask",
        })

        await client.post("/v1/view", json={
            "action": "send_message", "session_id": sid, "message": "run pwd",
        })

        # Wait for permission
        request_id = None
        for _ in range(30):
            view = await get_view(client, sid)
            if view["pending_actions"]:
                request_id = view["pending_actions"][0]["request_id"]
                break
            await asyncio.sleep(0.05)

        assert request_id is not None

        # Drop all in-memory sessions
        sessions_resp = await client.get("/v1/sessions")
        for s in sessions_resp.json()["sessions"]:
            await client.delete(f"/v1/sessions/{s['session_id']}")

        # Approve via the API (reconnects session from DB)
        r = await client.post(
            f"/v1/sessions/{sid}/permissions/respond",
            json={"request_id": request_id, "approved": True, "always": False},
        )
        assert r.status_code == 200
        assert r.json()["resolved"] is True

        # Wait for agent loop to finish
        for _ in range(50):
            r = await client.get(f"/v1/db/sessions/{sid}/messages")
            msgs = r.json()["messages"]
            has_result = any(m["role"] == "tool" and m["type"] == "tool_result" for m in msgs)
            has_text = any(m["role"] == "assistant" and m["type"] == "text" for m in msgs)
            if has_result and has_text:
                break
            await asyncio.sleep(0.1)

        # Pending permissions should be cleared
        r = await client.get(f"/v1/sessions/{sid}/pending-permissions")
        assert len(r.json()["permissions"]) == 0


@pytest.mark.asyncio
async def test_deny_after_refresh_stops_agent(client, manager, view_gen):
    """Denying permission after session removal produces denied message."""
    main.manager = manager
    main.view_generator = view_gen

    p1 = _patch_mock_llm([
        {
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_refresh3_001",
                    "name": "Bash",
                    "input": {"command": "rm -rf /"},
                },
            ],
            "stop_reason": "tool_use",
        },
    ])

    with p1:
        sid = await create_session(client)
        await client.post("/v1/view", json={
            "action": "update_tool_rule", "session_id": sid, "tool_name": "Bash", "tool_rule": "ask",
        })

        await client.post("/v1/view", json={
            "action": "send_message", "session_id": sid, "message": "delete everything",
        })

        request_id = None
        for _ in range(30):
            view = await get_view(client, sid)
            if view["pending_actions"]:
                request_id = view["pending_actions"][0]["request_id"]
                break
            await asyncio.sleep(0.05)

        assert request_id is not None

        # Drop sessions
        sessions_resp = await client.get("/v1/sessions")
        for s in sessions_resp.json()["sessions"]:
            await client.delete(f"/v1/sessions/{s['session_id']}")

        # Deny
        r = await client.post(
            f"/v1/sessions/{sid}/permissions/respond",
            json={"request_id": request_id, "approved": False},
        )
        assert r.status_code == 200

        # Check DB for denied message
        for _ in range(30):
            r = await client.get(f"/v1/db/sessions/{sid}/messages")
            msgs = r.json()["messages"]
            if any("denied" in (m.get("content") or "").lower() for m in msgs):
                break
            await asyncio.sleep(0.1)

        denied = [m for m in msgs if "denied" in (m.get("content") or "").lower()]
        assert len(denied) > 0
