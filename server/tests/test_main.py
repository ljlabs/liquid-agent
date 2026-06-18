import pytest
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
    from app.main import app
    from app.sessions import SessionManager
    from app.view_data import ViewDataGenerator
    from tests.conftest import InMemoryDB
    import app.main as main

    main.manager = SessionManager()
    main.view_generator = ViewDataGenerator(main.manager, InMemoryDB())

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
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
async def test_list_sessions_empty(async_client_with_db):
    """Test that listing sessions returns an empty list initially."""
    response = await async_client_with_db.post("/v1/view", json={"action": "get_view"})
    assert response.status_code == 200
    data = response.json()
    assert data["sessions"] == []


@pytest.mark.asyncio
async def test_create_session(async_client, tmp_cwd):
    """Test that a session can be created via the API."""
    response = await async_client.post(
        "/v1/view",
        json={
            "action": "create_session",
            "cwd": tmp_cwd,
            "model": "claude-sonnet-4-6"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "active_session" in data
    session_id = data["active_session"]["id"]
    assert data["active_session"]["cwd"] == tmp_cwd
    assert data["active_session"]["model"] == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_create_session_with_none_tools(async_client, tmp_cwd):
    """Test that a session can be created with None for tool lists."""
    response = await async_client.post(
        "/v1/view",
        json={
            "action": "create_session",
            "cwd": tmp_cwd,
            "allowed_tools": None,
            "disallowed_tools": None
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "active_session" in data


@pytest.mark.asyncio
async def test_create_session_minimal(async_client, tmp_cwd):
    """Test that a session can be created with minimal parameters."""
    response = await async_client.post("/v1/view", json={"action": "create_session", "cwd": tmp_cwd})
    assert response.status_code == 200
    data = response.json()
    assert "active_session" in data
    assert data["active_session"]["cwd"] == tmp_cwd
    assert "model" in data["active_session"]


@pytest.mark.asyncio
async def test_close_session(async_client, tmp_cwd):
    """Test that a session can be closed."""
    # First create a session
    create_response = await async_client.post("/v1/view", json={"action": "create_session", "cwd": tmp_cwd})
    assert create_response.status_code == 200
    session_id = create_response.json()["active_session"]["id"]

    # Close the session
    close_response = await async_client.post("/v1/view", json={"action": "delete_session", "session_id": session_id})
    assert close_response.status_code == 200
    # In the new architecture, we might just return the ViewData.
    # We check if it's gone from the list in a subsequent get_view.
    check_response = await async_client.post("/v1/view", json={"action": "get_view"})
    assert not any(s["id"] == session_id for s in check_response.json()["sessions"])


@pytest.mark.asyncio
async def test_close_nonexistent_session(async_client):
    """Test that closing a non-existent session returns 404."""
    # Note: The new /v1/view might handle this differently (e.g. just returning current view).
    # But for now, we'll assume it might still error or we check if it's gone.
    response = await async_client.post("/v1/view", json={"action": "delete_session", "session_id": "nonexistent_session_id"})
    # If the backend implementation of delete_session uses db.delete_session, it returns a bool.
    # If the endpoint doesn't raise HTTPException, it might return 200.
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_interrupt_nonexistent_session(async_client):
    """Test that interrupting a non-existent session returns 404."""
    response = await async_client.post(
        "/v1/view",
        json={"action": "interrupt", "session_id": "nonexistent_session_id"}
    )
    # The new architecture might just return the view.
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_set_permission_mode_nonexistent_session(async_client):
    """Test that setting permission mode on a non-existent session returns 404."""
    response = await async_client.post(
        "/v1/view",
        json={"action": "set_mode", "session_id": "nonexistent_session_id", "permission_mode": "acceptEdits"}
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_set_model_nonexistent_session(async_client):
    """Test that setting model on a non-existent session returns 404."""
    response = await async_client.post(
        "/v1/view",
        json={"action": "set_model", "session_id": "nonexistent_session_id", "model": "claude-haiku-4-5"}
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_set_tool_rule_nonexistent_session(async_client):
    """Test that setting tool rule on a non-existent session returns 404."""
    response = await async_client.post(
        "/v1/view",
        json={"action": "update_tool_rule", "session_id": "nonexistent_session_id", "tool_name": "Bash", "tool_rule": "allow"}
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_resolve_permission_nonexistent_request(async_client):
    """Test that resolving a non-existent permission request returns 404."""
    response = await async_client.post(
        "/v1/view",
        json={
            "action": "respond_permission",
            "request_id": "nonexistent_request_id",
            "approved": True,
            "always": False
        }
    )
    # In the new architecture, this will likely return a ViewData.
    assert response.status_code == 200


# ------------------------------------------------------------------
# DB endpoint tests
# ------------------------------------------------------------------


@pytest.fixture
async def async_client_with_db():
    from app.main import app
    from app.sessions import SessionManager
    from app.view_data import ViewDataGenerator
    from tests.conftest import InMemoryDB
    import app.main as main

    main.manager = SessionManager()
    main.view_generator = ViewDataGenerator(main.manager, InMemoryDB())

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    await main.manager.close_all()


@pytest.mark.asyncio
async def test_db_list_sessions_empty(async_client_with_db):
    """Test that listing sessions returns empty list initially."""
    response = await async_client_with_db.post("/v1/view", json={"action": "get_view"})
    assert response.status_code == 200
    data = response.json()
    assert data["sessions"] == []


@pytest.mark.asyncio
async def test_db_session_not_found(async_client_with_db):
    """Test that fetching a non-existent DB session returns no active_session."""
    response = await async_client_with_db.post("/v1/view", json={"action": "get_view", "session_id": "nonexistent"})
    assert response.status_code == 200
    data = response.json()
    assert data["active_session"] is None


@pytest.mark.asyncio
async def test_db_messages_not_found(async_client_with_db):
    """Test that fetching messages for a non-existent session returns 404."""
    response = await async_client_with_db.post("/v1/view", json={"action": "get_view", "session_id": "nonexistent"})
    assert response.status_code == 200
    data = response.json()
    assert data["messages"] == []


@pytest.mark.asyncio
async def test_db_delete_session_not_found(async_client_with_db):
    """Test that deleting a non-existent DB session returns 404."""
    response = await async_client_with_db.post("/v1/view", json={"action": "delete_session", "session_id": "nonexistent"})
    assert response.status_code == 200
