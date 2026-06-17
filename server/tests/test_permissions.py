import pytest
import tempfile
import shutil
import asyncio
import json
import httpx
from pathlib import Path
from unittest import mock
from app.sessions import (
    Session,
    SessionManager,
    PermissionResultAllow,
    PermissionResultDeny,
    DEFAULT_TOOL_RULES,
    DEFAULT_AUTO_ALLOW_TOOLS,
)
from app import database as db
from app.main import app


class MockClaudeSDKClient:
    def __init__(self, options=None):
        self.options = options
        self._queue = asyncio.Queue()

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def query(self, content):
        prompt_text = ""
        # FIX: content is now an AsyncIterable
        if hasattr(content, "__aiter__"):
            async for chunk in content:
                if isinstance(chunk, dict) and "content" in chunk:
                    prompt_text += chunk["content"]
        else:
            # Fallback for old tests that might still pass strings
            prompt_text = str(content)

        if "mock_tool:" in prompt_text:
            tool_name = prompt_text.split(":")[1].strip()
            tool_input = {"command": "echo hello"}
            tool_id = "mock_tool_id"

            await self._queue.put({
                "type": "content_block_start",
                "content_block": {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": tool_name,
                    "input": tool_input
                }
            })
            await asyncio.sleep(0.01)

            class MockContext:
                display_name = tool_name
                description = f"Mock description for {tool_name}"
                title = f"Run {tool_name}"
            context = MockContext()

            if self.options and getattr(self.options, "can_use_tool", None):
                try:
                    perm_res = await self.options.can_use_tool(tool_name, tool_input, context)
                    is_allow = (
                        isinstance(perm_res, PermissionResultAllow)
                        or type(perm_res).__name__ == "PermissionResultAllow"
                    )
                    if is_allow:
                        await self._queue.put({
                            "type": "tool_result",
                            "tool_id": tool_id,
                            "output": "mock tool output success"
                        })
                    else:
                        msg = getattr(perm_res, "message", "Denied by user")
                        await self._queue.put({
                            "type": "tool_error",
                            "tool_id": tool_id,
                            "error": f"Error: {msg}"
                        })
                except Exception as e:
                    await self._queue.put({
                        "type": "tool_error",
                        "tool_id": tool_id,
                        "error": str(e)
                    })
            await asyncio.sleep(0.01)
            await self._queue.put({"type": "message_stop"})

    async def receive_response(self):
        while True:
            ev = await self._queue.get()
            yield ev
            if ev.get("type") == "message_stop":
                break


@pytest.fixture
async def temp_db():
    tmpdir = tempfile.mkdtemp()
    tmp = Path(tmpdir) / "test_perm.db"
    old_db_path = db.DB_PATH
    db.DB_PATH = tmp
    db._db = None
    yield tmp
    await db.close_db()
    db.DB_PATH = old_db_path
    db._db = None
    shutil.rmtree(tmpdir, ignore_errors=True)


# ------------------------------------------------------------------
# Default tool rules
# ------------------------------------------------------------------


def test_default_tool_rules_defined():
    """DEFAULT_TOOL_RULES should contain the canonical tool list."""
    assert "Bash" in DEFAULT_TOOL_RULES
    assert DEFAULT_TOOL_RULES["Bash"] == "ask"
    assert DEFAULT_TOOL_RULES["Read"] == "allow"
    assert DEFAULT_TOOL_RULES["Edit"] == "ask"
    assert DEFAULT_TOOL_RULES["Write"] == "ask"
    assert DEFAULT_TOOL_RULES["WebFetch"] == "allow"
    assert DEFAULT_TOOL_RULES["Grep"] == "allow"


@pytest.mark.asyncio
async def test_session_seeded_with_default_rules():
    """A fresh Session should have _tool_rules seeded from DEFAULT_TOOL_RULES."""
    session = Session(session_id="test_defaults", cwd="/tmp")
    for name, rule in DEFAULT_TOOL_RULES.items():
        assert session._tool_rules[name.lower()] == rule, f"{name} should default to {rule}"


@pytest.mark.asyncio
async def test_session_get_tool_rules():
    """get_tool_rules returns a dict keyed by canonical name with current rules."""
    session = Session(session_id="test_get_rules", cwd="/tmp")
    rules = session.get_tool_rules()
    assert set(rules.keys()) == set(DEFAULT_TOOL_RULES.keys())
    assert rules["Bash"] == "ask"
    assert rules["Read"] == "allow"


@pytest.mark.asyncio
async def test_set_tool_rule_updates_internal_state():
    """Setting Bash to 'allow' updates internal _tool_rules."""
    session = Session(session_id="test_rule_update", cwd="/tmp")

    # Bash defaults to 'ask'
    assert session._tool_rules["bash"] == "ask"

    # Allow bash
    session.set_tool_rule("Bash", "allow")
    assert session._tool_rules["bash"] == "allow"

    # Deny bash
    session.set_tool_rule("Bash", "deny")
    assert session._tool_rules["bash"] == "deny"


