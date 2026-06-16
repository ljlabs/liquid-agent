import pytest
import os
import shutil
import tempfile
import httpx
from app.main import app


@pytest.fixture
def tmp_cwd():
    """Fixture to provide a consistent temporary directory for tests."""
    tmpdir = tempfile.mkdtemp()
    yield tmpdir
    try:
        shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception:
        pass


@pytest.fixture
async def async_client():
    """Fixture to provide an AsyncClient and ensure manager is initialized."""
    from app.main import app
    from app.sessions import SessionManager
    import app.main as main

    # Manually initialize the manager since we aren't running the full lifespan
    main.manager = SessionManager()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    # Cleanup
    await main.manager.close_all()


@pytest.mark.asyncio
async def test_health_endpoint(async_client):
    """Test that the health endpoint returns successfully."""
    response = await async_client.get("/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "sdk_available" in data
    assert "active_sessions" in data


@pytest.mark.asyncio
async def test_list_sessions_empty(async_client):
    """Test that listing sessions returns an empty list initially."""
    response = await async_client.get("/v1/sessions")
    assert response.status_code == 200
    data = response.json()
    assert data["sessions"] == []


@pytest.mark.asyncio
async def test_create_session(async_client, tmp_cwd):
    """Test that a session can be created via the API."""
    response = await async_client.post(
        "/v1/sessions",
        json={
            "cwd": tmp_cwd,
            "model": "claude-sonnet-4-6"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert data["cwd"] == tmp_cwd
    assert data["model"] == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_create_session_with_none_tools(async_client, tmp_cwd):
    """Test that a session can be created with None for tool lists."""
    response = await async_client.post(
        "/v1/sessions",
        json={
            "cwd": tmp_cwd,
            "allowed_tools": None,
            "disallowed_tools": None
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data


@pytest.mark.asyncio
async def test_create_session_minimal(async_client, tmp_cwd):
    """Test that a session can be created with minimal parameters."""
    response = await async_client.post("/v1/sessions", json={"cwd": tmp_cwd})
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert "cwd" in data
    assert "model" in data


@pytest.mark.asyncio
async def test_close_session(async_client, tmp_cwd):
    """Test that a session can be closed."""
    # First create a session
    create_response = await async_client.post("/v1/sessions", json={"cwd": tmp_cwd})
    assert create_response.status_code == 200
    session_id = create_response.json()["session_id"]

    # Close the session
    close_response = await async_client.delete(f"/v1/sessions/{session_id}")
    assert close_response.status_code == 200
    assert close_response.json()["closed"] is True


@pytest.mark.asyncio
async def test_close_nonexistent_session(async_client):
    """Test that closing a non-existent session returns 404."""
    response = await async_client.delete("/v1/sessions/nonexistent_session_id")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_interrupt_nonexistent_session(async_client):
    """Test that interrupting a non-existent session returns 404."""
    response = await async_client.post(
        "/v1/sessions/nonexistent_session_id/interrupt",
        json={}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_set_permission_mode_nonexistent_session(async_client):
    """Test that setting permission mode on a non-existent session returns 404."""
    response = await async_client.post(
        "/v1/sessions/nonexistent_session_id/permission-mode",
        json={"session_id": "nonexistent_session_id", "permission_mode": "acceptEdits"}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_set_model_nonexistent_session(async_client):
    """Test that setting model on a non-existent session returns 404."""
    response = await async_client.post(
        "/v1/sessions/nonexistent_session_id/model",
        json={"session_id": "nonexistent_session_id", "model": "claude-haiku-4-5"}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_set_tool_rule_nonexistent_session(async_client):
    """Test that setting tool rule on a non-existent session returns 404."""
    response = await async_client.post(
        "/v1/sessions/nonexistent_session_id/tool-rule",
        json={"session_id": "nonexistent_session_id", "tool_name": "Bash", "rule": "allow"}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_resolve_permission_nonexistent_request(async_client):
    """Test that resolving a non-existent permission request returns 404."""
    response = await async_client.post(
        "/v1/permissions/respond",
        json={
            "request_id": "nonexistent_request_id",
            "approved": True,
            "always": False
        }
    )
    assert response.status_code == 404


# ------------------------------------------------------------------
# DB endpoint tests
# ------------------------------------------------------------------


@pytest.fixture
async def async_client_with_db():
    """Fixture that also initializes the DB for DB endpoint tests."""
    from app.main import app
    from app.sessions import SessionManager
    import app.main as main
    from app import database as db

    main.manager = SessionManager()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    await main.manager.close_all()
    await db.close_db()


@pytest.mark.asyncio
async def test_db_list_sessions_empty(async_client_with_db):
    """Test that listing DB sessions returns empty list initially."""
    response = await async_client_with_db.get("/v1/db/sessions")
    assert response.status_code == 200
    data = response.json()
    assert data["sessions"] == []


@pytest.mark.asyncio
async def test_db_session_not_found(async_client_with_db):
    """Test that fetching a non-existent DB session returns 404."""
    response = await async_client_with_db.get("/v1/db/sessions/nonexistent")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_db_messages_not_found(async_client_with_db):
    """Test that fetching messages for a non-existent session returns 404."""
    response = await async_client_with_db.get("/v1/db/sessions/nonexistent/messages")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_db_delete_session_not_found(async_client_with_db):
    """Test that deleting a non-existent DB session returns 404."""
    response = await async_client_with_db.delete("/v1/db/sessions/nonexistent")
    assert response.status_code == 404


# ------------------------------------------------------------------
# DB endpoint tests
# ------------------------------------------------------------------


@pytest.fixture
async def async_client_with_db():
    """Fixture that also initializes the DB for DB endpoint tests."""
    from app.main import app
    from app.sessions import SessionManager
    import app.main as main
    from app import database as db
    import tempfile
    from pathlib import Path
    import shutil

    tmpdir = tempfile.mkdtemp()
    tmp = Path(tmpdir) / "test_main.db"
    old_db_path = db.DB_PATH
    db.DB_PATH = tmp
    db._db = None

    main.manager = SessionManager()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    await main.manager.close_all()
    await db.close_db()
    db.DB_PATH = old_db_path
    db._db = None
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.asyncio
async def test_db_list_sessions_empty(async_client_with_db):
    """Test that listing DB sessions returns empty list initially."""
    response = await async_client_with_db.get("/v1/db/sessions")
    assert response.status_code == 200
    data = response.json()
    assert data["sessions"] == []


@pytest.mark.asyncio
async def test_db_session_not_found(async_client_with_db):
    """Test that fetching a non-existent DB session returns 404."""
    response = await async_client_with_db.get("/v1/db/sessions/nonexistent")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_db_messages_not_found(async_client_with_db):
    """Test that fetching messages for a non-existent session returns 404."""
    response = await async_client_with_db.get("/v1/db/sessions/nonexistent/messages")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_db_delete_session_not_found(async_client_with_db):
    """Test that deleting a non-existent DB session returns 404."""
    response = await async_client_with_db.delete("/v1/db/sessions/nonexistent")
    assert response.status_code == 404
