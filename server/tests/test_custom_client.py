import pytest
import asyncio
import json
import os
import httpx
from unittest import mock
from app.sessions import Session, SessionManager
from app.tools import execute_tool, ALL_TOOLS
from app.database import get_db, close_db

@pytest.fixture(autouse=True)
async def setup_db():
    await get_db()
    yield
    await close_db()

@pytest.mark.asyncio
async def test_session_tool_call_flow():
    """Test that a tool call from the LLM triggers the permission flow and executes correctly."""
    session = Session(session_id="test_sess")
    
    # First response has a tool call
    resp1 = [
        {
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": "call_123",
                        "function": {"name": "Bash", "arguments": '{"command": "echo hello"}'}
                    }]
                }
            }]
        },
        {}
    ]
    
    # Second response (after tool result) has final text
    resp2 = [
        {
            "choices": [{
                "delta": {
                    "content": "Finished task"
                }
            }]
        },
        {}
    ]
    
    responses_list = [resp1, resp2]
    resp_index = 0

    with mock.patch("app.llm.httpx.AsyncClient.stream") as mock_stream:
        # We need a dynamic mock for multiple calls
        async def mock_stream_context(*args, **kwargs):
            nonlocal resp_index
            mock_resp = mock.MagicMock()
            mock_resp.status_code = 200
            
            current_resp = responses_list[resp_index]
            resp_index += 1
            
            async def mock_aiter_lines():
                for r in current_resp:
                    yield f"data: {json.dumps(r)}"
                yield "data: [DONE]"
                
            mock_resp.aiter_lines = mock_aiter_lines
            return mock_resp

        mock_stream.return_value.__aenter__ = mock_stream_context

        # Run the turn
        gen = session.run_turn("test message")
        
        # Turn 1: tool_use
        event = await gen.__anext__()
        assert event["type"] == "tool_use"
        
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
    res = await execute_tool("Bash", {"command": "echo 'test bash'"})
    assert "test bash" in res.output.strip()
    assert not res.is_error

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
