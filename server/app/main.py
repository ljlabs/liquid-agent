from __future__ import annotations

import sys
import asyncio

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

"""
FastAPI wrapper around the Claude Agent SDK.
"""

import json
import time
from pathlib import Path
from typing import AsyncIterator
from contextlib import asynccontextmanager
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from .models import (
    DBMessageInfo,
    DBMessageListResponse,
    DBSessionInfo,
    DBSessionListResponse,
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
    ToolDefaultsResponse,
    ToolRuleInfo,
)
from .sessions import DEFAULT_TOOL_RULES, SDK_AVAILABLE, SessionManager
from . import database as db


SDK_VERSION = "custom-wrapper-v1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global manager
    manager = SessionManager()
    yield
    await manager.close_all()
    await db.close_db()

app = FastAPI(title="Claude Agent SDK Wrapper", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

manager: SessionManager = None


# ------------------------------------------------------------------
# Health
# ------------------------------------------------------------------

@app.get("/v1/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        sdk_available=SDK_AVAILABLE,
        sdk_version=SDK_VERSION,
        active_sessions=len(manager.list()),
    )


# ------------------------------------------------------------------
# In-memory session lifecycle
# ------------------------------------------------------------------

@app.post("/v1/sessions", response_model=SessionInfo)
async def create_session(req: SessionCreateRequest) -> SessionInfo:

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

    await db.create_session(
        session_id=session.session_id,
        title="New Session",
        cwd=session.cwd or "",
        model=session.model,
        permission_mode=session.permission_mode,
        tool_rules=json.dumps(session.get_tool_rules()),
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
        permission_mode=session.permission_mode,
        created_at=session.created_at,
        status=session.status,
    )


# ------------------------------------------------------------------
# Persistent session endpoints (SQLite)
# ------------------------------------------------------------------

@app.get("/v1/db/sessions", response_model=DBSessionListResponse)
async def list_db_sessions() -> DBSessionListResponse:
    sessions = await db.list_sessions()
    return DBSessionListResponse(sessions=[DBSessionInfo(**s) for s in sessions])


@app.get("/v1/db/sessions/{session_id}", response_model=DBSessionInfo)
async def get_db_session(session_id: str) -> DBSessionInfo:
    session = await db.get_session(session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    return DBSessionInfo(**session)


@app.delete("/v1/db/sessions/{session_id}")
async def delete_db_session(session_id: str) -> dict[str, bool]:
    await manager.close(session_id)
    deleted = await db.delete_session(session_id)
    if not deleted:
        raise HTTPException(404, "session not found")
    return {"deleted": True}


@app.get("/v1/db/sessions/{session_id}/messages", response_model=DBMessageListResponse)
async def get_db_messages(session_id: str) -> DBMessageListResponse:
    session = await db.get_session(session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    messages = await db.get_messages(session_id)
    return DBMessageListResponse(messages=[DBMessageInfo(**m) for m in messages])


# ------------------------------------------------------------------
# Mid-session controls
# ------------------------------------------------------------------

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
    if not session:
        raise HTTPException(404, "session not found")
    await session.set_permission_mode(req.permission_mode)
    await db.update_session(session_id, permission_mode=req.permission_mode)
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
    if not session:
        raise HTTPException(404, "session not found")
    session.set_tool_rule(req.tool_name, req.rule)
    rules = session.get_tool_rules()
    await db.update_session(session_id, tool_rules=json.dumps(rules))
    return {"tool": req.tool_name, "rule": req.rule}


@app.get("/v1/sessions/{session_id}/tool-rules", response_model=ToolDefaultsResponse)
async def get_session_tool_rules(session_id: str) -> ToolDefaultsResponse:
    session = manager.get(session_id)
    
    # If session not in memory, try to load from database
    if session is None:
        db_session = await db.get_session(session_id)
        if db_session and db_session.get("tool_rules"):
            try:
                rules_dict = json.loads(db_session["tool_rules"])
                return ToolDefaultsResponse(
                    tools=list(DEFAULT_TOOL_RULES.keys()),
                    rules=[ToolRuleInfo(tool=name, rule=rules_dict.get(name, "ask")) 
                           for name in DEFAULT_TOOL_RULES],
                )
            except Exception:
                pass
        # Fall back to defaults if session not found or no rules stored
        return ToolDefaultsResponse(
            tools=list(DEFAULT_TOOL_RULES.keys()),
            rules=[ToolRuleInfo(tool=name, rule=rule) for name, rule in DEFAULT_TOOL_RULES.items()],
        )
    
    rules = session.get_tool_rules()
    return ToolDefaultsResponse(
        tools=list(DEFAULT_TOOL_RULES.keys()),
        rules=[ToolRuleInfo(tool=name, rule=rules[name]) for name in DEFAULT_TOOL_RULES],
    )


@app.get("/v1/tool-defaults", response_model=ToolDefaultsResponse)
async def get_tool_defaults() -> ToolDefaultsResponse:
    return ToolDefaultsResponse(
        tools=list(DEFAULT_TOOL_RULES.keys()),
        rules=[ToolRuleInfo(tool=name, rule=rule) for name, rule in DEFAULT_TOOL_RULES.items()],
    )


# ------------------------------------------------------------------
# Permission responses
# ------------------------------------------------------------------

@app.post("/v1/permissions/respond")
async def respond_permission(req: PermissionDecisionRequest) -> dict[str, bool]:
    for session in manager.list():
        # Get pending permission before resolving to capture tool info
        pending = session._pending_permissions.get(req.request_id)
        
        if session.resolve_permission(req.request_id, req.approved, req.always, req.deny_message):
            # Log permission decision
            if pending:
                await db.log_permission(
                    session_id=session.session_id,
                    request_id=req.request_id,
                    tool_name=pending.tool_name,
                    tool_input=json.dumps(pending.tool_input) if pending.tool_input else None,
                    approved=req.approved,
                    always=req.always or False,
                )
            
            if req.always:
                rules = session.get_tool_rules()
                await db.update_session(session.session_id, tool_rules=json.dumps(rules))
            return {"resolved": True}
    raise HTTPException(404, "permission request not found (it may have already timed out)")


# ------------------------------------------------------------------
# Streaming chat endpoint
# ------------------------------------------------------------------

@app.post("/v1/sessions/stream")
async def stream(req: StreamRequest) -> StreamingResponse:

    db_session = await db.get_session(req.session_id) if req.session_id else None

    initial_tool_rules = None
    if db_session and db_session.get("tool_rules"):
        try:
            initial_tool_rules = json.loads(db_session["tool_rules"])
        except Exception:
            pass

    session = await manager.get_or_create(
        req.session_id,
        cwd=req.cwd,
        model=req.model,
        system_prompt=req.system_prompt,
        permission_mode=req.permission_mode or "default",
        allowed_tools=req.allowed_tools,
        disallowed_tools=req.disallowed_tools,
        tool_rules=initial_tool_rules,
        mcp_servers=req.mcp_servers,
        max_turns=req.max_turns,
        include_partial_messages=req.include_partial_messages,
    )

    if db_session is None:
        title = req.message[:60].strip() or "New Session"
        await db.create_session(
            session_id=session.session_id,
            title=title,
            cwd=session.cwd or "",
            model=session.model,
            permission_mode=session.permission_mode,
            tool_rules=json.dumps(session.get_tool_rules()),
        )
    elif db_session.get("title") == "New Session":
        new_title = req.message[:60].strip() or "New Session"
        await db.update_session(session.session_id, title=new_title, status="running")
    else:
        await db.update_session(session.session_id, status="running")

    await db.add_message(
        session_id=session.session_id,
        role="user",
        content=req.message,
    )

    # ── FIX: auto_approve sets the permission mode BEFORE run_turn, not
    # during the turn setup, and only on the session object (not via the
    # live SDK set_permission_mode which fires a mid-session SystemMessage).
    # We update session.permission_mode directly so the _can_use_tool
    # callback sees it, without sending a redundant set_permission_mode
    # command over the already-connected client.
    if req.auto_approve and session.permission_mode == "default":
        session.permission_mode = "acceptEdits"
        if session._options is not None:
            session._options.permission_mode = "acceptEdits"
        await db.update_session(session.session_id, permission_mode="acceptEdits")

    async def event_stream() -> AsyncIterator[str]:
        assistant_text_buffer = ""

        db_sess = await db.get_session(session.session_id)
        yield _sse({
            "type": "session",
            "session_id": session.session_id,
            "title": db_sess.get("title") if db_sess else "New Session",
            "cwd": session.cwd,
            "model": session.model,
            "permission_mode": session.permission_mode,
        })

        try:
            async for event in session.run_turn(
                req.message,
                planning_mode=req.planning_mode,
                image_paths=req.image_paths,
            ):
                yield _sse(event)

                etype = event.get("type")
                if etype == "text":
                    assistant_text_buffer += event.get("data", "")
                elif etype == "thinking":
                    if event.get("done"):
                        content = event.get("data", "")
                        if content:
                            await db.add_message(
                                session_id=session.session_id,
                                role="assistant",
                                type="thinking",
                                content=content,
                            )
                elif etype == "tool_use":
                    if assistant_text_buffer:
                        await db.add_message(
                            session_id=session.session_id,
                            role="assistant",
                            content=assistant_text_buffer,
                        )
                        assistant_text_buffer = ""
                    await db.add_message(
                        session_id=session.session_id,
                        role="assistant",
                        type="tool_use",
                        content=json.dumps(event.get("input", {}), default=str),
                        tool_name=event.get("name"),
                        tool_id=event.get("tool_id"),
                        tool_input=json.dumps(event.get("input", {}), default=str),
                    )
                elif etype == "tool_result":
                    await db.add_message(
                        session_id=session.session_id,
                        role="tool",
                        type="tool_result",
                        content=str(event.get("output", "")),
                        tool_id=event.get("tool_id"),
                    )
                elif etype == "tool_error":
                    await db.add_message(
                        session_id=session.session_id,
                        role="tool",
                        type="tool_error",
                        content=str(event.get("error", "")),
                        tool_id=event.get("tool_id"),
                    )
                elif etype == "result":
                    if assistant_text_buffer:
                        await db.add_message(
                            session_id=session.session_id,
                            role="assistant",
                            content=assistant_text_buffer,
                        )
                    await db.update_session(session.session_id, status="idle")

        except asyncio.CancelledError:
            await db.update_session(session.session_id, status="idle")
            raise
        except Exception as exc:  # noqa: BLE001
            yield _sse({"type": "error", "message": str(exc)})
            await db.update_session(session.session_id, status="idle")

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


# ------------------------------------------------------------------
# Static UI
# ------------------------------------------------------------------

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


# ------------------------------------------------------------------
# Local dev entrypoint
# ------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    uvicorn.run("app.main:app", host="0.0.0.0", port=8787, reload=True, loop="asyncio")