"""Tests: SSE stream endpoint /v1/view/stream."""

import asyncio
import json
import pytest
from .conftest import create_session


@pytest.mark.asyncio
async def test_stream_returns_sse(client):
    """GET /v1/view/stream returns text/event-stream."""
    async with client.stream("GET", "/v1/view/stream") as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_stream_first_event_is_view(client):
    """First event from stream is a ViewData object."""
    sid = await create_session(client)
    first_view = None
    async with client.stream("GET", f"/v1/view/stream?session_id={sid}") as resp:
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                data = json.loads(line[6:])
                if data.get("type") == "view":
                    first_view = data
                    break
    assert first_view is not None
    assert first_view["type"] == "view"
    assert first_view["active_session"]["id"] == sid


@pytest.mark.asyncio
async def test_stream_no_session(client):
    """Stream with no session_id returns ViewData with no active_session."""
    first_view = None
    async with client.stream("GET", "/v1/view/stream") as resp:
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                data = json.loads(line[6:])
                if data.get("type") == "view":
                    first_view = data
                    break
    assert first_view is not None
    assert first_view["active_session"] is None


@pytest.mark.asyncio
async def test_stream_sends_done_when_idle(client):
    """Stream sends done event when session is idle."""
    sid = await create_session(client)
    got_done = False
    async with client.stream("GET", f"/v1/view/stream?session_id={sid}") as resp:
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                data = json.loads(line[6:])
                if data.get("type") == "done":
                    got_done = True
                    break
    assert got_done


@pytest.mark.asyncio
async def test_stream_view_data_has_all_fields(client):
    """ViewData from stream has all required top-level fields."""
    sid = await create_session(client)
    async with client.stream("GET", f"/v1/view/stream?session_id={sid}") as resp:
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                data = json.loads(line[6:])
                if data.get("type") == "view":
                    assert "active_session" in data
                    assert "sessions" in data
                    assert "ui_state" in data
                    assert "messages" in data
                    assert "pending_actions" in data
                    assert "tool_rules" in data
                    assert "files" in data
                    assert "usage" in data
                    assert "tool_call_log" in data
                    assert "session_log" in data
                    break
