"""Unit tests for the Session and SessionManager classes."""

import tempfile
import os
import asyncio
import pytest
from app.sessions import Session, SessionManager, DEFAULT_AUTO_ALLOW_TOOLS, DEFAULT_TOOL_RULES


def test_sdk_availability():
    """Check that the custom SDK is available."""
    from app.sessions import SDK_AVAILABLE
    print(f"\nSDK_AVAILABLE: {SDK_AVAILABLE}")
    assert SDK_AVAILABLE is True

@pytest.mark.asyncio
async def test_session_initialization():
    """Test that a session can be initialized with minimal parameters."""
    with tempfile.TemporaryDirectory() as tmpdir:
        session = Session(
            session_id="test_session",
            cwd=tmpdir,
            model="claude-sonnet-4-6"
        )
        assert session.session_id == "test_session"
        assert session.cwd == tmpdir
        assert session.model == "claude-sonnet-4-6"
        assert session.permission_mode == "default"
        assert session.status == "idle"


@pytest.mark.asyncio
async def test_session_with_none_tools():
    """Test that a session can be initialized without tool restrictions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        session = Session(
            session_id="test_session",
            cwd=tmpdir,
            model="claude-sonnet-4-6"
        )
        assert session.session_id == "test_session"
        assert session.allowed_tools is None
        assert session.disallowed_tools is None


@pytest.mark.asyncio
async def test_session_with_tool_lists():
    """Test that a session can be initialized with lists for allowed/disallowed tools."""
    with tempfile.TemporaryDirectory() as tmpdir:
        session = Session(
            session_id="test_session",
            cwd=tmpdir,
            model="claude-sonnet-4-6",
            allowed_tools=["Read", "Write"],
            disallowed_tools=["Bash"]
        )
        assert session.session_id == "test_session"
        assert "read" in session._tool_rules
        assert "write" in session._tool_rules
        assert session._tool_rules["bash"] == "ask"


@pytest.mark.asyncio
async def test_session_connect_and_close():
    """Test that a session can connect and close properly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        session = Session(
            session_id="test_session",
            cwd=tmpdir,
            model="claude-sonnet-4-6"
        )

        # Test connection
        await session.connect()
        assert session.status == "idle"

        # Test closing
        await session.close()
        assert session.status == "closed"


@pytest.mark.asyncio
async def test_session_manager_create():
    """Test that SessionManager can create sessions."""
    manager = SessionManager()
    with tempfile.TemporaryDirectory() as tmpdir:
        session = await manager.create(
            cwd=tmpdir,
            model="claude-sonnet-4-6"
        )

        assert session.session_id.startswith("sess_")
        assert session.cwd == tmpdir
        assert len(manager.list()) == 1

        await manager.close(session.session_id)


@pytest.mark.asyncio
async def test_session_manager_get_or_create():
    """Test that SessionManager can get existing sessions or create new ones."""
    manager = SessionManager()
    with tempfile.TemporaryDirectory() as tmpdir:
        session1 = await manager.create(
            cwd=tmpdir,
            model="claude-sonnet-4-6"
        )
        session_id = session1.session_id

        session2 = await manager.get_or_create(session_id)
        assert session1.session_id == session2.session_id

        session3 = await manager.get_or_create(None, cwd=tmpdir)
        assert session3.session_id != session_id
        assert session3.cwd == tmpdir

        await manager.close(session_id)
        await manager.close(session3.session_id)


@pytest.mark.asyncio
async def test_session_manager_close_all():
    """Test that SessionManager can close all sessions."""
    manager = SessionManager()
    with tempfile.TemporaryDirectory() as tmpdir:
        session1 = await manager.create(cwd=tmpdir)
        session2 = await manager.create(cwd=tmpdir)

        assert len(manager.list()) == 2

        await manager.close_all()
        assert len(manager.list()) == 0


