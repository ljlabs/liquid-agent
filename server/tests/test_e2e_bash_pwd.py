import asyncio
import pytest
from unittest import mock
from app.sessions import Session, PermissionResultAllow, PermissionResultDeny

class EndToEndMockClaudeClient:
    def __init__(self, options=None):
        self.options = options
        self._queue = asyncio.Queue()

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def query(self, content):
        if content == "run pwd in your bash tool and tell me the result":
            tool_name = "Bash"
            tool_input = {"command": "pwd"}
            tool_id = "tool_pwd_123"

            # 1. Start tool use
            await self._queue.put({
                "type": "content_block_start",
                "content_block": {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": tool_name,
                    "input": tool_input
                }
            })
            
            # Simulate some delay
            await asyncio.sleep(0.01)

            # 2. Check permission
            class MockContext:
                display_name = tool_name
                description = "Run a bash command"
                title = "Run Bash"
            context = MockContext()

            if self.options and hasattr(self.options, "can_use_tool"):
                try:
                    # This should block until the test resolves the permission
                    perm_res = await self.options.can_use_tool(tool_name, tool_input, context)
                    
                    is_allowed = False
                    if isinstance(perm_res, PermissionResultAllow) or type(perm_res).__name__ == "PermissionResultAllow":
                        is_allowed = True
                    
                    if is_allowed:
                        await self._queue.put({
                            "type": "tool_result",
                            "tool_id": tool_id,
                            "output": "/c/Users/jorda/Documents/workspace/model_containment/server"
                        })
                    else:
                        await self._queue.put({
                            "type": "tool_error",
                            "tool_id": tool_id,
                            "error": "Permission denied"
                        })
                except Exception as e:
                    await self._queue.put({
                        "type": "tool_error",
                        "tool_id": tool_id,
                        "error": str(e)
                    })
            
            await self._queue.put({"type": "message_stop"})

    async def receive_response(self):
        while True:
            ev = await self._queue.get()
            yield ev
            if ev.get("type") == "message_stop":
                break

@pytest.mark.asyncio
async def test_e2e_bash_pwd_permission_flow():
    """
    Test that 'Bash(pwd)' blocks for permission and only returns the result after approval.
    """
    with mock.patch("app.sessions.ClaudeSDKClient", EndToEndMockClaudeClient), \
         mock.patch("app.sessions.IS_MOCK", True):

        session = Session(session_id="test_e2e", cwd="/tmp")
        await session.connect()

        events = []
        async def collect():
            async for ev in session.run_turn("run pwd in your bash tool and tell me the result"):
                events.append(ev)
        
        collect_task = asyncio.create_task(collect())
        
        # Wait for the permission request to be emitted
        # We need to give it enough time to run through content_block_start and hit can_use_tool
        for _ in range(10):
            await asyncio.sleep(0.1)
            if any(e["type"] == "permission_request" for e in events):
                break
        
        # Assert that we have a permission request but NO tool result yet
        event_types = [e["type"] for e in events]
        assert "permission_request" in event_types
        assert "tool_result" not in event_types, "Tool should NOT have responded with a result before permission"
        
        # Check that it's blocked
        assert len(session._pending_permissions) == 1
        req_id = list(session._pending_permissions.keys())[0]
        
        # Now resolve the permission
        session.resolve_permission(req_id, approved=True)
        
        # Wait for completion
        await collect_task
        
        # Final assertions
        final_event_types = [e["type"] for e in events]
        assert "tool_result" in final_event_types
        
        # Verify the actual output
        result_event = next(e for e in events if e["type"] == "tool_result")
        assert result_event["output"] == "/c/Users/jorda/Documents/workspace/model_containment/server"

        await session.close()
