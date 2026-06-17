"""Tests: Agent conversation flow — send message, mock LLM, tool calls."""

import asyncio
import json
import pytest
from unittest import mock
from app.sessions import Session, SessionManager, PermissionResultAllow, PermissionResultDeny
from app.view_data import ViewDataGenerator
from app import database as db
import app.main as main

from .conftest import MockLLMClient, create_session, get_view, wait_for_session_idle


def _patch_mock_llm(sequence=None):
    """Return context manager patch for MockLLMClient."""
    client = MockLLMClient()
    if sequence:
        client.set_sequence(sequence)
    return mock.patch("app.sessions.CustomLLMWrapper", lambda **kw: client)


@pytest.mark.asyncio
async def test_send_message_returns_view_data(client):
    """send_message returns a ViewData snapshot."""
    sid = await create_session(client)
    r = await client.post("/v1/view", json={
        "action": "send_message", "session_id": sid, "message": "hello",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["type"] == "view"
    assert data["active_session"]["id"] == sid


@pytest.mark.asyncio
async def test_send_message_creates_user_message_in_db(client):
    """send_message persists the user message in the database."""
    sid = await create_session(client)
    await client.post("/v1/view", json={
        "action": "send_message", "session_id": sid, "message": "hello world",
    })
    r = await client.get(f"/v1/db/sessions/{sid}/messages")
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert len(msgs) >= 1
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "hello world"


@pytest.mark.asyncio
async def test_mock_llm_text_response(client, manager, view_gen):
    """Mock LLM returns text, which appears in messages."""
    main.manager = manager
    main.view_generator = view_gen

    p1 = _patch_mock_llm([
        {
            "content": [{"type": "text", "text": "Hello from mock"}],
            "stop_reason": "end_turn",
        },
    ])

    with p1:
        sid = await create_session(client)
        await client.post("/v1/view", json={
            "action": "send_message", "session_id": sid, "message": "test",
        })
        view = await wait_for_session_idle(client, sid)
        assistant_msgs = [m for m in view["messages"] if m["role"] == "assistant"]
        assert len(assistant_msgs) >= 1
        assert "Hello from mock" in assistant_msgs[0]["content"]


@pytest.mark.asyncio
async def test_mock_llm_tool_use_then_result(client, manager, view_gen):
    """Mock LLM triggers tool use, permission is auto-approved, result appears."""
    main.manager = manager
    main.view_generator = view_gen

    p1 = _patch_mock_llm([
        {
            "content": [
                {"type": "text", "text": "Running tool"},
                {
                    "type": "tool_use",
                    "id": "toolu_test_001",
                    "name": "Bash",
                    "input": {"command": "echo test"},
                },
            ],
            "stop_reason": "tool_use",
        },
        {
            "content": [{"type": "text", "text": "Done"}],
            "stop_reason": "end_turn",
        },
    ])

    with p1:
        sid = await create_session(client)
        await client.post("/v1/view", json={
            "action": "send_message", "session_id": sid, "message": "run something",
        })
        view = await wait_for_session_idle(client, sid)

        tool_msgs = [m for m in view["messages"] if m["role"] == "tool"]
        assert len(tool_msgs) >= 1
        assert tool_msgs[0]["type"] == "tool_result"


@pytest.mark.asyncio
async def test_permission_request_appears_in_view(client, manager, view_gen):
    """Tool with 'ask' rule triggers pending_actions in ViewData."""
    main.manager = manager
    main.view_generator = view_gen

    p1 = _patch_mock_llm([
        {
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_perm_001",
                    "name": "Bash",
                    "input": {"command": "ls"},
                },
            ],
            "stop_reason": "tool_use",
        },
    ])

    with p1:
        sid = await create_session(client)
        # Ensure Bash is set to 'ask'
        await client.post("/v1/view", json={
            "action": "update_tool_rule", "session_id": sid, "tool_name": "Bash", "tool_rule": "ask",
        })

        await client.post("/v1/view", json={
            "action": "send_message", "session_id": sid, "message": "run ls",
        })

        # Wait a bit for the permission to be created
        for _ in range(30):
            view = await get_view(client, sid)
            if view["pending_actions"]:
                break
            await asyncio.sleep(0.05)

        assert len(view["pending_actions"]) >= 1
        assert view["pending_actions"][0]["action_type"] == "permission"
        assert view["pending_actions"][0]["tool_name"] == "Bash"
        assert view["ui_state"]["awaiting_approval"] is True
        assert view["active_session"]["permission_status"] == "awaiting_approval"


