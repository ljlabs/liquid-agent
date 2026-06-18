import pytest
import asyncio
import json
import os
import httpx
from unittest import mock
from app.sessions import Session, SessionManager
from app.tools import execute_tool, ALL_TOOLS
@pytest.mark.asyncio
async def test_session_tool_call_flow(mock_execute_tool):
    """Test that a tool call from the LLM triggers the permission flow and executes correctly."""
    from unittest import mock as _mock

    class MockLLMForFlow:
        def __init__(self, **kwargs):
            self.model = kwargs.get("model", "mock")
            self._turn = 0

        async def chat_completion(self, messages, system=None, tools=None, stream=False):
            self._turn += 1
            if self._turn == 1:
                yield {
                    "content": [
                        {"type": "text", "text": "Running command."},
                        {"type": "tool_use", "id": "call_123", "name": "Bash", "input": {"command": "echo hello"}},
                    ],
                    "stop_reason": "tool_use",
                }
            else:
                yield {
                    "content": [{"type": "text", "text": "Finished task"}],
                    "stop_reason": "end_turn",
                }

    session = Session(session_id="test_sess", permission_mode="default")

    with _mock.patch("app.sessions.CustomLLMWrapper", MockLLMForFlow):
        session._llm = MockLLMForFlow()

        gen = session.run_turn("test message")

        # Turn 1: text
        event = await gen.__anext__()
        assert event["type"] == "text"
        assert event["data"] == "Running command."

        # Turn 1: tool_use
        event = await gen.__anext__()
        assert event["type"] == "tool_use"
        assert event["name"] == "Bash"

        # Turn 1: permission_request
        event = await gen.__anext__()
        assert event["type"] == "permission_request"
        request_id = event["request_id"]
        session.resolve_permission(request_id, approved=True)

        # Turn 1: tool_result
        event = await gen.__anext__()
        assert event["type"] == "tool_result"

        # Turn 2: text
        event = await gen.__anext__()
        assert event["type"] == "text"
        assert event["data"] == "Finished task"

        # Turn 2: result
        event = await gen.__anext__()
        assert event["type"] == "result"

@pytest.mark.asyncio
async def test_tool_read_file_range(tmp_path):
    """Test Read tool with line range."""
    test_file = tmp_path / "test.txt"
    content = "line 1\nline 2\nline 3\nline 4"
    test_file.write_text(content)
    
    # Test range read
    res = await execute_tool("Read", {"path": str(test_file), "start_line": 2, "end_line": 3})
    assert res.output == "line 2\nline 3\n"
    assert not res.is_error

@pytest.mark.asyncio
async def test_tool_replace_file(tmp_path):
    """Test Replace tool."""
    test_file = tmp_path / "replace.txt"
    content = "the quick brown fox"
    test_file.write_text(content)
    
    res = await execute_tool("Replace", {
        "path": str(test_file),
        "old_string": "quick brown",
        "new_string": "slow red"
    })
    assert "Successfully replaced" in res.output
    assert test_file.read_text() == "the slow red fox"

@pytest.mark.asyncio
async def test_tool_bash():
    """Test Bash tool."""
    with mock.patch("app.tools.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0, stdout="test bash\n", stderr="")
        res = await execute_tool("Bash", {"command": "echo 'test bash'"})
        assert "test bash" in res.output.strip()
        mock_run.assert_called_once()

@pytest.mark.asyncio
async def test_tool_web_fetch():
    """Test WebFetch tool with mock."""
    with mock.patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = mock.MagicMock(text="<html>web content</html>", status_code=200)
        res = await execute_tool("WebFetch", {"url": "http://example.com"})
        assert "web content" in res.output
        assert not res.is_error

@pytest.mark.asyncio
async def test_delegation_tool():
    """Test Delegation tool."""
    res = await execute_tool("Delegate", {"task": "fix bugs"})
    assert "Sub-Agent" in res.output
    assert "fix bugs" in res.output
