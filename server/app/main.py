"""
FastAPI wrapper around the Claude Agent SDK.

Endpoints map directly onto the actions the index.html UI takes:

  POST   /v1/sessions                 create a session, return its id
  GET    /v1/sessions                 list active sessions
  DELETE /v1/sessions/{session_id}    close a session
  POST   /v1/sessions/stream          send a message, stream the response (SSE)
  POST   /v1/sessions/{id}/interrupt  interrupt the current turn
  POST   /v1/sessions/{id}/permission-mode   change permission mode
  POST   /v1/sessions/{id}/model      change model
  POST   /v1/sessions/{id}/tool-rule  set an always-allow/deny rule for a tool
  POST   /v1/permissions/respond      resolve a pending permission_request
  GET    /v1/health                   health + SDK availability check

The SSE stream emits `data: <json>\n\n` lines matching the event shapes
the UI's handleStreamEvent() function expects (type: text, tool_use,
tool_result, tool_error, permission_request, planning_complete, result,
error).
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from .models import (
    HealthResponse,
    InterruptRequest,
    PermissionDecisionRequest,
    PermissionRuleUpdate,
    SessionCreateRequest,
    SessionInfo,
    SessionListResponse,
    SetModelRequest,
    SetPermissionModeRequest,
    StreamRequest,
)
from .sessions import SDK_AVAILABLE, SessionManager

try:
    import claude_agent_sdk

    SDK_VERSION = getattr(claude_agent_sdk, "__version__", "unknown")
except ImportError:  # pragma: no cover
    SDK_VERSION = None


app = FastAPI(title="Claude Agent SDK Wrapper", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = SessionManager()


# ----------------------------------------------------------------------
# Health
# ----------------------------------------------------------------------


@app.get("/v1/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        sdk_available=SDK_AVAILABLE,
        sdk_version=SDK_VERSION,
        active_sessions=len(manager.list()),
    )


# ----------------------------------------------------------------------
# Session lifecycle
# ----------------------------------------------------------------------


@app.post("/v1/sessions", response_model=SessionInfo)
async def create_session(req: SessionCreateRequest) -> SessionInfo:
    if not SDK_AVAILABLE:
        raise HTTPException(503, "claude_agent_sdk is not installed on the server")

    session = await manager.create(
        cwd=req.cwd,
        model=req.model,
        system_prompt=req.system_prompt,
        permission_mode=req.permission_mode,
        allowed_tools=req.allowed_tools,
        disallowed_tools=req.disallowed_tools,
        mcp_servers=req.mcp_servers,
        max_turns=req.max_turns,
        include_partial_messages=req.include_partial_messages,
    )
    return _session_info(session)


@app.get("/v1/sessions", response_model=SessionListResponse)
async def list_sessions() -> SessionListResponse:
    return SessionListResponse(sessions=[_session_info(s) for s in manager.list()])


@app.delete("/v1/sessions/{session_id}")
async def close_session(session_id: str) -> dict[str, bool]:
    ok = await manager.close(session_id)
    if not ok:
        raise HTTPException(404, "session not found")
    return {"closed": True}


def _session_info(session) -> SessionInfo:
    return SessionInfo(
        session_id=session.session_id,
        cwd=session.cwd or "",
        model=session.model,
        permission_mode=session.permission_mode,  # type: ignore[arg-type]
        created_at=session.created_at,
        status=session.status,  # type: ignore[arg-type]
    )


# ----------------------------------------------------------------------
# Mid-session controls
# ----------------------------------------------------------------------


@app.post("/v1/sessions/{session_id}/interrupt")
async def interrupt_session(session_id: str) -> dict[str, bool]:
    session = manager.get(session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    await session.interrupt()
    return {"interrupted": True}


@app.post("/v1/sessions/{session_id}/permission-mode")
async def set_permission_mode(session_id: str, req: SetPermissionModeRequest) -> dict[str, str]:
    session = manager.get(session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    await session.set_permission_mode(req.permission_mode)
    return {"permission_mode": session.permission_mode}


@app.post("/v1/sessions/{session_id}/model")
async def set_model(session_id: str, req: SetModelRequest) -> dict[str, str]:
    session = manager.get(session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    await session.set_model(req.model)
    return {"model": session.model}


@app.post("/v1/sessions/{session_id}/tool-rule")
async def set_tool_rule(session_id: str, req: PermissionRuleUpdate) -> dict[str, str]:
    session = manager.get(session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    session.set_tool_rule(req.tool_name, req.rule)
    return {"tool": req.tool_name, "rule": req.rule}


# ----------------------------------------------------------------------
# Permission responses (from the in-chat Allow/Deny buttons)
# ----------------------------------------------------------------------


@app.post("/v1/permissions/respond")
async def respond_permission(req: PermissionDecisionRequest) -> dict[str, bool]:
    # request_id is globally unique (uuid4), so scan all sessions.
    for session in manager.list():
        if session.resolve_permission(
            req.request_id, req.approved, req.always, req.deny_message
        ):
            return {"resolved": True}
    raise HTTPException(404, "permission request not found (it may have already timed out)")


# ----------------------------------------------------------------------
# Streaming chat endpoint
# ----------------------------------------------------------------------


@app.post("/v1/sessions/stream")
async def stream(req: StreamRequest) -> StreamingResponse:
    if not SDK_AVAILABLE:
        raise HTTPException(503, "claude_agent_sdk is not installed on the server")

    session = await manager.get_or_create(
        req.session_id,
        cwd=req.cwd,
        model=req.model,
        system_prompt=req.system_prompt,
        permission_mode=req.permission_mode or "default",
        allowed_tools=req.allowed_tools,
        disallowed_tools=req.disallowed_tools,
        mcp_servers=req.mcp_servers,
        max_turns=req.max_turns,
        include_partial_messages=req.include_partial_messages,
    )

    if req.auto_approve and session.permission_mode == "default":
        await session.set_permission_mode("acceptEdits")

    async def event_stream() -> AsyncIterator[str]:
        # Always tell the UI which session this turn belongs to first,
        # so a brand-new session gets adopted by the sidebar/session list.
        yield _sse(
            {
                "type": "session",
                "session_id": session.session_id,
                "cwd": session.cwd,
                "model": session.model,
                "permission_mode": session.permission_mode,
            }
        )

        try:
            async for event in session.run_turn(
                req.message,
                planning_mode=req.planning_mode,
                image_paths=req.image_paths,
            ):
                yield _sse(event)
        except asyncio.CancelledError:
            # Client disconnected; nothing more to send.
            raise
        except Exception as exc:  # noqa: BLE001
            yield _sse({"type": "error", "message": str(exc)})

        yield _sse({"type": "done"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


# ----------------------------------------------------------------------
# Shutdown
# ----------------------------------------------------------------------


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await manager.close_all()


# ----------------------------------------------------------------------
# Static UI (serves index.html at /) — mounted last so it doesn't shadow
# the /v1/* API routes above.
# ----------------------------------------------------------------------

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


# ----------------------------------------------------------------------
# Local dev entrypoint
# ----------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8787, reload=True)
