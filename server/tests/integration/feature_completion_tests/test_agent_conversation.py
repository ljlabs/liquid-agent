"""Tests: Agent conversation flow — send message, mock LLM, tool calls.

Uses keyword-based routing in the mock LLM client.  When the user
message contains a known keyword the mock returns a canned response
matching that keyword, no explicit sequence needed.
"""

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


# ---------------------------------------------------------------------------
# Basic send_message
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Text-only response
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# "run pwd" — approve flow (full two-turn conversation)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_pwd_approve_flow(client, manager, view_gen):
    """'run pwd' triggers Bash(pwd), approve → tool_result, then final text.

    This is the primary integration test for the permission mechanism:
      Turn 1: LLM requests Bash(pwd) → permission card shown
      Turn 2: user approves → tool executes → LLM sees output → final text
    """
    main.manager = manager
    main.view_generator = view_gen

    with _patch_mock_llm():
        sid = await create_session(client)
        # Bash defaults to 'ask', so permission will be required
        await client.post("/v1/view", json={
            "action": "update_tool_rule", "session_id": sid,
            "tool_name": "Bash", "tool_rule": "ask",
        })

        # Send "run pwd" — keyword routing returns Bash(pwd) + text
        await client.post("/v1/view", json={
            "action": "send_message", "session_id": sid, "message": "run pwd",
        })

        # Wait for permission request
        request_id = None
        for _ in range(50):
            view = await get_view(client, sid)
            if view["pending_actions"]:
                request_id = view["pending_actions"][0]["request_id"]
                break
            await asyncio.sleep(0.05)

        assert request_id is not None, "No permission request appeared"
        assert view["pending_actions"][0]["tool_name"] == "Bash"
        assert view["ui_state"]["awaiting_approval"] is True
        assert view["active_session"]["permission_status"] == "awaiting_approval"

        # Approve the permission
        r = await client.post("/v1/view", json={
            "action": "respond_permission", "session_id": sid,
            "request_id": request_id, "approved": True,
        })
        assert r.status_code == 200

        # Wait for session to go idle (agent loop completes turn 2)
        view = await wait_for_session_idle(client, sid)

        # Verify tool_result message exists
        tool_msgs = [m for m in view["messages"] if m["role"] == "tool"]
        assert len(tool_msgs) >= 1, "No tool_result message after approval"
        assert tool_msgs[0]["type"] == "tool_result"

        # Verify final assistant text from turn 2
        assistant_msgs = [m for m in view["messages"] if m["role"] == "assistant"]
        assert len(assistant_msgs) >= 1
        # Turn 2 text should reference the output
        all_text = " ".join(m["content"] for m in assistant_msgs if m["content"])
        assert "directory" in all_text.lower() or "pwd" in all_text.lower()

        # Pending actions should be cleared
        assert view["pending_actions"] == []
        assert view["ui_state"]["awaiting_approval"] is False


# ---------------------------------------------------------------------------
# "run pwd" — deny flow (agent loop exits after denial)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_pwd_deny_flow(client, manager, view_gen):
    """'run pwd' triggers Bash(pwd), deny → tool_error → agent loop ends.

    After denial the session goes idle and waits for a follow-up command.
    The denied tool produces a tool_error message.
    """
    main.manager = manager
    main.view_generator = view_gen

    with _patch_mock_llm():
        sid = await create_session(client)
        await client.post("/v1/view", json={
            "action": "update_tool_rule", "session_id": sid,
            "tool_name": "Bash", "tool_rule": "ask",
        })

        await client.post("/v1/view", json={
            "action": "send_message", "session_id": sid, "message": "run pwd",
        })

        # Wait for permission request
        request_id = None
        for _ in range(50):
            view = await get_view(client, sid)
            if view["pending_actions"]:
                request_id = view["pending_actions"][0]["request_id"]
                break
            await asyncio.sleep(0.05)

        assert request_id is not None, "No permission request appeared"

        # Deny the permission
        r = await client.post("/v1/view", json={
            "action": "respond_permission", "session_id": sid,
            "request_id": request_id, "approved": False,
        })
        assert r.status_code == 200

        # Wait for session idle
        view = await wait_for_session_idle(client, sid)

        # Verify a tool_error message exists
        error_msgs = [m for m in view["messages"] if m["type"] == "tool_error"]
        assert len(error_msgs) >= 1, "No tool_error after denial"
        assert "denied" in error_msgs[0]["content"].lower()

        # Session should be idle, ready for follow-up
        assert view["active_session"]["status"] == "idle"
        assert view["pending_actions"] == []


