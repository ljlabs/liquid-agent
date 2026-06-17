"""Tests: Right drawer — files tracking, usage, tool call log, session logs."""

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


# -----------------------------------------------------------------------
# Files tracking
# -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_files_empty_for_new_session(client):
    """New session has empty files lists."""
    sid = await create_session(client)
    view = await get_view(client, sid)
    assert view["files"]["changed"] == []
    assert view["files"]["recently_read"] == []


@pytest.mark.asyncio
async def test_files_changed_after_write_tool(client, manager, view_gen):
    """Write tool adds file to changed list."""
    main.manager = manager
    main.view_generator = view_gen

    p1 = _patch_mock_llm([
        {
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_write_001",
                    "name": "Write",
                    "input": {"path": "/tmp/test.txt", "content": "hello"},
                },
            ],
            "stop_reason": "tool_use",
        },
        {
            "content": [{"type": "text", "text": "Written"}],
            "stop_reason": "end_turn",
        },
    ])

    with p1:
        sid = await create_session(client)
        await client.post("/v1/view", json={
            "action": "send_message", "session_id": sid, "message": "write a file",
        })
        view = await wait_for_session_idle(client, sid)
        changed = view["files"]["changed"]
        assert any("test.txt" in f["path"] for f in changed)
        assert any(f["tool_name"] == "Write" for f in changed)


@pytest.mark.asyncio
async def test_files_changed_after_edit_tool(client, manager, view_gen):
    """Edit tool adds file to changed list."""
    main.manager = manager
    main.view_generator = view_gen

    p1 = _patch_mock_llm([
        {
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_edit_001",
                    "name": "Replace",
                    "input": {"path": "/tmp/edit.txt", "old_string": "a", "new_string": "b"},
                },
            ],
            "stop_reason": "tool_use",
        },
        {
            "content": [{"type": "text", "text": "Edited"}],
            "stop_reason": "end_turn",
        },
    ])

    with p1:
        sid = await create_session(client)
        await client.post("/v1/view", json={
            "action": "send_message", "session_id": sid, "message": "edit a file",
        })
        view = await wait_for_session_idle(client, sid)
        changed = view["files"]["changed"]
        assert any("edit.txt" in f["path"] for f in changed)


@pytest.mark.asyncio
async def test_files_recently_read_after_read_tool(client, manager, view_gen):
    """Read tool adds file to recently_read list."""
    main.manager = manager
    main.view_generator = view_gen

    p1 = _patch_mock_llm([
        {
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_read_001",
                    "name": "Read",
                    "input": {"path": "/tmp/readme.txt"},
                },
            ],
            "stop_reason": "tool_use",
        },
        {
            "content": [{"type": "text", "text": "Read it"}],
            "stop_reason": "end_turn",
        },
    ])

    with p1:
        sid = await create_session(client)
        await client.post("/v1/view", json={
            "action": "send_message", "session_id": sid, "message": "read a file",
        })
        view = await wait_for_session_idle(client, sid)
        recently_read = view["files"]["recently_read"]
        assert any("readme.txt" in f["path"] for f in recently_read)
        assert any(f["tool_name"] == "Read" for f in recently_read)


# -----------------------------------------------------------------------
# Usage tracking
# -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_usage_zero_for_new_session(client):
    """New session has zero usage."""
    sid = await create_session(client)
    view = await get_view(client, sid)
    u = view["usage"]
    assert u["input_tokens"] == 0
    assert u["output_tokens"] == 0
    assert u["estimated_cost"] == 0.0


@pytest.mark.asyncio
async def test_usage_positive_after_message(client, manager, view_gen):
    """Usage tokens are positive after sending a message."""
    main.manager = manager
    main.view_generator = view_gen

    p1 = _patch_mock_llm([
        {
            "content": [{"type": "text", "text": "Response"}],
            "stop_reason": "end_turn",
        },
    ])

    with p1:
        sid = await create_session(client)
        await client.post("/v1/view", json={
            "action": "send_message", "session_id": sid, "message": "hello",
        })
        view = await wait_for_session_idle(client, sid)
        u = view["usage"]
        assert u["input_tokens"] > 0 or u["output_tokens"] > 0


@pytest.mark.asyncio
async def test_usage_wall_time_positive(client, manager, view_gen):
    """Wall time is positive after a turn."""
    main.manager = manager
    main.view_generator = view_gen

    p1 = _patch_mock_llm([
        {
            "content": [{"type": "text", "text": "Hi"}],
            "stop_reason": "end_turn",
        },
    ])

    with p1:
        sid = await create_session(client)
        await client.post("/v1/view", json={
            "action": "send_message", "session_id": sid, "message": "hi",
        })
        view = await wait_for_session_idle(client, sid)
        assert view["usage"]["wall_time_seconds"] > 0


@pytest.mark.asyncio
async def test_context_window_has_valid_max(client):
    """Context window max is positive, percentage in range."""
    sid = await create_session(client)
    view = await get_view(client, sid)
    cw = view["usage"]["context_window"]
    assert cw["max"] > 0
    assert 0.0 <= cw["percentage"] <= 100.0


# -----------------------------------------------------------------------
# Tool call log
# -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_call_log_empty_for_new_session(client):
    """New session has empty tool call log."""
    sid = await create_session(client)
    view = await get_view(client, sid)
    assert view["tool_call_log"] == []


@pytest.mark.asyncio
async def test_tool_call_log_after_tool_use(client, manager, view_gen):
    """Tool call log populated after tool execution."""
    main.manager = manager
    main.view_generator = view_gen

    p1 = _patch_mock_llm([
        {
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_log_001",
                    "name": "Bash",
                    "input": {"command": "echo log"},
                },
            ],
            "stop_reason": "tool_use",
        },
        {
            "content": [{"type": "text", "text": "Logged"}],
            "stop_reason": "end_turn",
        },
    ])

    with p1:
        sid = await create_session(client)
        await client.post("/v1/view", json={
            "action": "send_message", "session_id": sid, "message": "run echo",
        })
        view = await wait_for_session_idle(client, sid)
        log = view["tool_call_log"]
        assert len(log) >= 1
        assert log[0]["tool_name"] == "Bash"
        assert log[0]["status"] in ("success", "error")


@pytest.mark.asyncio
async def test_tool_call_log_chronological(client, manager, view_gen):
    """Tool call log entries are ordered by timestamp."""
    main.manager = manager
    main.view_generator = view_gen

    p1 = _patch_mock_llm([
        {
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_chrono_001",
                    "name": "Bash",
                    "input": {"command": "echo first"},
                },
            ],
            "stop_reason": "tool_use",
        },
        {
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_chrono_002",
                    "name": "Bash",
                    "input": {"command": "echo second"},
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
            "action": "send_message", "session_id": sid, "message": "run two commands",
        })
        view = await wait_for_session_idle(client, sid)
        log = view["tool_call_log"]
        if len(log) >= 2:
            assert log[0]["timestamp"] <= log[1]["timestamp"]


# -----------------------------------------------------------------------
# Session logs
# -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_log_empty_for_new_session(client):
    """New session has empty session log."""
    sid = await create_session(client)
    view = await get_view(client, sid)
    assert view["session_log"] == []


@pytest.mark.asyncio
async def test_session_log_structure(client):
    """Session log entries have valid structure."""
    sid = await create_session(client)
    view = await get_view(client, sid)
    for entry in view["session_log"]:
        assert isinstance(entry["timestamp"], float)
        assert entry["level"] in ("info", "warn", "error")
        assert isinstance(entry["message"], str)
