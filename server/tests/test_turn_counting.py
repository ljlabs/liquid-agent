
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from app.sessions import Session, SessionManager
from app.view_data import ViewDataGenerator, SessionView
from app import database

@pytest.mark.asyncio
async def test_session_turn_count_calculation():
    """
    Test that the turn count is calculated based on assistant responses,
    not user messages.
    """
    # Mock database and session manager
    mock_db = MagicMock()
    mock_db.get_session = AsyncMock(return_value=None)

    manager = SessionManager()
    generator = ViewDataGenerator(manager, mock_db)

    # Case 1: 1 user message, 1 assistant response -> Turn 1
    session1 = await manager.create(session_id="s1")
    session1.messages = [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello!"}
    ]

    view_data1 = await generator.generate(session_id="s1")
    assert view_data1.active_session.turn_count == 1, f"Expected 1 turn, got {view_data1.active_session.turn_count}"

    # Case 2: 1 user message, 2 assistant responses (e.g. tool use + final response) -> Turn 2
    session2 = await manager.create(session_id="s2")
    session2.messages = [
        {"role": "user", "content": "What is 1+1?"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "1", "name": "calc", "input": "1+1"}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "1", "content": "2"}]},
        {"role": "assistant", "content": "1+1 is 2"}
    ]

    view_data2 = await generator.generate(session_id="s2")
    assert view_data2.active_session.turn_count == 2, f"Expected 2 turns, got {view_data2.active_session.turn_count}"

    # Case 3: 2 user messages, 1 response each -> Turn 2
    session3 = await manager.create(session_id="s3")
    session3.messages = [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello!"},
        {"role": "user", "content": "How are you?"},
        {"role": "assistant", "content": "I am good!"}
    ]

    view_data3 = await generator.generate(session_id="s3")
    assert view_data3.active_session.turn_count == 2, f"Expected 2 turns, got {view_data3.active_session.turn_count}"

@pytest.mark.asyncio
async def test_max_turns_limit():
    """
    Test that the agent loop respects the max_turns limit per request.
    """
    # Mock LLM to always return a tool use to force the loop to continue
    mock_llm = MagicMock()
    # chat_completion is an async generator
    async def mock_chat_completion(*args, **kwargs):
        yield {"type": "assistant", "content": [{"type": "tool_use", "id": "test", "name": "test_tool", "input": {}}]}

    mock_llm.chat_completion = mock_chat_completion

    session = Session(
        session_id="max_turn_test",
        max_turns=3
    )
    session._llm = mock_llm

    # We need to mock execute_tool to avoid actual execution
    import app.tools
    app.tools.execute_tool = AsyncMock(return_value=MagicMock(is_error=False, output="tool output"))

    # Run the turn
    turns_yielded = 0
    async for event in session.run_turn("Test message"):
        if event.get("type") == "tool_use":
            turns_yielded += 1

    # The loop should run exactly max_turns times
    # In run_turn, the loop is: while turn_count < self.max_turns: turn_count += 1
    # So it should execute the loop 3 times.
    assert turns_yielded == 3, f"Expected 3 turns before limit, got {turns_yielded}"
