import pytest
import asyncio
import json
import httpx
from unittest import mock
from app.sessions import (
    Session,
    SessionManager,
    DEFAULT_TOOL_RULES,
    DEFAULT_AUTO_ALLOW_TOOLS,
)
from app.main import app


class MockLLM:
    """Mock CustomLLMWrapper that yields Anthropic Messages API format responses."""

    def __init__(self, **kwargs):
        self.model = kwargs.get("model", "mock")
        self._sequence = []
        self._index = 0

    def set_sequence(self, sequence):
        self._sequence = sequence
        self._index = 0

    async def chat_completion(self, messages, system=None, tools=None, stream=False):
        if self._index < len(self._sequence):
            resp = self._sequence[self._index]
            self._index += 1
            yield resp
        else:
            yield {
                "content": [{"type": "text", "text": "Done."}],
                "stop_reason": "end_turn",
            }


# ------------------------------------------------------------------
# Default tool rules
# ------------------------------------------------------------------


def test_default_tool_rules_defined():
    """DEFAULT_TOOL_RULES should contain the canonical tool list."""
    assert "Bash" in DEFAULT_TOOL_RULES
    assert DEFAULT_TOOL_RULES["Bash"] == "ask"
    assert DEFAULT_TOOL_RULES["Read"] == "allow"
    assert DEFAULT_TOOL_RULES["Replace"] == "ask"
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
    assert session._tool_rules["bash"] == "ask"

    session.set_tool_rule("Bash", "allow")
    assert session._tool_rules["bash"] == "allow"

    session.set_tool_rule("Bash", "deny")
    assert session._tool_rules["bash"] == "deny"


# ------------------------------------------------------------------
# _check_permission enforcement
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_permission_default_ask_triggers_permission():
    """Bash defaults to 'ask' -- _check_permission should create a pending permission."""
    session = Session(session_id="test_ask", cwd="/tmp")

    task = asyncio.create_task(session._check_permission("Bash", {"command": "ls"}))
    await asyncio.sleep(0.05)

    assert len(session._pending_permissions) == 1

    req_id = list(session._pending_permissions.keys())[0]
    session.resolve_permission(req_id, approved=False)
    result = await task
    assert result is False


@pytest.mark.asyncio
async def test_check_permission_allow_auto_approves():
    """Setting Bash to 'allow' should skip the permission prompt."""
    session = Session(session_id="test_auto_allow", cwd="/tmp")
    session.set_tool_rule("Bash", "allow")

    res = await session._check_permission("Bash", {"command": "ls"})
    assert res is True
    assert len(session._pending_permissions) == 0


@pytest.mark.asyncio
async def test_check_permission_deny_blocks():
    """Setting Bash to 'deny' should immediately deny."""
    session = Session(session_id="test_deny", cwd="/tmp")
    session.set_tool_rule("Bash", "deny")

    res = await session._check_permission("Bash", {"command": "ls"})
    assert res is False
    assert len(session._pending_permissions) == 0


@pytest.mark.asyncio
async def test_check_permission_read_auto_allows():
    """Read defaults to 'allow' in DEFAULT_TOOL_RULES -- should auto-allow."""
    session = Session(session_id="test_read", cwd="/tmp")
    res = await session._check_permission("Read", {"path": "/tmp/foo"})
    assert res is True
    assert len(session._pending_permissions) == 0


@pytest.mark.asyncio
async def test_check_permission_ask_overrides_auto_allow():
    """Setting Read to 'ask' should trigger a permission prompt."""
    session = Session(session_id="test_ask_override", cwd="/tmp")
    session.set_tool_rule("Read", "ask")

    task = asyncio.create_task(session._check_permission("Read", {"path": "/tmp/foo"}))
    await asyncio.sleep(0.05)

    assert len(session._pending_permissions) == 1
    req_id = list(session._pending_permissions.keys())[0]
    session.resolve_permission(req_id, approved=True)
    result = await task
    assert result is True


# ------------------------------------------------------------------
# Case-insensitive tool rules
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_insensitive_tool_rules():
    """Tool rules are stored lowercase, but lookups work with any case."""
    session = Session(session_id="test_case", cwd="/tmp")

    session.set_tool_rule("Bash", "allow")
    assert session._tool_rules.get("bash") == "allow"

    res = await session._check_permission("bash", {})
    assert res is True

    session.set_tool_rule("edit", "deny")
    assert session._tool_rules.get("edit") == "deny"

    res2 = await session._check_permission("Edit", {})
    assert res2 is False


