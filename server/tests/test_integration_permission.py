import asyncio
import pytest
import os
from app.sessions import Session

@pytest.mark.asyncio
async def test_real_sdk_permission_callback():
    """
    Integration test connecting to the real ClaudeSDKClient to verify if
    can_use_tool callback is triggered for a Bash command.
    """
    # Use a dummy session ID and tmp directory
    session_id = "test_integration_perm"
    cwd = os.getcwd()
    
    session = Session(session_id=session_id, cwd=cwd, permission_mode="default")
    
    # Ensure Bash is set to 'ask'
    session.set_tool_rule("Bash", "ask")
    
    await session.connect()
    
    # We will track if the callback is ever triggered
    callback_triggered = asyncio.Event()
    
    # Wrap the original callback to detect invocation
    original_callback = session._can_use_tool
    
    async def wrapped_callback(tool_name, tool_input, context):
        print(f"\n!!! CALLBACK TRIGGERED: {tool_name} !!!\n")
        callback_triggered.set()
        return await original_callback(tool_name, tool_input, context)
        
    session._can_use_tool = wrapped_callback
    
    async def collect():
        async for _ in session.run_turn("run pwd"):
            pass
            
    print(f"\nStarting run_turn for tool call 'edit'...")
    # Trigger a tool call
    turn_task = asyncio.create_task(collect())
    
    # Try sending an edit command which should definitely trigger 'ask'
    # Actually we just send a message that would provoke a tool call
    # We can try to send a message that forces Edit
    # The session will try to use the tool if the LLM decides to.
    # Since we use the real SDK, we rely on it to invoke the tool.
    
    # Send a message that should provoke 'Edit' tool usage
    # (Assuming we have a test prompt that triggers this)
    # If this doesn't trigger it, we might need a better prompt
    async def run():
        async for _ in session.run_turn("edit the file /tmp/test.txt"):
            pass
    collect_task = asyncio.create_task(run())
