"""
Integration test: permission approval survives a simulated page refresh.

Uses ASGI transport (no running server required) and the conftest mock LLM server.
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


TIMEOUT = 60


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
    await asyncio.sleep(0.5)
    await db.close_db()


@pytest.fixture(autouse=True)
def _set_mock_env(mock_llm_server):
    os.environ["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{mock_llm_server}"
    os.environ["ANTHROPIC_MODEL"] = "mock-model"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def send_action(client: httpx.AsyncClient, action: dict):
    r = await client.post("/v1/view", json=action, timeout=TIMEOUT)
    assert r.status_code == 200
    return r.json()


async def get_view_data(client: httpx.AsyncClient, session_id: str):
    return await send_action(client, {"action": "get_view", "session_id": session_id})


async def wait_for_condition(client, session_id, predicate, label, attempts=50, delay=0.2):
    for _ in range(attempts):
        view_data = await get_view_data(client, session_id)
        if predicate(view_data):
            return view_data
        await asyncio.sleep(delay)
    pytest.fail(f"Timed out waiting for: {label}")


async def reset_mock():
    async with httpx.AsyncClient() as c:
        await c.post(f"http://127.0.0.1:{os.environ.get('MOCK_PORT', 9002)}/reset", timeout=10)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_permission_survives_page_refresh(client, mock_llm_server):
    mock_base = f"http://127.0.0.1:{mock_llm_server}"
    async with httpx.AsyncClient() as mc:
        await mc.post(f"{mock_base}/reset", timeout=10)

    # ── 1. Send message ─────────────────────────────────────────────
    r = await client.post(
        "/v1/view",
        json={"action": "send_message", "message": "run pwd"},
        timeout=TIMEOUT,
    )
    assert r.status_code == 200
    session_id = r.json()["active_session"]["id"]

    # ── 2. Wait for permission request ──────────────────────────────
    request_id = None
    for _ in range(50):
        view = await get_view_data(client, session_id)
        pending = view.get("pending_actions", [])
        if pending:
            request_id = pending[0]["request_id"]
            assert pending[0]["tool_name"] == "Bash"
            break
        await asyncio.sleep(0.2)

    assert request_id, "Permission request never appeared"

    # ── 3. Simulate page refresh: drop in-memory session ─────────────
    import app.main as _main
    await _main.manager.close(session_id)

    # ── 4. Pending permission must survive ──────────────────────────
    # Reconnect the session from DB
    await send_action(client, {"action": "switch_session", "session_id": session_id})
    view = await get_view_data(client, session_id)
    assert view["active_session"]["permission_status"] == "awaiting_approval"
    assert any(p["request_id"] == request_id for p in view["pending_actions"])

    # ── 5. Approve permission ──────────────────────────────────────
    r = await client.post(
        "/v1/view",
        json={"action": "respond_permission", "session_id": session_id, "request_id": request_id, "approved": True},
        timeout=TIMEOUT,
    )
    assert r.status_code == 200

    # ── 6. Wait for agent loop to finish ───────────────────────────
    view = await wait_for_condition(
        client, session_id,
        lambda v: v["active_session"]["status"] == "idle",
        "session idle after approval",
    )

    msgs = view["messages"]
    tool_results = [m for m in msgs if m["type"] == "tool_result"]
    assert tool_results, "No tool_result message"
    assert tool_results[0]["content"], "Tool result is empty"

    assert len(view["pending_actions"]) == 0, "pending actions not cleared"
    assert view["active_session"]["status"] == "idle"


@pytest.mark.asyncio
async def test_deny_stops_agent(client, mock_llm_server):
    mock_base = f"http://127.0.0.1:{mock_llm_server}"
    async with httpx.AsyncClient() as mc:
        await mc.post(f"{mock_base}/reset", timeout=10)

    r = await client.post(
        "/v1/view",
        json={"action": "send_message", "message": "run pwd"},
        timeout=TIMEOUT,
    )
    session_id = r.json()["active_session"]["id"]

    request_id = None
    for _ in range(50):
        view = await get_view_data(client, session_id)
        pending = view.get("pending_actions", [])
        if pending:
            request_id = pending[0]["request_id"]
            break
        await asyncio.sleep(0.2)

    assert request_id, "Permission request never appeared"

    r = await client.post(
        "/v1/view",
        json={"action": "respond_permission", "session_id": session_id, "request_id": request_id, "approved": False},
        timeout=TIMEOUT,
    )
    assert r.status_code == 200

    view = await wait_for_condition(
        client, session_id,
        lambda v: v["active_session"]["status"] == "idle",
        "session idle after deny",
    )

    msgs = view["messages"]
    denied = [m for m in msgs if "denied" in (m.get("content") or "").lower()]
    assert denied, "No 'Permission denied' in messages"
