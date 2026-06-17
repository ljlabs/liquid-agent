import asyncio
import pytest
import os
from app.sessions import Session

@pytest.mark.asyncio
async def test_real_sdk_permission_callback():
    """
    Integration test verifying if permission logic is triggered for a Bash command.
    """
    # Set environment for mock server
    os.environ["ANTHROPIC_MODEL"] = "mock-model"
    os.environ["ANTHROPIC_BASE_URL"] = "http://localhost:9002"

    session_id = "test_integration_perm"
    cwd = os.getcwd()

    session = Session(session_id=session_id, cwd=cwd, permission_mode="default")

    # Ensure Bash is set to 'ask'
    session.set_tool_rule("Bash", "ask")

    await session.connect()

    # We will track if the callback is ever triggered
    callback_triggered = asyncio.Event()

    # In the current implementation, permissions are handled via _pending_permissions
    # and a future. We can check if a permission request was created.
    async def run_turn():
        async for _ in session.run_turn("run pwd"):
            pass

    turn_task = asyncio.create_task(run_turn())

    # Wait for a permission request to appear in the session
    for _ in range(20):
        if session._pending_permissions:
            callback_triggered.set()
            break
        await asyncio.sleep(0.1)

    assert callback_triggered.is_set(), "Permission request was not triggered for 'run pwd'"
    await turn_task