# ------------------------------------------------------------------
# Mock LLM permission request flow
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_tool_permission_request(mock_execute_tool):
    """send_message with a tool_use response triggers a pending permission and blocks."""
    with mock.patch("app.sessions.CustomLLMWrapper", MockLLM):
        session = Session(session_id="test_mock_tool", cwd="/tmp", permission_mode="default")

        mock_llm = session._llm
        mock_llm.set_sequence([
            {
                "content": [
                    {"type": "text", "text": "I'll run that."},
                    {"type": "tool_use", "id": "tool_1", "name": "Bash", "input": {"command": "echo hello"}},
                ],
                "stop_reason": "tool_use",
            },
        ])

        events = []
        async def collect():
            async for ev in session.run_turn("mock_tool: Bash"):
                events.append(ev)

        collect_task = asyncio.create_task(collect())

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


@pytest.mark.asyncio
async def test_mock_tool_deny_prevents_execution():
    """If the user denies a tool, the agent should emit tool_error."""
    with mock.patch("app.sessions.CustomLLMWrapper", MockLLM):
        session = Session(session_id="test_mock_deny", cwd="/tmp", permission_mode="default")

        mock_llm = session._llm
        mock_llm.set_sequence([
            {
                "content": [
                    {"type": "text", "text": "I'll run that."},
                    {"type": "tool_use", "id": "tool_1", "name": "Bash", "input": {"command": "echo hello"}},
                ],
                "stop_reason": "tool_use",
            },
        ])

        events = []
        async def collect():
            async for ev in session.run_turn("mock_tool: Bash"):
                events.append(ev)

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.15)

        assert len(session._pending_permissions) == 1
        req_id = list(session._pending_permissions.keys())[0]

        session.resolve_permission(req_id, approved=False)
        await asyncio.sleep(0.15)
        await task

        types = [e["type"] for e in events]
        assert "permission_request" in types
        assert "tool_error" in types


@pytest.mark.asyncio
async def test_deny_halts_agent_loop_no_extra_llm_call():
    """When a tool call is denied, the agent loop should halt immediately.

    After denial the loop should NOT call the LLM again. The MockLLM
    tracks how many times chat_completion was called.
    """
    with mock.patch("app.sessions.CustomLLMWrapper", MockLLM):
        session = Session(session_id="test_deny_halt", cwd="/tmp", permission_mode="default")

        mock_llm = session._llm
        mock_llm.set_sequence([
            {
                "content": [
                    {"type": "text", "text": "I'll run that."},
                    {"type": "tool_use", "id": "tool_1", "name": "Bash", "input": {"command": "echo hello"}},
                ],
                "stop_reason": "tool_use",
            },
            # This should NOT be reached after denial
            {
                "content": [{"type": "text", "text": "This should not appear."}],
                "stop_reason": "end_turn",
            },
        ])

        call_count = 0
        original_chat = mock_llm.chat_completion

        async def counting_chat(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            async for chunk in original_chat(*args, **kwargs):
                yield chunk

        mock_llm.chat_completion = counting_chat

        events = []
        async def collect():
            async for ev in session.run_turn("test deny halt"):
                events.append(ev)

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.15)

        assert len(session._pending_permissions) == 1
        req_id = list(session._pending_permissions.keys())[0]

        session.resolve_permission(req_id, approved=False)
        await asyncio.sleep(0.15)
        await task

        # The LLM should have been called exactly once (the initial tool_use response)
        assert call_count == 1, f"Expected 1 LLM call, got {call_count}"

        # The loop should have halted — no "This should not appear." text
        text_events = [e for e in events if e["type"] == "text"]
        all_text = "".join(e["data"] for e in text_events)
        assert "This should not appear" not in all_text

        # Session should be idle
        assert session.status == "idle"


