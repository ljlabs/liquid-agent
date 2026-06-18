
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
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
    mock_db = AsyncMock()
    mock_db.get_session = AsyncMock(return_value=None)
    mock_db.list_sessions = AsyncMock(return_value=[])


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

    # Case 2: 1 user message, 2 assistant responses (e.g. a multi-turn response) -> Turn 2
    session2 = await manager.create(session_id="s2")
    session2.messages = [
        {"role": "user", "content": "Tell me a story in two parts"},
        {"role": "assistant", "content": "Part 1: Once upon a time..."},
        {"role": "assistant", "content": "Part 2: And they lived happily ever after!"}
    ]

    view_data2 = await generator.generate(session_id="s2")
    assert view_data2.active_session.turn_count == 2, f"Expected 2 turns, got {view_data2.active_session.turn_count}"

    # Case 3: Tool use flow: 1 user message, 2 assistant responses (tool call + final response) -> Turn 2
    session3 = await manager.create(session_id="s3")
    session3.messages = [
        {"role": "user", "content": "What is 1+1?"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "1", "name": "calc", "input": {"expression": "1+1"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "1", "content": "2"}]},
        {"role": "assistant", "content": "1+1 is 2"}
    ]

    view_data3 = await generator.generate(session_id="s3")
    assert view_data3.active_session.turn_count == 2, f"Expected 2 turns, got {view_data3.active_session.turn_count}"

    # Case 4: 2 user messages, 1 response each -> Turn 2
    session4 = await manager.create(session_id="s4")
    session4.messages = [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello!"},
        {"role": "user", "content": "How are you?"},
        {"role": "assistant", "content": "I am good!"}
    ]

    view_data4 = await generator.generate(session_id="s4")
    assert view_data4.active_session.turn_count == 2, f"Expected 2 turns, got {view_data4.active_session.turn_count}"

@pytest.mark.asyncio
async def test_max_turns_limit():
    """
    Test that the agent loop respects the max_turns limit per request.
    """
    # Use patch to ensure CustomLLMWrapper is mocked regardless of where it's instantiated
    with patch('app.sessions.CustomLLMWrapper') as MockLLM:
        mock_llm_instance = MockLLM.return_value

        # Setup an async generator for chat_completion
        async def mock_chat_completion(*args, **kwargs):
            yield {"type": "assistant", "content": [{"type": "tool_use", "id": "test", "name": "test_tool", "input": {}}]}

        mock_llm_instance.chat_completion = mock_chat_completion

        # Mock execute_tool to prevent real execution
        with patch('app.sessions.execute_tool', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = MagicMock(is_error=False, output="tool output")

            session = Session(
                session_id="max_turn_test",
                max_turns=3,
                permission_mode="bypassPermissions"
            )


            # Run the turn
            turns_yielded = 0
            async for event in session.run_turn("Test message"):
                if event.get("type") == "tool_use":
                    turns_yielded += 1

            # The loop should run exactly max_turns times
            assert turns_yielded == 3, f"Expected 3 turns before limit, got {turns_yielded}"