@pytest.mark.asyncio
async def test_pending_permission():
    """Test that PendingPermission can be created."""
    from app.sessions import PendingPermission
    import uuid

    request_id = str(uuid.uuid4())
    pending = PendingPermission(
        request_id=request_id,
        tool_name="Bash",
        tool_input={"command": "echo test"}
    )

    assert pending.request_id == request_id
    assert pending.tool_name == "Bash"
    assert pending.tool_input == {"command": "echo test"}
    assert pending.future is not None

def test_default_auto_allow_tools():
    """Test that DEFAULT_AUTO_ALLOW_TOOLS is defined correctly."""
    expected_tools = {"Read", "Glob", "Grep", "WebFetch"}
    assert DEFAULT_AUTO_ALLOW_TOOLS == expected_tools


def test_default_tool_rules_populated():
    """Test that DEFAULT_TOOL_RULES has entries for the canonical tool list."""
    assert "Bash" in DEFAULT_TOOL_RULES
    assert DEFAULT_TOOL_RULES["Bash"] == "ask"
    assert DEFAULT_TOOL_RULES["Read"] == "allow"
    assert DEFAULT_TOOL_RULES["Replace"] == "ask"
    assert DEFAULT_TOOL_RULES["Write"] == "ask"
    assert DEFAULT_TOOL_RULES["WebFetch"] == "allow"
    assert DEFAULT_TOOL_RULES["Grep"] == "allow"


# ------------------------------------------------------------------
# Database module tests
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_session_crud():
    """Test create, get, update, list, delete for sessions."""
    import tempfile
    from pathlib import Path
    from app import database as test_db

    tmp = Path(tempfile.mkdtemp()) / "test.db"
    test_db.DB_PATH = tmp
    test_db._db = None

    try:
        session = await test_db.create_session(
            session_id="test_crud",
            title="Test Session",
            cwd="/tmp",
            model="claude-haiku-4-5",
            permission_mode="default",
        )
        assert session is not None
        assert session["id"] == "test_crud"
        assert session["title"] == "Test Session"

        fetched = await test_db.get_session("test_crud")
        assert fetched is not None
        assert fetched["model"] == "claude-haiku-4-5"

        await test_db.update_session("test_crud", title="Updated Title", status="running")
        updated = await test_db.get_session("test_crud")
        assert updated["title"] == "Updated Title"
        assert updated["status"] == "running"

        sessions = await test_db.list_sessions()
        assert len(sessions) >= 1
        assert any(s["id"] == "test_crud" for s in sessions)

        deleted = await test_db.delete_session("test_crud")
        assert deleted is True
        assert await test_db.get_session("test_crud") is None
    finally:
        await test_db.close_db()
        import shutil
        shutil.rmtree(tmp.parent, ignore_errors=True)


@pytest.mark.asyncio
async def test_db_message_crud():
    """Test add_message and get_messages."""
    import tempfile
    from pathlib import Path
    from app import database as test_db

    tmp = Path(tempfile.mkdtemp()) / "test_messages.db"
    test_db.DB_PATH = tmp
    test_db._db = None

    try:
        await test_db.create_session(session_id="msg_session", title="Msg Test")
        msg_id = await test_db.add_message(
            session_id="msg_session",
            role="user",
            content="Hello",
        )
        assert msg_id is not None
        assert msg_id > 0

        await test_db.add_message(
            session_id="msg_session",
            role="assistant",
            type="text",
            content="Hi there!",
        )

        messages = await test_db.get_messages("msg_session")
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hello"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "Hi there!"

        count = await test_db.get_message_count("msg_session")
        assert count == 2
    finally:
        await test_db.close_db()
        import shutil
        shutil.rmtree(tmp.parent, ignore_errors=True)


@pytest.mark.asyncio
async def test_db_get_nonexistent():
    """Test that get_session returns None for unknown IDs."""
    import tempfile
    from pathlib import Path
    from app import database as test_db

    tmp = Path(tempfile.mkdtemp()) / "test_none.db"
    test_db.DB_PATH = tmp
    test_db._db = None

    try:
        assert await test_db.get_session("does_not_exist") is None
    finally:
        await test_db.close_db()
        import shutil
        shutil.rmtree(tmp.parent, ignore_errors=True)