@pytest.mark.asyncio
async def test_deny_halts_resume_after_permission():
    """When permission is denied via _resume_after_permission (idle session),
    the agent loop should NOT continue. The session stays idle."""
    with mock.patch("app.sessions.CustomLLMWrapper", MockLLM):
        session = Session(session_id="test_resume_deny", cwd="/tmp", permission_mode="default")

        mock_llm = session._llm
        mock_llm.set_sequence([
            {
                "content": [
                    {"type": "text", "text": "Running tool."},
                    {"type": "tool_use", "id": "tool_1", "name": "Bash", "input": {"command": "echo hello"}},
                ],
                "stop_reason": "tool_use",
            },
            # This should NOT be reached
            {
                "content": [{"type": "text", "text": "Extra response."}],
                "stop_reason": "end_turn",
            },
        ])

        call_count = 0
        original_chat = mock_llm.chat_completion

        async def counting_chat(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            async for chunk in original_chat(*args, **kwargs):
                yield chunk

        mock_llm.chat_completion = counting_chat

        events = []
        async def collect():
            async for ev in session.run_turn("test resume deny"):
                events.append(ev)

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.15)

        assert len(session._pending_permissions) == 1
        req_id = list(session._pending_permissions.keys())[0]

        # Set session to idle (simulating page refresh scenario)
        session.status = "idle"

        # Resolve with deny — this triggers _resume_after_permission
        session.resolve_permission(req_id, approved=False)
        await asyncio.sleep(0.3)
        await task

        # LLM should have been called only once (the initial tool_use)
        assert call_count == 1, f"Expected 1 LLM call, got {call_count}"

        # Session should still be idle
        assert session.status == "idle"

        # No extra text from the denied path
        text_events = [e for e in events if e["type"] == "text"]
        all_text = "".join(e["data"] for e in text_events)
        assert "Extra response" not in all_text


@pytest.mark.asyncio
async def test_mock_tool_allow_runs_without_prompt(mock_execute_tool):
    """If Bash is set to 'allow', the agent should skip the permission prompt."""
    with mock.patch("app.sessions.CustomLLMWrapper", MockLLM):
        session = Session(session_id="test_mock_allow", cwd="/tmp", permission_mode="default")
        session.set_tool_rule("Bash", "allow")

        mock_llm = session._llm
        mock_llm.set_sequence([
            {
                "content": [
                    {"type": "text", "text": "Running."},
                    {"type": "tool_use", "id": "tool_1", "name": "Bash", "input": {"command": "echo hello"}},
                ],
                "stop_reason": "tool_use",
            },
            {
                "content": [{"type": "text", "text": "Done."}],
                "stop_reason": "end_turn",
            },
        ])

        events = []
        async for ev in session.run_turn("mock_tool: Bash"):
            events.append(ev)

        types = [e["type"] for e in events]
        assert "permission_request" not in types
        assert "tool_use" in types


# ------------------------------------------------------------------
# HTTP endpoint tests
# ------------------------------------------------------------------


@pytest.fixture
async def test_app_client():
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

    await test_app_client.post(f"/v1/sessions/{sid}/tool-rule", json={
        "session_id": sid, "tool_name": "Bash", "rule": "allow"
    })

    rules_resp2 = await test_app_client.get(f"/v1/sessions/{sid}/tool-rules")
    data2 = rules_resp2.json()
    rules_by_tool2 = {r["tool"]: r["rule"] for r in data2["rules"]}
    assert rules_by_tool2["Bash"] == "allow"


@pytest.mark.asyncio
async def test_http_resolve_permission(test_app_client, mock_execute_tool):
    """Test the HTTP endpoint for resolving permissions via the stream endpoint."""
    with mock.patch("app.sessions.CustomLLMWrapper", MockLLM):
        resp = await test_app_client.post("/v1/sessions", json={"cwd": "/tmp", "model": "mock-model"})
        assert resp.status_code == 200
        session_id = resp.json()["session_id"]

        import app.main as main
        session = main.manager.get(session_id)
        session._llm.set_sequence([
            {
                "content": [
                    {"type": "text", "text": "Running tool."},
                    {"type": "tool_use", "id": "tool_http_1", "name": "Bash", "input": {"command": "echo test"}},
                ],
                "stop_reason": "tool_use",
            },
            {
                "content": [{"type": "text", "text": "Tool completed."}],
                "stop_reason": "end_turn",
            },
        ])

        async def run_stream():
            events = []
            async with test_app_client.stream("POST", "/v1/sessions/stream", json={
                "session_id": session_id,
                "message": "run echo test",
                "cwd": "/tmp"
            }) as response:
                assert response.status_code == 200
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        events.append(json.loads(line[6:]))
            return events

        stream_task = asyncio.create_task(run_stream())
        await asyncio.sleep(0.3)

        assert session is not None
        assert len(session._pending_permissions) == 1
        req_id = list(session._pending_permissions.keys())[0]

        resolve_resp = await test_app_client.post(f"/v1/sessions/{session_id}/permissions/respond", json={
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