# ---------------------------------------------------------------------------
# "run pwd" with Bash set to 'allow' — no permission needed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_pwd_auto_allow(client, manager, view_gen):
    """'run pwd' with Bash=allow skips permission, tool_result appears."""
    main.manager = manager
    main.view_generator = view_gen

    with _patch_mock_llm():
        sid = await create_session(client)
        await client.post("/v1/view", json={
            "action": "update_tool_rule", "session_id": sid,
            "tool_name": "Bash", "tool_rule": "allow",
        })

        await client.post("/v1/view", json={
            "action": "send_message", "session_id": sid, "message": "run pwd",
        })

        view = await wait_for_session_idle(client, sid)

        # No permission prompt
        assert view["pending_actions"] == []

        # Tool executed directly
        tool_msgs = [m for m in view["messages"] if m["role"] == "tool"]
        assert len(tool_msgs) >= 1
        assert tool_msgs[0]["type"] == "tool_result"


# ---------------------------------------------------------------------------
# "echo" — keyword routing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_echo_keyword_flow(client, manager, view_gen):
    """'echo' keyword triggers Bash(echo hello), approve → tool_result + text."""
    main.manager = manager
    main.view_generator = view_gen

    with _patch_mock_llm():
        sid = await create_session(client)
        await client.post("/v1/view", json={
            "action": "update_tool_rule", "session_id": sid,
            "tool_name": "Bash", "tool_rule": "ask",
        })

        await client.post("/v1/view", json={
            "action": "send_message", "session_id": sid, "message": "echo",
        })

        request_id = None
        for _ in range(50):
            view = await get_view(client, sid)
            if view["pending_actions"]:
                request_id = view["pending_actions"][0]["request_id"]
                break
            await asyncio.sleep(0.05)

        assert request_id is not None

        await client.post("/v1/view", json={
            "action": "respond_permission", "session_id": sid,
            "request_id": request_id, "approved": True,
        })

        view = await wait_for_session_idle(client, sid)
        tool_msgs = [m for m in view["messages"] if m["role"] == "tool"]
        assert len(tool_msgs) >= 1

        assistant_msgs = [m for m in view["messages"] if m["role"] == "assistant"]
        all_text = " ".join(m["content"] for m in assistant_msgs if m["content"])
        assert "echo" in all_text.lower() or "completed" in all_text.lower()


# ---------------------------------------------------------------------------
# "run ls" — keyword routing with deny
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_ls_deny_flow(client, manager, view_gen):
    """'run ls' triggers Bash(ls), deny → tool_error → idle."""
    main.manager = manager
    main.view_generator = view_gen

    with _patch_mock_llm():
        sid = await create_session(client)
        await client.post("/v1/view", json={
            "action": "update_tool_rule", "session_id": sid,
            "tool_name": "Bash", "tool_rule": "ask",
        })

        await client.post("/v1/view", json={
            "action": "send_message", "session_id": sid, "message": "run ls",
        })

        request_id = None
        for _ in range(50):
            view = await get_view(client, sid)
            if view["pending_actions"]:
                request_id = view["pending_actions"][0]["request_id"]
                break
            await asyncio.sleep(0.05)

        assert request_id is not None

        await client.post("/v1/view", json={
            "action": "respond_permission", "session_id": sid,
            "request_id": request_id, "approved": False,
        })

        view = await wait_for_session_idle(client, sid)
        error_msgs = [m for m in view["messages"] if m["type"] == "tool_error"]
        assert len(error_msgs) >= 1
        assert view["active_session"]["status"] == "idle"
