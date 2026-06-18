import asyncio
import pytest
from unittest import mock
from app.sessions import Session


class MockLLMPwd:
    """Mock LLM that returns a Bash pwd tool_use, then a text response."""

    def __init__(self, **kwargs):
        self.model = kwargs.get("model", "mock")
        self._turn = 0

    async def chat_completion(self, messages, system=None, tools=None, stream=False):
        self._turn += 1
        if self._turn == 1:
            yield {
                "content": [
                    {"type": "text", "text": "I'll run pwd."},
                    {"type": "tool_use", "id": "tool_pwd_123", "name": "Bash", "input": {"command": "pwd"}},
                ],
                "stop_reason": "tool_use",
            }
        else:
            yield {
                "content": [{"type": "text", "text": "Done."}],
                "stop_reason": "end_turn",
            }


@pytest.mark.asyncio
async def test_e2e_bash_pwd_permission_flow(mock_execute_tool):
    """
    Test that 'Bash(pwd)' blocks for permission and only returns the result after approval.
    """
    with mock.patch("app.sessions.CustomLLMWrapper", MockLLMPwd):
        session = Session(session_id="test_e2e", cwd="/tmp", permission_mode="default")
        session._llm = MockLLMPwd()

        events = []
        async def collect():
            async for ev in session.run_turn("run pwd"):
                events.append(ev)

        collect_task = asyncio.create_task(collect())

        for _ in range(20):
            await asyncio.sleep(0.1)
            if any(e["type"] == "permission_request" for e in events):
                break

        event_types = [e["type"] for e in events]
        assert "permission_request" in event_types
        assert "tool_result" not in event_types

        assert len(session._pending_permissions) == 1
        req_id = list(session._pending_permissions.keys())[0]

        session.resolve_permission(req_id, approved=True)

        await collect_task

        final_event_types = [e["type"] for e in events]
        assert "tool_result" in final_event_types
        assert "text" in final_event_types

        result_event = next(e for e in events if e["type"] == "tool_result")
        assert result_event["output"].strip(), "Tool result should not be empty"

        await session.close()
