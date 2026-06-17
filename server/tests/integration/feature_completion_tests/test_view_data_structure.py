"""Tests: ViewData structure and field validation."""

import pytest
from .conftest import create_session, get_view


@pytest.mark.asyncio
async def test_view_data_top_level_fields(client):
    """ViewData has all required top-level fields."""
    view = await get_view(client)
    assert view["type"] == "view"
    assert "active_session" in view
    assert "sessions" in view
    assert "ui_state" in view
    assert "messages" in view
    assert "pending_actions" in view
    assert "tool_rules" in view
    assert "files" in view
    assert "usage" in view
    assert "tool_call_log" in view
    assert "session_log" in view
    assert "available_models" in view


@pytest.mark.asyncio
async def test_ui_state_structure(client):
    """UIState has all required fields with correct types."""
    sid = await create_session(client)
    view = await get_view(client, sid)
    ui = view["ui_state"]
    assert isinstance(ui["streaming"], bool)
    assert isinstance(ui["awaiting_approval"], bool)
    assert ui["mode"] in ("plan", "acceptEdits", "default")
    assert isinstance(ui["turn_tag"], str)
    assert isinstance(ui["should_attach"], bool)


@pytest.mark.asyncio
async def test_session_view_structure(client):
    """SessionView has all required fields."""
    sid = await create_session(client)
    view = await get_view(client, sid)
    s = view["active_session"]
    assert isinstance(s["id"], str)
    assert isinstance(s["title"], str)
    assert isinstance(s["cwd"], str)
    assert isinstance(s["model"], str)
    assert isinstance(s["permission_mode"], str)
    assert s["status"] in ("idle", "running", "closed")
    assert s["permission_status"] in ("none", "awaiting_approval", "awaiting_planning", None)
    assert isinstance(s["created_at"], float)
    assert isinstance(s["updated_at"], float)
    assert isinstance(s["turn_count"], int)


@pytest.mark.asyncio
async def test_session_list_item_structure(client):
    """SessionListItem has required fields."""
    sid = await create_session(client)
    view = await get_view(client)
    items = view["sessions"]
    assert len(items) >= 1
    item = next(i for i in items if i["id"] == sid)
    assert isinstance(item["id"], str)
    assert isinstance(item["title"], str)
    assert isinstance(item["updated_at"], float)
    assert isinstance(item["status"], str)
    assert isinstance(item["message_count"], int)


@pytest.mark.asyncio
async def test_tool_rule_view_structure(client):
    """ToolRuleView has tool and rule fields."""
    sid = await create_session(client)
    view = await get_view(client, sid)
    assert len(view["tool_rules"]) > 0
    for rule in view["tool_rules"]:
        assert isinstance(rule["tool"], str)
        assert rule["rule"] in ("allow", "ask", "deny")


@pytest.mark.asyncio
async def test_files_structure(client):
    """Files view has changed and recently_read lists."""
    sid = await create_session(client)
    view = await get_view(client, sid)
    assert isinstance(view["files"]["changed"], list)
    assert isinstance(view["files"]["recently_read"], list)


@pytest.mark.asyncio
async def test_usage_structure(client):
    """Usage view has token and context window fields."""
    sid = await create_session(client)
    view = await get_view(client, sid)
    u = view["usage"]
    assert isinstance(u["input_tokens"], int)
    assert isinstance(u["output_tokens"], int)
    assert isinstance(u["estimated_cost"], float)
    assert isinstance(u["wall_time_seconds"], float)
    cw = u["context_window"]
    assert isinstance(cw["used"], int)
    assert isinstance(cw["max"], int)
    assert isinstance(cw["percentage"], float)


@pytest.mark.asyncio
async def test_tool_call_log_structure(client):
    """Tool call log is a list."""
    sid = await create_session(client)
    view = await get_view(client, sid)
    assert isinstance(view["tool_call_log"], list)


@pytest.mark.asyncio
async def test_session_log_structure(client):
    """Session log is a list."""
    sid = await create_session(client)
    view = await get_view(client, sid)
    assert isinstance(view["session_log"], list)


@pytest.mark.asyncio
async def test_available_models_in_get_view(client):
    """available_models is present and contains expected model names."""
    view = await get_view(client)
    models = view["available_models"]
    assert isinstance(models, list)
    assert len(models) > 0
    assert all(isinstance(m, str) for m in models)


@pytest.mark.asyncio
async def test_available_models_includes_mock_model(client):
    """available_models includes mock-model."""
    view = await get_view(client)
    assert "mock-model" in view["available_models"]


@pytest.mark.asyncio
async def test_available_models_includes_standard_models(client):
    """available_models includes standard Claude and GPT models."""
    view = await get_view(client)
    models = view["available_models"]
    assert "claude-sonnet-4-6" in models
    assert "claude-haiku-4-5" in models


@pytest.mark.asyncio
async def test_available_models_in_sse_stream(client):
    """available_models is present in SSE stream ViewData events."""
    import json
    import asyncio

    sid = await create_session(client)
    found_models = None

    async with client.stream("GET", f"/v1/view/stream?session_id={sid}") as resp:
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                data = json.loads(line[6:])
                if data.get("type") == "view":
                    if "available_models" in data:
                        found_models = data["available_models"]
                    break

    assert found_models is not None
    assert isinstance(found_models, list)
    assert len(found_models) > 0
    assert "mock-model" in found_models


@pytest.mark.asyncio
async def test_available_models_after_create_session(client):
    """available_models is still present after creating a session."""
    sid = await create_session(client)
    view = await get_view(client, sid)
    assert "available_models" in view
    assert len(view["available_models"]) > 0
