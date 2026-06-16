"""Pydantic models shared across the API."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


PermissionMode = Literal["default", "acceptEdits", "bypassPermissions", "plan"]


class SessionCreateRequest(BaseModel):
    """Options for creating a new agent session."""

    cwd: Optional[str] = None
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    permission_mode: PermissionMode = "default"
    allowed_tools: Optional[list[str]] = None
    disallowed_tools: Optional[list[str]] = None
    mcp_servers: Optional[dict[str, Any]] = None
    max_turns: Optional[int] = None
    include_partial_messages: bool = True
    extra_args: Optional[dict[str, Any]] = None


class SessionInfo(BaseModel):
    session_id: str
    cwd: str
    model: str
    permission_mode: PermissionMode
    created_at: float
    status: Literal["idle", "running", "closed"]


class SessionListResponse(BaseModel):
    sessions: list[SessionInfo]


class StreamRequest(BaseModel):
    """A single turn sent to an existing or new session."""

    message: str
    session_id: Optional[str] = None

    # Options used only when creating a new session implicitly
    cwd: Optional[str] = None
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    permission_mode: Optional[PermissionMode] = None
    allowed_tools: Optional[list[str]] = None
    disallowed_tools: Optional[list[str]] = None
    mcp_servers: Optional[dict[str, Any]] = None
    max_turns: Optional[int] = None
    include_partial_messages: bool = True

    # UI-driven flags
    planning_mode: bool = False
    auto_approve: bool = False
    image_paths: Optional[list[str]] = None


class PermissionDecisionRequest(BaseModel):
    request_id: str
    approved: bool
    always: bool = False
    deny_message: Optional[str] = None


class InterruptRequest(BaseModel):
    session_id: str


class SetPermissionModeRequest(BaseModel):
    session_id: str
    permission_mode: PermissionMode


class SetModelRequest(BaseModel):
    session_id: str
    model: str


class PermissionRuleUpdate(BaseModel):
    session_id: str
    tool_name: str
    rule: Literal["allow", "ask", "deny"]


class HealthResponse(BaseModel):
    status: str
    sdk_available: bool
    sdk_version: Optional[str] = None
    active_sessions: int


class DBSessionInfo(BaseModel):
    """Persistent session info from the database."""
    id: str
    title: str
    cwd: str
    model: str
    permission_mode: PermissionMode
    status: str
    created_at: float
    updated_at: float


class DBSessionListResponse(BaseModel):
    sessions: list[DBSessionInfo]


class DBMessageInfo(BaseModel):
    """A persisted message from the database."""
    id: int
    session_id: str
    role: str
    type: str
    content: str
    tool_name: Optional[str] = None
    tool_id: Optional[str] = None
    tool_input: Optional[str] = None
    created_at: float


class DBMessageListResponse(BaseModel):
    messages: list[DBMessageInfo]


class ToolRuleInfo(BaseModel):
    """A single tool's rule, surfaced via /v1/tool-defaults and session views."""
    tool: str
    rule: Literal["allow", "ask", "deny"]


class ToolDefaultsResponse(BaseModel):
    """Canonical tool list and per-session effective rules."""
    tools: list[str]
    rules: list[ToolRuleInfo]