# ------------------------------------------------------------------
# _can_use_tool enforcement
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_can_use_tool_default_ask_triggers_permission():
    """Bash defaults to 'ask' -- _can_use_tool should emit a permission request."""
    session = Session(session_id="test_ask", cwd="/tmp")

    class Ctx:
        display_name = "Bash"
        description = "Run a shell command"
        title = "Run Bash"

    # Start the permission call in a task so we can check side effects
    task = asyncio.create_task(session._can_use_tool("Bash", {"command": "ls"}, Ctx()))
    await asyncio.sleep(0.05)

    # Should have a pending permission
    assert len(session._pending_permissions) == 1

    # Resolve it
    req_id = list(session._pending_permissions.keys())[0]
    session.resolve_permission(req_id, approved=False)
    result = await task
    assert type(result).__name__ == "PermissionResultDeny"


@pytest.mark.asyncio
async def test_can_use_tool_allow_auto_approves():
    """Setting Bash to 'allow' should skip the permission prompt."""
    session = Session(session_id="test_auto_allow", cwd="/tmp")
    session.set_tool_rule("Bash", "allow")

    res = await session._can_use_tool("Bash", {"command": "ls"}, None)
    assert isinstance(res, PermissionResultAllow) or type(res).__name__ == "PermissionResultAllow"
    assert len(session._pending_permissions) == 0


@pytest.mark.asyncio
async def test_can_use_tool_deny_blocks():
    """Setting Bash to 'deny' should immediately deny."""
    session = Session(session_id="test_deny", cwd="/tmp")
    session.set_tool_rule("Bash", "deny")

    res = await session._can_use_tool("Bash", {"command": "ls"}, None)
    assert isinstance(res, PermissionResultDeny) or type(res).__name__ == "PermissionResultDeny"
    assert len(session._pending_permissions) == 0


@pytest.mark.asyncio
async def test_can_use_tool_read_auto_allows():
    """Read defaults to 'allow' in DEFAULT_TOOL_RULES -- should auto-allow."""
    session = Session(session_id="test_read", cwd="/tmp")
    res = await session._can_use_tool("Read", {"path": "/tmp/foo"}, None)
    assert isinstance(res, PermissionResultAllow) or type(res).__name__ == "PermissionResultAllow"
    assert len(session._pending_permissions) == 0


@pytest.mark.asyncio
async def test_can_use_tool_ask_overrides_auto_allow():
    """Setting Read to 'ask' should trigger a permission prompt even though
    Read is in DEFAULT_AUTO_ALLOW_TOOLS."""
    session = Session(session_id="test_ask_override", cwd="/tmp")
    session.set_tool_rule("Read", "ask")

    class Ctx:
        display_name = "Read"
        description = "Read a file"
        title = "Read file"

    task = asyncio.create_task(session._can_use_tool("Read", {"path": "/tmp/foo"}, Ctx()))
    await asyncio.sleep(0.05)

    assert len(session._pending_permissions) == 1
    req_id = list(session._pending_permissions.keys())[0]
    session.resolve_permission(req_id, approved=True)
    result = await task
    assert isinstance(result, PermissionResultAllow) or type(result).__name__ == "PermissionResultAllow"


# ------------------------------------------------------------------
# Case-insensitive tool rules
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_insensitive_tool_rules():
    """Tool rules are stored lowercase, but lookups work with any case."""
    session = Session(session_id="test_case", cwd="/tmp")

    # Set rule with capitalized name
    session.set_tool_rule("Bash", "allow")
    assert session._tool_rules.get("bash") == "allow"

    res = await session._can_use_tool("bash", {}, None)
    assert isinstance(res, PermissionResultAllow) or type(res).__name__ == "PermissionResultAllow"

    # Set rule with lowercase name
    session.set_tool_rule("edit", "deny")
    assert session._tool_rules.get("edit") == "deny"

    res2 = await session._can_use_tool("Edit", {}, None)
    assert isinstance(res2, PermissionResultDeny) or type(res2).__name__ == "PermissionResultDeny"


# ------------------------------------------------------------------
# Mock tool permission request flow
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_tool_permission_request(temp_db):
    """Query with a simulated tool call creates a pending permission and blocks."""
    with mock.patch("app.sessions.ClaudeSDKClient", MockClaudeSDKClient), \
         mock.patch("app.sessions.IS_MOCK", True):

        session = Session(session_id="test_mock_tool", cwd="/tmp")
        await session.connect()

        events = []
        async def collect():
            async for ev in session.run_turn("mock_tool: Bash"):
                events.append(ev)
        
        collect_task = asyncio.create_task(collect())
        
        # Wait for it to hit the permission request
        for _ in range(20):
            await asyncio.sleep(0.05)
            if len(session._pending_permissions) == 1:
                break
        
        assert len(session._pending_permissions) == 1
        req_id = list(session._pending_permissions.keys())[0]
        
        resolved = session.resolve_permission(req_id, approved=True)
        assert resolved is True
        
        await collect_task
        
        event_types = [e["type"] for e in events]
        assert "permission_request" in event_types
        assert "tool_use" in event_types
        assert "tool_result" in event_types

        await session.close()


