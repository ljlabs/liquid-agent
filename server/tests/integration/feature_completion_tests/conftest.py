"""Shared fixtures for feature completion integration tests."""

import asyncio
import json
import tempfile
import shutil
from pathlib import Path
from unittest import mock

import pytest
import httpx

from app.main import app
from app.sessions import Session, SessionManager, PermissionResultAllow, PermissionResultDeny
from app.view_data import ViewDataGenerator
from app import database as db


# ---------------------------------------------------------------------------
# Mock LLM Client
# ---------------------------------------------------------------------------


class MockLLMClient:
    """Deterministic mock LLM that returns configurable responses."""

    def __init__(self, options=None):
        self.options = options
        self._queue = asyncio.Queue()
        self._sequence = []
        self._seq_index = 0

    def set_sequence(self, sequence):
        self._sequence = sequence
        self._seq_index = 0

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def query(self, content):
        prompt_text = ""
        if hasattr(content, "__aiter__"):
            async for chunk in content:
                if isinstance(chunk, dict) and "content" in chunk:
                    prompt_text += chunk["content"]
        else:
            prompt_text = str(content)

        # Pick response from sequence
        if self._sequence:
            idx = min(self._seq_index, len(self._sequence) - 1)
            resp = self._sequence[idx]
            self._seq_index += 1
        else:
            # Default: text only
            resp = {
                "content": [{"type": "text", "text": f"Mock response to: {prompt_text[:50]}"}],
                "stop_reason": "end_turn",
            }

        # Handle tool_use blocks — check permission via callback
        for block in resp.get("content", []):
            if block.get("type") == "tool_use":
                tool_name = block["name"]
                tool_input = block["input"]
                tool_id = block["id"]

                await self._queue.put({
                    "type": "content_block_start",
                    "content_block": {
                        "type": "tool_use",
                        "id": tool_id,
                        "name": tool_name,
                        "input": tool_input,
                    },
                })
                await asyncio.sleep(0.005)

                class Ctx:
                    display_name = tool_name
                    description = f"Run {tool_name}"
                    title = f"Run {tool_name}"

                if self.options and getattr(self.options, "can_use_tool", None):
                    try:
                        perm_res = await self.options.can_use_tool(tool_name, tool_input, Ctx())
                        is_allow = isinstance(perm_res, PermissionResultAllow) or (
                            type(perm_res).__name__ == "PermissionResultAllow"
                        )
                        if is_allow:
                            await self._queue.put({
                                "type": "tool_result",
                                "tool_id": tool_id,
                                "output": f"mock output for {tool_name}",
                            })
                        else:
                            await self._queue.put({
                                "type": "tool_error",
                                "tool_id": tool_id,
                                "error": "Permission denied by user",
                            })
                    except Exception as e:
                        await self._queue.put({
                            "type": "tool_error",
                            "tool_id": tool_id,
                            "error": str(e),
                        })
                else:
                    # No permission callback — auto-allow
                    await self._queue.put({
                        "type": "tool_result",
                        "tool_id": tool_id,
                        "output": f"mock output for {tool_name}",
                    })

                await asyncio.sleep(0.005)

        # Emit text blocks
        for block in resp.get("content", []):
            if block.get("type") == "text":
                await self._queue.put({"type": "text", "data": block["text"]})

        await self._queue.put({"type": "message_stop"})

    async def chat_completion(self, messages, system=None, tools=None, stream=False):
        """Chat completion interface matching CustomLLMWrapper."""
        # Pick response from sequence
        if self._sequence:
            idx = min(self._seq_index, len(self._sequence) - 1)
            resp = self._sequence[idx]
            self._seq_index += 1
        else:
            resp = {
                "content": [{"type": "text", "text": "Mock response"}],
                "stop_reason": "end_turn",
            }

        # Inject unique tool_use IDs
        for block in resp.get("content", []):
            if block.get("type") == "tool_use" and not block.get("id", "").startswith("toolu_"):
                block["id"] = f"toolu_{uuid.uuid4().hex[:8]}"

        # Return the response as a dict (the session expects this)
        yield resp

    async def receive_response(self):
        while True:
            ev = await self._queue.get()
            yield ev
            if ev.get("type") == "message_stop":
                break


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolate_db(tmp_path):
    """Use a fresh temp database for each test."""
    tmp_db = tmp_path / "test.db"
    old_db_path = db.DB_PATH
    db.DB_PATH = tmp_db
    db._db = None
    yield tmp_db
    # Cleanup is handled by tmp_path being cleaned up by pytest
    db._db = None
    db.DB_PATH = old_db_path


@pytest.fixture
def manager():
    return SessionManager()


@pytest.fixture
def view_gen(manager):
    return ViewDataGenerator(manager, db)


@pytest.fixture
async def client(manager, view_gen):
    """Async HTTP client with fresh manager and view generator."""
    import app.main as main
    main.manager = manager
    main.view_generator = view_gen

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    await manager.close_all()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def create_session(client, model="mock-model"):
    """Create a session via the view endpoint and return (client, session_id)."""
    r = await client.post("/v1/view", json={"action": "create_session", "model": model})
    assert r.status_code == 200
    data = r.json()
    return data["active_session"]["id"]


async def get_view(client, session_id=None):
    """Get ViewData snapshot."""
    payload = {"action": "get_view"}
    if session_id:
        payload["session_id"] = session_id
    r = await client.post("/v1/view", json=payload)
    assert r.status_code == 200
    return r.json()


async def send_message(client, session_id, message):
    """Send a message and return the initial ViewData."""
    r = await client.post("/v1/view", json={
        "action": "send_message",
        "session_id": session_id,
        "message": message,
    })
    assert r.status_code == 200
    return r.json()


async def wait_for_session_idle(client, session_id, attempts=50, delay=0.1):
    """Poll get_view until session is idle."""
    for _ in range(attempts):
        view = await get_view(client, session_id)
        if view.get("active_session", {}).get("status") == "idle":
            return view
        await asyncio.sleep(delay)
    # Return whatever we have — test will fail with useful info
    return await get_view(client, session_id)
