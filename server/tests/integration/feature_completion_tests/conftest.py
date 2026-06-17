"""Shared fixtures for feature completion integration tests."""

import asyncio
import json
import uuid
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
# Keyword → response mapping (mirrors mock_llm_server.py)
# ---------------------------------------------------------------------------

def _keyword_response(prompt_lower: str) -> list[dict] | None:
    """Return a two-turn response list if the prompt matches a keyword."""
    if "run pwd" in prompt_lower:
        return [
            {
                "content": [
                    {"type": "text", "text": "I'll run pwd for you."},
                    {"type": "tool_use", "id": f"toolu_{uuid.uuid4().hex[:8]}",
                     "name": "Bash", "input": {"command": "pwd"}},
                ],
                "stop_reason": "tool_use",
            },
            {
                "content": [{"type": "text", "text": "The current directory is shown above."}],
                "stop_reason": "end_turn",
            },
        ]
    if "run ls" in prompt_lower:
        return [
            {
                "content": [
                    {"type": "text", "text": "I'll list the directory."},
                    {"type": "tool_use", "id": f"toolu_{uuid.uuid4().hex[:8]}",
                     "name": "Bash", "input": {"command": "ls"}},
                ],
                "stop_reason": "tool_use",
            },
            {
                "content": [{"type": "text", "text": "Here are the files."}],
                "stop_reason": "end_turn",
            },
        ]
    if "echo" in prompt_lower:
        return [
            {
                "content": [
                    {"type": "text", "text": "Running echo."},
                    {"type": "tool_use", "id": f"toolu_{uuid.uuid4().hex[:8]}",
                     "name": "Bash", "input": {"command": "echo hello"}},
                ],
                "stop_reason": "tool_use",
            },
            {
                "content": [{"type": "text", "text": "Echo completed."}],
                "stop_reason": "end_turn",
            },
        ]
    if "delete" in prompt_lower or "rm " in prompt_lower:
        return [
            {
                "content": [
                    {"type": "text", "text": "I'll remove that."},
                    {"type": "tool_use", "id": f"toolu_{uuid.uuid4().hex[:8]}",
                     "name": "Bash", "input": {"command": "rm -rf /tmp/test"}},
                ],
                "stop_reason": "tool_use",
            },
            {
                "content": [{"type": "text", "text": "Deletion complete."}],
                "stop_reason": "end_turn",
            },
        ]
    if "edit" in prompt_lower:
        return [
            {
                "content": [
                    {"type": "text", "text": "I'll make that edit."},
                    {"type": "tool_use", "id": f"toolu_{uuid.uuid4().hex[:8]}",
                     "name": "Bash", "input": {"command": "echo edited"}},
                ],
                "stop_reason": "tool_use",
            },
            {
                "content": [{"type": "text", "text": "Edit applied."}],
                "stop_reason": "end_turn",
            },
        ]
    return None


def _extract_prompt(messages: list[dict]) -> str:
    """Pull plain-text content from Anthropic messages list."""
    parts = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_result":
                        parts.append(str(block.get("content", "")))
    return " ".join(parts).lower()


# ---------------------------------------------------------------------------
# Mock LLM Client
# ---------------------------------------------------------------------------


class MockLLMClient:
    """Deterministic mock LLM that returns configurable responses.

    Supports two modes:
    1. Explicit sequence — ``set_sequence([...])`` overrides everything.
    2. Keyword routing — if no sequence is set, the prompt is inspected
       for keywords ("run pwd", "echo", etc.) and the matching canned
       response is returned.  Each keyword fires at most once; subsequent
       calls return a plain-text终结 response so the agent loop exits.
    """

    def __init__(self, options=None):
        self.options = options
        self._queue = asyncio.Queue()
        self._sequence: list[dict] = []
        self._seq_index: int = 0
        self._kw_fired: set[str] = set()

    def set_sequence(self, sequence):
        self._sequence = sequence
        self._seq_index = 0

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    def _pick_response(self, messages: list[dict]) -> dict:
        """Choose a response: keyword match > explicit sequence > default."""
        prompt = _extract_prompt(messages)

        # keyword routing — each keyword fires at most once
        kw = _keyword_response(prompt)
        if kw:
            # Find which keyword matched
            matched_kw = None
            for kw_str in ("run pwd", "run ls", "echo", "delete", "rm ", "edit"):
                if kw_str in prompt:
                    matched_kw = kw_str
                    break

            if matched_kw and matched_kw not in self._kw_fired:
                self._kw_fired.add(matched_kw)
                resp = dict(kw[0])
                for block in resp.get("content", []):
                    if block.get("type") == "tool_use":
                        block["id"] = f"toolu_{uuid.uuid4().hex[:8]}"
                return resp

            # Keyword already fired — return终结 text so the loop ends
            return {
                "content": [{"type": "text", "text": "Done."}],
                "stop_reason": "end_turn",
            }

        # explicit sequence
        if self._sequence:
            idx = min(self._seq_index, len(self._sequence) - 1)
            resp = dict(self._sequence[idx])
            self._seq_index += 1
            for block in resp.get("content", []):
                if block.get("type") == "tool_use":
                    block["id"] = f"toolu_{uuid.uuid4().hex[:8]}"
            return resp

        # default: plain text
        return {
            "content": [{"type": "text", "text": "Mock response"}],
            "stop_reason": "end_turn",
        }

    async def query(self, content):
        prompt_text = ""
        if hasattr(content, "__aiter__"):
            async for chunk in content:
                if isinstance(chunk, dict) and "content" in chunk:
                    prompt_text += chunk["content"]
        else:
            prompt_text = str(content)

        messages = [{"role": "user", "content": prompt_text}]
        resp = self._pick_response(messages)

        # Emit events the old way (for legacy callers)
        for block in resp.get("content", []):
            if block.get("type") == "tool_use":
                await self._queue.put({
                    "type": "content_block_start",
                    "content_block": {
                        "type": "tool_use",
                        "id": block["id"],
                        "name": block["name"],
                        "input": block["input"],
                    },
                })
                await asyncio.sleep(0.005)

                class Ctx:
                    display_name = block["name"]
                    description = f"Run {block['name']}"
                    title = f"Run {block['name']}"

                if self.options and getattr(self.options, "can_use_tool", None):
                    try:
                        perm_res = await self.options.can_use_tool(
                            block["name"], block["input"], Ctx()
                        )
                        is_allow = isinstance(perm_res, PermissionResultAllow) or (
                            type(perm_res).__name__ == "PermissionResultAllow"
                        )
                        if is_allow:
                            await self._queue.put({
                                "type": "tool_result",
                                "tool_id": block["id"],
                                "output": f"mock output for {block['name']}",
                            })
                        else:
                            await self._queue.put({
                                "type": "tool_error",
                                "tool_id": block["id"],
                                "error": "Permission denied by user",
                            })
                    except Exception as e:
                        await self._queue.put({
                            "type": "tool_error",
                            "tool_id": block["id"],
                            "error": str(e),
                        })
                else:
                    await self._queue.put({
                        "type": "tool_result",
                        "tool_id": block["id"],
                        "output": f"mock output for {block['name']}",
                    })

                await asyncio.sleep(0.005)

        for block in resp.get("content", []):
            if block.get("type") == "text":
                await self._queue.put({"type": "text", "data": block["text"]})

        await self._queue.put({"type": "message_stop"})

    async def chat_completion(self, messages, system=None, tools=None, stream=False):
        """Chat completion interface matching CustomLLMWrapper.

        Called once per LLM turn.  Returns the single response dict as an
        async generator (one yield).
        """
        resp = self._pick_response(messages)
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
