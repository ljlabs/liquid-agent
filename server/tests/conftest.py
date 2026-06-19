"""Shared fixtures for all tests.

Provides:
- InMemoryDB: dict-backed replacement for app.database
- mock_database (autouse): patches db module references in app.main and app.sessions
- mock_system_prompt (autouse): prevents Session.__init__ from reading system_prompt.md
- mock_execute_tool (opt-in): returns canned ToolResult instead of running real tools
- isolate_env (autouse): sets env vars via monkeypatch to prevent leakage
- mock_llm_server (session-scoped): real mock LLM server for integration tests
"""

import os
import socket
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import uvicorn


# ---------------------------------------------------------------------------
# InMemoryDB — dict-backed replacement for app.database
# ---------------------------------------------------------------------------

class InMemoryDB:
    """Stores sessions, messages, and permissions in plain Python dicts.

    Drop-in replacement for the app.database module's async functions.
    """

    def __init__(self):
        self.sessions: dict[str, dict] = {}
        self.messages: list[dict] = []
        self.pending: dict[tuple[str, str], dict] = {}
        self.permissions: list[dict] = []

    async def create_session(self, *, session_id, title="New Session", cwd="",
                             model="default", permission_mode="default",
                             tool_rules=None):
        self.sessions[session_id] = {
            "id": session_id, "title": title, "cwd": cwd, "model": model,
            "permission_mode": permission_mode, "tool_rules": tool_rules or "",
            "status": "idle", "created_at": 0.0, "updated_at": 0.0,
        }
        return self.sessions[session_id]

    async def get_session(self, session_id):
        return self.sessions.get(session_id)

    async def update_session(self, session_id, **fields):
        if session_id in self.sessions:
            self.sessions[session_id].update(fields)

    async def list_sessions(self, limit=50):
        return list(self.sessions.values())[:limit]

    async def delete_session(self, session_id):
        if session_id in self.sessions:
            del self.sessions[session_id]
            self.messages = [m for m in self.messages if m["session_id"] != session_id]
            return True
        return False

    async def add_message(self, *, session_id, role, type="text", content="",
                          tool_name=None, tool_id=None, tool_input=None,
                          pending_request_id=None):
        self.messages.append({
            "id": len(self.messages) + 1, "session_id": session_id,
            "role": role, "type": type, "content": content,
            "tool_name": tool_name, "tool_id": tool_id,
            "tool_input": tool_input, "pending_request_id": pending_request_id,
            "created_at": 0.0,
        })
        return len(self.messages)

    async def get_messages(self, session_id):
        return [m for m in self.messages if m["session_id"] == session_id]

    async def get_message_count(self, session_id):
        return len([m for m in self.messages if m["session_id"] == session_id])

    async def store_pending_permission(self, *, session_id, request_id,
                                       tool_name, tool_id=None, tool_input=None):
        self.pending[(session_id, request_id)] = {
            "session_id": session_id, "request_id": request_id,
            "tool_name": tool_name, "tool_id": tool_id, "tool_input": tool_input,
        }

    async def remove_pending_permission(self, session_id, request_id):
        self.pending.pop((session_id, request_id), None)

    async def get_pending_permissions(self, session_id):
        return [v for (sid, _), v in self.pending.items() if sid == session_id]

    async def log_permission(self, *, session_id, request_id, tool_name,
                             tool_input=None, approved=False, always=False):
        self.permissions.append({
            "session_id": session_id, "request_id": request_id,
            "tool_name": tool_name, "tool_input": tool_input,
            "approved": approved, "always": always,
        })


# ---------------------------------------------------------------------------
# Autouse fixtures — apply to every test automatically
# ---------------------------------------------------------------------------

def _is_integration_test(request) -> bool:
    """Return True if the test is an integration test.

    Integration tests live under tests/integration/ or are known integration
    test files in tests/ that depend on the mock LLM server.
    """
    fspath = str(request.fspath)
    if "integration" in fspath:
        return True
    integration_files = [
        "test_integration_permission.py",
        "test_tool_use_feature.py",
        "test_permission_refresh.py",
    ]
    return any(f in fspath for f in integration_files)


@pytest.fixture(autouse=True)
def mock_database(request):
    """Replace app.database with InMemoryDB for unit tests only.

    Integration tests (under tests/integration/) are skipped — they use
    their own database fixtures.
    """
    if _is_integration_test(request):
        yield
        return

    db = InMemoryDB()
    mock_db = MagicMock()
    for method_name in ["create_session", "get_session", "update_session",
                        "list_sessions", "delete_session", "add_message",
                        "get_messages", "get_message_count",
                        "store_pending_permission", "remove_pending_permission",
                        "get_pending_permissions", "log_permission"]:
        setattr(mock_db, method_name, getattr(db, method_name))

    with patch("app.main.db", mock_db), \
         patch("app.sessions.db", mock_db):
        yield db


@pytest.fixture(autouse=True)
def mock_system_prompt(request):
    """Prevent Session.__init__ from reading system_prompt.md (unit tests only)."""
    if _is_integration_test(request):
        yield
        return
    with patch("app.sessions.Session._load_system_prompt", return_value=""):
        yield


@pytest.fixture(autouse=True)
def isolate_env(request, monkeypatch):
    """Set env vars via monkeypatch so they are automatically restored."""
    monkeypatch.setenv("ANTHROPIC_MODEL", "mock-model")
    if _is_integration_test(request):
        yield
        return
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-no-key-needed")
    yield


# ---------------------------------------------------------------------------
# Opt-in fixtures — request explicitly when needed
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_execute_tool():
    """Mock execute_tool to return a canned ToolResult.

    Use in tests that approve permissions and need the agent loop to continue
    without running real subprocesses.
    """
    from app.tools import ToolResult
    with patch("app.sessions.execute_tool", new_callable=AsyncMock) as mock:
        mock.return_value = ToolResult(output="mock tool output")
        yield mock


# ---------------------------------------------------------------------------
# Session-scoped mock LLM server — for integration tests in tests/
# ---------------------------------------------------------------------------

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session", autouse=True)
def mock_llm_server():
    """Start the mock LLM server in a background thread for the test session.

    Used by integration tests (test_tool_use_feature, test_permission_refresh,
    test_integration_permission) that need a real HTTP endpoint. Unit tests
    mock the LLM directly and do not use this server.
    """
    from tests.mock_llm_server import app as mock_app

    port = _free_port()
    config = uvicorn.Config(
        mock_app, host="127.0.0.1", port=port, log_level="error"
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.1)

    yield port

    server.should_exit = True
    thread.join(timeout=5)