@pytest.mark.asyncio
async def test_approve_permission_resumes_agent(client, manager, view_gen):
    """Approving a permission resumes the agent loop and produces tool_result."""
    main.manager = manager
    main.view_generator = view_gen

    p1 = _patch_mock_llm([
        {
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_approve_001",
                    "name": "Bash",
                    "input": {"command": "pwd"},
                },
            ],
            "stop_reason": "tool_use",
        },
        {
            "content": [{"type": "text", "text": "Completed"}],
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

        # Wait for permission request
        request_id = None
        for _ in range(30):
            view = await get_view(client, sid)
            if view["pending_actions"]:
                request_id = view["pending_actions"][0]["request_id"]
                break
            await asyncio.sleep(0.05)

        assert request_id is not None

        # Approve
        r = await client.post("/v1/view", json={
            "action": "respond_permission",
            "session_id": sid,
            "request_id": request_id,
            "approved": True,
        })
        assert r.status_code == 200

        # Wait for idle
        view = await wait_for_session_idle(client, sid)
        tool_msgs = [m for m in view["messages"] if m["role"] == "tool"]
        assert len(tool_msgs) >= 1


@pytest.mark.asyncio
async def test_deny_permission_blocks_tool(client, manager, view_gen):
    """Denying a permission produces a tool_error."""
    main.manager = manager
    main.view_generator = view_gen

    p1 = _patch_mock_llm([
        {
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_deny_001",
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

        # Wait for permission
        request_id = None
        for _ in range(30):
            view = await get_view(client, sid)
            if view["pending_actions"]:
                request_id = view["pending_actions"][0]["request_id"]
                break
            await asyncio.sleep(0.05)

        assert request_id is not None

        # Deny
        await client.post("/v1/view", json={
            "action": "respond_permission",
            "session_id": sid,
            "request_id": request_id,
            "approved": False,
        })

        view = await wait_for_session_idle(client, sid)
        error_msgs = [m for m in view["messages"] if m["type"] == "tool_error"]
        assert len(error_msgs) >= 1


@pytest.mark.asyncio
async def test_allow_tool_skips_permission(client, manager, view_gen):
    """Tool set to 'allow' skips permission prompt entirely."""
    main.manager = manager
    main.view_generator = view_gen

    p1 = _patch_mock_llm([
        {
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_allow_001",
                    "name": "Bash",
                    "input": {"command": "echo hi"},
                },
            ],
            "stop_reason": "tool_use",
        },
        {
            "content": [{"type": "text", "text": "Done"}],
            "stop_reason": "end_turn",
        },
    ])

    with p1:
        sid = await create_session(client)
        await client.post("/v1/view", json={
            "action": "update_tool_rule", "session_id": sid, "tool_name": "Bash", "tool_rule": "allow",
        })

        await client.post("/v1/view", json={
            "action": "send_message", "session_id": sid, "message": "echo",
        })

        view = await wait_for_session_idle(client, sid)
        assert view["pending_actions"] == []
        tool_msgs = [m for m in view["messages"] if m["role"] == "tool"]
        assert len(tool_msgs) >= 1


@pytest.mark.asyncio
async def test_deny_tool_blocks_immediately(client, manager, view_gen):
    """Tool set to 'deny' blocks without permission prompt."""
    main.manager = manager
    main.view_generator = view_gen

    p1 = _patch_mock_llm([
        {
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_deny2_001",
                    "name": "Bash",
                    "input": {"command": "ls"},
                },
            ],
            "stop_reason": "tool_use",
        },
    ])

    with p1:
        sid = await create_session(client)
        await client.post("/v1/view", json={
            "action": "update_tool_rule", "session_id": sid, "tool_name": "Bash", "tool_rule": "deny",
        })

        await client.post("/v1/view", json={
            "action": "send_message", "session_id": sid, "message": "ls",
        })

        view = await wait_for_session_idle(client, sid)
        assert view["pending_actions"] == []
        error_msgs = [m for m in view["messages"] if m["type"] == "tool_error"]
        assert len(error_msgs) >= 1
