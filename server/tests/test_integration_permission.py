import asyncio
import pytest
import os
import httpx
from app.sessions import Session


@pytest.mark.asyncio
async def test_real_sdk_permission_callback(mock_llm_server):
    """
    Integration test verifying if permission logic is triggered for a Bash command.
    Uses the mock LLM server started by conftest.
    """
    # Reset mock server state before test
    async with httpx.AsyncClient() as c:
        await c.post(f"http://127.0.0.1:{mock_llm_server}/reset", timeout=10)

    session_id = "test_integration_perm"
    cwd = os.getcwd()

    session = Session(session_id=session_id, cwd=cwd, permission_mode="default", model="mock-model")
    session.set_tool_rule("Bash", "ask")

    await session.connect()

    events = []

    async def collect():
        async for ev in session.run_turn("run pwd"):
            events.append(ev)

    turn_task = asyncio.create_task(collect())

    for _ in range(50):
        if session._pending_permissions:
            break
        await asyncio.sleep(0.1)

    assert len(session._pending_permissions) >= 1, "Permission request was not triggered for 'run pwd'"

    req_id = list(session._pending_permissions.keys())[0]
    session.resolve_permission(req_id, approved=True)

    await asyncio.wait_for(turn_task, timeout=5)