@pytest.mark.asyncio
async def test_mock_tool_deny_prevents_execution(temp_db):
    """If the user denies a tool, the mock should emit tool_error, not tool_result."""
    with mock.patch("app.sessions.ClaudeSDKClient", MockClaudeSDKClient), \
         mock.patch("app.sessions.IS_MOCK", True):

        session = Session(session_id="test_mock_deny", cwd="/tmp")
        await session.connect()

        events = []
        async def collect():
            async for ev in session.run_turn("mock_tool: Bash"):
                events.append(ev)

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.15)

        assert len(session._pending_permissions) == 1
        req_id = list(session._pending_permissions.keys())[0]

        session.resolve_permission(req_id, approved=False, deny_message="User said no")
        await asyncio.sleep(0.15)
        await task

        types = [e["type"] for e in events]
        assert "permission_request" in types
        assert "tool_result" not in types
        # Denied tools should produce a tool_error from the mock
        assert "tool_error" in types

        await session.close()


@pytest.mark.asyncio
async def test_mock_tool_allow_runs_without_prompt(temp_db):
    """If Bash is set to 'allow', the mock should skip the permission prompt."""
    with mock.patch("app.sessions.ClaudeSDKClient", MockClaudeSDKClient), \
         mock.patch("app.sessions.IS_MOCK", True):

        session = Session(session_id="test_mock_allow", cwd="/tmp")
        session.set_tool_rule("Bash", "allow")
        await session.connect()

        events = []
        async for ev in session.run_turn("mock_tool: Bash"):
            events.append(ev)

        types = [e["type"] for e in events]
        assert "permission_request" not in types
        assert "tool_use" in types
        assert "tool_result" in types

        await session.close()


# ------------------------------------------------------------------
# HTTP endpoint tests
# ------------------------------------------------------------------


@pytest.fixture
async def test_app_client(temp_db):
    import app.main as main
    main.manager = SessionManager()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    await main.manager.close_all()


@pytest.mark.asyncio
async def test_http_tool_defaults(test_app_client):
    """GET /v1/tool-defaults returns the canonical list."""
    resp = await test_app_client.get("/v1/tool-defaults")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data["tools"]) == set(DEFAULT_TOOL_RULES.keys())
    rules_by_tool = {r["tool"]: r["rule"] for r in data["rules"]}
    assert rules_by_tool["Bash"] == "ask"
    assert rules_by_tool["Read"] == "allow"


@pytest.mark.asyncio
async def test_http_session_tool_rules(test_app_client):
    """GET /v1/sessions/{id}/tool-rules returns current rules for the session."""
    resp = await test_app_client.post("/v1/sessions", json={"cwd": "/tmp"})
    assert resp.status_code == 200
    sid = resp.json()["session_id"]

    rules_resp = await test_app_client.get(f"/v1/sessions/{sid}/tool-rules")
    assert rules_resp.status_code == 200
    data = rules_resp.json()
    assert set(data["tools"]) == set(DEFAULT_TOOL_RULES.keys())
    rules_by_tool = {r["tool"]: r["rule"] for r in data["rules"]}
    assert rules_by_tool["Bash"] == "ask"

    # Change Bash to allow
    await test_app_client.post(f"/v1/sessions/{sid}/tool-rule", json={
        "session_id": sid, "tool_name": "Bash", "rule": "allow"
    })

    rules_resp2 = await test_app_client.get(f"/v1/sessions/{sid}/tool-rules")
    data2 = rules_resp2.json()
    rules_by_tool2 = {r["tool"]: r["rule"] for r in data2["rules"]}
    assert rules_by_tool2["Bash"] == "allow"


@pytest.mark.asyncio
async def test_http_resolve_permission(test_app_client):
    """Test the HTTP endpoint for resolving permissions."""
    with mock.patch("app.sessions.ClaudeSDKClient", MockClaudeSDKClient), \
         mock.patch("app.sessions.IS_MOCK", True):

        resp = await test_app_client.post("/v1/sessions", json={"cwd": "/tmp", "model": "claude-sonnet-4-6"})
        assert resp.status_code == 200
        session_id = resp.json()["session_id"]

        async def run_stream():
            events = []
            async with test_app_client.stream("POST", "/v1/sessions/stream", json={
                "session_id": session_id,
                "message": "mock_tool: Bash",
                "cwd": "/tmp"
            }) as response:
                assert response.status_code == 200
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        events.append(json.loads(line[6:]))
            return events

        stream_task = asyncio.create_task(run_stream())
        await asyncio.sleep(0.3)

        import app.main as main
        session = main.manager.get(session_id)
        assert session is not None
        assert len(session._pending_permissions) == 1
        req_id = list(session._pending_permissions.keys())[0]

        resolve_resp = await test_app_client.post("/v1/permissions/respond", json={
            "request_id": req_id,
            "approved": True,
            "always": False
        })
        assert resolve_resp.status_code == 200
        assert resolve_resp.json()["resolved"] is True

        events = await stream_task
        event_types = [e["type"] for e in events]
        assert "permission_request" in event_types
        assert "tool_use" in event_types
        assert "tool_result" in event_types
