"""
Integration test: tool_use bubble appears in ViewData and is stored in SQLite.

Verifies that when the LLM returns a tool_use block, the backend:
  1. Stores a tool_use message in the database
  2. Includes the tool_use as a separate MessageView in ViewData
  3. Shows pending_approval status when a permission is required
"""

import asyncio
import json
import os

import httpx
import pytest

from app.main import app
from app.sessions import SessionManager
from app.view_data import ViewDataGenerator
from app import database as db
import app.main as main


@pytest.fixture
async def client():
    """AsyncClient with manager + view_generator initialised."""
    main.manager = SessionManager()
    main.view_generator = ViewDataGenerator(main.manager, db)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    await main.manager.close_all()
    # Give background tasks a moment to finish writing to DB before closing
    await asyncio.sleep(0.5)
    await db.close_db()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

MOCK_BASE = None  # set by conftest autouse fixture


@pytest.fixture(autouse=True)
def _set_mock_port(mock_llm_server):
    global MOCK_BASE
    MOCK_BASE = f"http://127.0.0.1:{mock_llm_server}"
    os.environ["ANTHROPIC_BASE_URL"] = MOCK_BASE
    os.environ["ANTHROPIC_MODEL"] = "mock-model"


async def reset_mock():
    async with httpx.AsyncClient() as c:
        await c.post(f"{MOCK_BASE}/reset", timeout=10)


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_use_appears_in_view_data(client):
    """Send a message that triggers Bash tool_use, verify it appears in ViewData."""
    await reset_mock()

    # ── 1. Send message via /v1/view ────────────────────────────────
    r = await client.post(
        "/v1/view",
        json={"action": "send_message", "message": "run pwd"},
        timeout=10,
    )
    assert r.status_code == 200
    view = r.json()
    session_id = view["active_session"]["id"]

    # ── 2. Poll until tool_use appears in view data ──────────────────
    tool_use_found = False
    for _ in range(50):
        r = await client.post(
            "/v1/view",
            json={"action": "get_view", "session_id": session_id},
            timeout=10,
        )
        view = r.json()
        msgs = view.get("messages", [])

        for m in msgs:
            if m.get("type") == "tool_use" and m.get("tool_name") == "Bash":
                tool_use_found = True
                assert m["tool_input"]["command"] == "pwd"
                break
        if tool_use_found:
            break
        await asyncio.sleep(0.2)

    assert tool_use_found, (
        f"tool_use for Bash not found in ViewData messages: "
        f"{json.dumps([{'type': m['type'], 'tool': m.get('tool_name')} for m in msgs], indent=2)}"
    )

    # ── 3. Verify the tool_use message is in SQLite ─────────────────
    r = await client.post(
        "/v1/view",
        json={"action": "get_view", "session_id": session_id},
        timeout=10,
    )
    view = r.json()
    tool_msgs = [m for m in view["messages"] if m["type"] == "tool_use"]
    assert len(tool_msgs) >= 1, "Expected at least one tool_use message in DB"

    # ── 4. Verify pending action (permission) exists ─────────────────
    pending = view.get("pending_actions", [])
    assert len(pending) >= 1, "Expected a pending permission action"
    assert pending[0]["tool_name"] == "Bash"

    # ── 5. Verify session status reflects awaiting permission ────────
    assert view["active_session"]["permission_status"] == "awaiting_approval"
    assert view["ui_state"]["awaiting_approval"] is True


@pytest.mark.asyncio
async def test_tool_use_bubble_after_permission_granted(client):
    """After granting permission, tool_use + tool_result both appear in ViewData."""
    await reset_mock()

    # ── 1. Send message ─────────────────────────────────────────────
    r = await client.post(
        "/v1/view",
        json={"action": "send_message", "message": "run pwd"},
        timeout=10,
    )
    session_id = r.json()["active_session"]["id"]

    # ── 2. Wait for permission request ──────────────────────────────
    request_id = None
    for _ in range(50):
        r = await client.post(
            "/v1/view",
            json={"action": "get_view", "session_id": session_id},
            timeout=10,
        )
        pending = r.json().get("pending_actions", [])
        if pending:
            request_id = pending[0]["request_id"]
            break
        await asyncio.sleep(0.2)

    assert request_id, "Permission request never appeared"

    # ── 3. Approve the permission ───────────────────────────────────
    r = await client.post(
        "/v1/view",
        json={
            "action": "respond_permission",
            "session_id": session_id,
            "request_id": request_id,
            "approved": True,
        },
        timeout=10,
    )
    assert r.status_code == 200

    # ── 4. Poll until agent loop finishes ───────────────────────────
    for attempt in range(100):
        r = await client.post(
            "/v1/view",
            json={"action": "get_view", "session_id": session_id},
            timeout=10,
        )
        view = r.json()
        msgs = view.get("messages", [])
        status = view.get("active_session", {}).get("status", "unknown")
        has_tool_result = any(m["type"] == "tool_result" for m in msgs)
        has_final_text = any(
            m["type"] == "text" and m["role"] == "assistant" for m in msgs
        )
        if status == "idle":
            break
        await asyncio.sleep(0.3)

    # ── 5. Final assertions ─────────────────────────────────────────
    tool_uses = [m for m in msgs if m["type"] == "tool_use"]
    tool_results = [m for m in msgs if m["type"] == "tool_result"]
    assert len(tool_uses) >= 1, "tool_use message missing after completion"
    assert len(tool_results) >= 1, "tool_result message missing after completion"
    assert tool_results[0]["content"], "tool_result content is empty"
    assert view["active_session"]["status"] == "idle", (
        f"Expected idle but got {view['active_session']['status']}. "
        f"Messages: {json.dumps([{'type': m['type'], 'role': m['role']} for m in msgs], indent=2)}"
    )
    assert view["ui_state"]["awaiting_approval"] is False
