"""
Integration test: permission approval survives a simulated page refresh.

Prerequisites:
  - FastAPI app running at http://127.0.0.1:8787
  - Mock LLM server running at http://127.0.0.1:9001 (wired as ANTHROPIC_BASE_URL)

Flow:
  1. Reset mock LLM, POST /v1/sessions/stream with "run pwd"
  2. Read SSE events incrementally (stream never closes while permission is pending)
  3. Assert permission_request for Bash with command "pwd"
  4. DELETE all in-memory sessions (simulates browser refresh)
  5. POST approval to /v1/sessions/{id}/permissions/respond
  6. GET /v1/db/sessions/{id}/messages → verify tool executed and agent continued
"""

import asyncio
import json

import httpx
import pytest

BASE = "http://127.0.0.1:8787"
MOCK = "http://127.0.0.1:9001"
TIMEOUT = 60
STREAM_TIMEOUT = 5  # seconds to wait for each SSE chunk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _parse_view_event(line: str) -> dict | None:
    if line.startswith("data: "):
        try:
            return json.loads(line[6:])
        except json.JSONDecodeError:
            pass
    return None


async def stream_view_events(action: dict):
    """
    Send an action and then listen to the resulting SSE stream.
    """
    client = httpx.AsyncClient(timeout=httpx.Timeout(
        connect=10, read=STREAM_TIMEOUT, write=10, pool=10
    ))

    req = client.build_request("POST", f"{BASE}/v1/view", json=action)
    resp = await client.send(req, stream=True)

    assert resp.status_code == 200, f"view stream returned {resp.status_code}"

    events = []
    buf = ""
    try:
        async for raw_chunk in resp.aiter_lines():
            buf += raw_chunk + "\n"
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                ev = _parse_view_event(line.rstrip("\r"))
                if ev:
                    events.append(ev)
                    yield ev
                    if ev.get("type") == "done":
                        return
    except (httpx.ReadTimeout, httpx.RemoteProtocolError):
        pass
    finally:
        await resp.aclose()
        await client.aclose()


async def collect_view_events(action: dict):
    """Collect all ViewData events from a stream into a list."""
    events = []
    async for ev in stream_view_events(action):
        events.append(ev)

    sid = None
    for e in events:
        if e.get("active_session"):
            sid = e["active_session"]["id"]
            break
    return events, sid


async def get_view_data(client: httpx.AsyncClient, session_id: str):
    r = await client.post(f"{BASE}/v1/view", json={"action": "get_view", "session_id": session_id}, timeout=TIMEOUT)
    assert r.status_code == 200
    return r.json()


async def wait_for_messages(client: httpx.AsyncClient, session_id: str, predicate, label: str, attempts=50, delay=0.2):
    for _ in range(attempts):
        view_data = await get_view_data(client, session_id)
        msgs = view_data["messages"]
        if predicate(msgs):
            return msgs
        await asyncio.sleep(delay)
    pytest.fail(f"Timed out waiting for: {label}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_permission_survives_page_refresh():
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:

        # Reset mock LLM to turn 0 (Bash pwd tool_use)
        await c.post(f"{MOCK}/reset", timeout=TIMEOUT)

        # ── 1. Stream first message ──────────────────────────────────
        events, sid = await collect_view_events({"action": "send_message", "message": "run pwd"})
        assert sid, "No session_id returned"

        perms = [e for e in events if e.get("pending_actions")]
        assert perms, f"No pending actions in events: {[e.get('type') for e in events]}"

        # Get the first pending action
        first_view = next(e for e in events if e.get("active_session"))
        pending_action = first_view["pending_actions"][0]
        assert pending_action["tool_name"] == "Bash", f"Expected Bash, got {pending_action['tool_name']}"
        assert pending_action["tool_input"]["command"] == "pwd", (
            f"Expected command 'pwd', got {pending_action['tool_input'].get('command')}"
        )
        request_id = pending_action["request_id"]

        # ── 2. Simulate page refresh: drop all in-memory sessions ────
        # Use /v1/view with action delete_session for each
        view_data = await send_action(c, {"action": "get_view"})
        for s in view_data["sessions"]:
            await send_action(c, {"action": "delete_session", "session_id": s["id"]})

        # Verify sessions are empty
        view_data = await send_action(c, {"action": "get_view"})
        # Note: delete_session might not clear the active_session immediately in the return data
        # but we check the sessions list.
        assert len(view_data["sessions"]) == 0, "sessions should be empty after refresh"

        # Pending permission must survive in DB (check via get_view)
        view_data = await send_action(c, {"action": "get_view", "session_id": sid})
        assert view_data["active_session"]["permission_status"] == "awaiting_approval", (
            "session should be awaiting approval after refresh"
        )
        assert any(p["request_id"] == request_id for p in view_data["pending_actions"]), (
            "pending permission not found in view data after refresh"
        )

        # ── 3. Approve permission (reconnects session from DB) ───────
        r = await c.post(
            f"{BASE}/v1/view",
            json={"action": "respond_permission", "session_id": sid, "request_id": request_id, "approved": True, "always": False},
            timeout=TIMEOUT,
        )
        assert r.status_code == 200, f"approve failed: {r.status_code} {r.text}"

        # ── 4. Wait for background agent loop to finish ──────────────
        msgs = await wait_for_messages(
            c, sid,
            lambda ms: (
                any(m["role"] == "tool" and m["type"] == "tool_result" for m in ms)
                and any(m["role"] == "assistant" and m["type"] == "text" for m in ms)
            ),
            "tool_result + final text",
        )

        # ── 5. Assertions ────────────────────────────────────────────
        tool_msgs = [m for m in msgs if m["role"] == "tool" and m["type"] == "tool_result"]
        assert tool_msgs, "No tool_result message"
        assert tool_msgs[0]["content"], "Tool result is empty"

        # Pending permissions cleared
        view_data = await send_action(c, {"action": "get_view", "session_id": sid})
        assert len(view_data["pending_actions"]) == 0, "pending actions not cleared"

        # Session returned to idle
        assert view_data["active_session"]["status"] == "idle", f"status is {view_data['active_session']['status']}, expected idle"


@pytest.mark.asyncio
async def test_deny_stops_agent():
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        # Reset mock LLM to turn 0 (Bash pwd tool_use)
        await c.post(f"{MOCK}/reset", timeout=TIMEOUT)

        events, sid = await collect_view_events({"action": "send_message", "message": "run pwd"})
        assert sid

        first_view = next(e for e in events if e.get("active_session"))
        request_id = first_view["pending_actions"][0]["request_id"]

        r = await c.post(
            f"{BASE}/v1/view",
            json={"action": "respond_permission", "session_id": sid, "request_id": request_id, "approved": False},
            timeout=TIMEOUT,
        )
        assert r.status_code == 200

        msgs = await wait_for_messages(
            c, sid,
            lambda ms: any(m["role"] == "tool" and "denied" in (m.get("content") or "").lower() for m in ms),
            "permission denied message",
        )

        denied = [m for m in msgs if "denied" in (m.get("content") or "").lower()]
        assert denied, "No 'Permission denied' in messages"
