"""
View Data Module - Generates structured Pydantic objects for frontend rendering.

This is the single source of truth for all data sent to the frontend.
The frontend is a pure renderer that consumes ViewData objects.
"""

from __future__ import annotations

import json
import re
import time
from typing import Optional, Literal
from pydantic import BaseModel


class ContentBlock(BaseModel):
    """Pre-parsed content block for assistant messages."""
    type: Literal["text", "thinking"]
    content: str


class MessageView(BaseModel):
    """Single message for display - structured, no parsing needed."""
    id: int
    role: Literal["user", "assistant", "tool"]
    type: Literal["text", "thinking", "tool_use", "tool_result", "tool_error"]
    content: str
    content_blocks: Optional[list[ContentBlock]] = None
    tool_name: Optional[str] = None
    tool_id: Optional[str] = None
    tool_input: Optional[dict] = None
    status: Optional[Literal["running", "success", "error", "pending_approval"]] = None
    created_at: float


class PendingAction(BaseModel):
    """Action requiring user decision."""
    request_id: str
    action_type: Literal["permission", "planning_approval"]
    tool_name: Optional[str] = None
    tool_input: Optional[dict] = None
    title: str
    description: str


class ToolRuleView(BaseModel):
    """Tool permission rule."""
    tool: str
    rule: Literal["allow", "ask", "deny"]


class SessionView(BaseModel):
    """Active session metadata with first-class status."""
    id: str
    title: str
    cwd: str
    model: str
    permission_mode: str
    status: Literal["idle", "running", "closed"]
    permission_status: Optional[Literal["none", "awaiting_approval", "awaiting_planning"]] = None
    created_at: float
    updated_at: float
    turn_count: int = 0
    current_pending_request: Optional[PendingAction] = None


class SessionListItem(BaseModel):
    """Lightweight session for sidebar."""
    id: str
    title: str
    updated_at: float
    status: str
    message_count: int = 0


class UIState(BaseModel):
    """Frontend UI state managed by backend."""
    streaming: bool = False
    awaiting_approval: bool = False
    mode: Literal["plan", "acceptEdits", "default"] = "default"
    turn_tag: str = "Turn 0"
    should_attach: bool = False


class FileEntry(BaseModel):
    """A file touched during the session."""
    path: str
    tool_name: str
    timestamp: float


class ContextWindow(BaseModel):
    """Context window usage."""
    used: int = 0
    max: int = 200000
    percentage: float = 0.0


class UsageData(BaseModel):
    """Token usage and cost for the session."""
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float = 0.0
    wall_time_seconds: float = 0.0
    context_window: ContextWindow = ContextWindow()


class ToolCallLogEntry(BaseModel):
    """A single tool invocation in the log."""
    tool_name: str
    target: str
    status: str
    timestamp: float
    tool_id: str


class SessionLogEntry(BaseModel):
    """A backend log entry for the session."""
    timestamp: float
    level: Literal["info", "warn", "error"]
    message: str


class ViewData(BaseModel):
    """Complete UI state sent to frontend."""
    type: Literal["view"] = "view"
    active_session: Optional[SessionView] = None
    sessions: list[SessionListItem] = []
    ui_state: UIState = UIState()
    messages: list[MessageView] = []
    pending_actions: list[PendingAction] = []
    tool_rules: list[ToolRuleView] = []
    files: dict[str, list[FileEntry]] = {"changed": [], "recently_read": []}
    usage: UsageData = UsageData()
    tool_call_log: list[ToolCallLogEntry] = []
    session_log: list[SessionLogEntry] = []
    available_models: list[str] = []


class ViewDataGenerator:
    """Generates ViewData from backend state."""

    def __init__(self, session_manager, database):
        self._manager = session_manager
        self._db = database

    async def generate(
        self,
        session_id: Optional[str] = None,
        include_messages: bool = True,
    ) -> ViewData:
        """Generate complete view data for current state."""
        active_session = None
        messages: list[MessageView] = []
        tool_rules: list[ToolRuleView] = []
        pending_actions: list[PendingAction] = []

        if session_id:
            session = self._manager.get(session_id)
            if session is not None:
                permission_status: Optional[str] = "none"
                current_pending: Optional[PendingAction] = None

                if session._pending_permissions:
                    permission_status = "awaiting_approval"
                    for req_id, pending in session._pending_permissions.items():
                        current_pending = PendingAction(
                            request_id=req_id,
                            action_type="permission",
                            tool_name=pending.tool_name,
                            tool_input=pending.tool_input,
                            title=f"Allow {pending.tool_name}?",
                            description=f"Permission request for {pending.tool_name}",
                        )
                        break

                db_session = await self._db.get_session(session_id)
                title = "New Session"
                updated_at = session.created_at
                if db_session:
                    title = db_session.get("title", "New Session")
                    updated_at = db_session.get("updated_at", session.created_at)

                turn_count = sum(1 for m in session.messages if m.get("role") == "user")

                active_session = SessionView(
                    id=session.session_id,
                    title=title,
                    cwd=session.cwd or "",
                    model=session.model,
                    permission_mode=session.permission_mode,
                    status=session.status,
                    permission_status=permission_status,
                    created_at=session.created_at,
                    updated_at=updated_at,
                    turn_count=turn_count,
                    current_pending_request=current_pending,
                )

                if include_messages:
                    messages = self._build_messages(session)

                tool_rules = self._build_tool_rules(session)
                pending_actions = self._build_pending_actions(session)

        sessions = await self._build_session_list()

        streaming = False
        awaiting = False
        mode = "default"
        turn_tag = "Turn 0"
        should_attach = False

        if active_session:
            streaming = active_session.status == "running"
            awaiting = len(pending_actions) > 0
            if active_session.permission_mode == "plan":
                mode = "plan"
            elif active_session.permission_mode == "acceptEdits":
                mode = "acceptEdits"
            turn_tag = f"Turn {active_session.turn_count}"
            should_attach = streaming or awaiting

        ui_state = UIState(
            streaming=streaming,
            awaiting_approval=awaiting,
            mode=mode,
            turn_tag=turn_tag,
            should_attach=should_attach,
        )

        files = self._build_files(messages)
        usage = self._build_usage(messages, active_session)
        tool_call_log = self._build_tool_call_log(messages)
        session_log = self._build_session_log(messages)

        available_models = self._get_available_models()

        return ViewData(
            active_session=active_session,
            sessions=sessions,
            ui_state=ui_state,
            messages=messages,
            pending_actions=pending_actions,
            tool_rules=tool_rules,
            files=files,
            usage=usage,
            tool_call_log=tool_call_log,
            session_log=session_log,
            available_models=available_models,
        )

    def _get_available_models(self) -> list[str]:
        """Return list of available model names."""
        return [
            "claude-opus-4-6",
            "claude-sonnet-4-6",
            "claude-haiku-4-5",
            "gpt-4o",
            "gpt-4o-mini",
            "gemma-4-31b",
            "mock-model"
        ]

    def _build_messages(self, session) -> list[MessageView]:
        """Convert session messages to view format with structured blocks."""
        messages: list[MessageView] = []
        for i, msg in enumerate(session.messages):
            content_blocks = None
            if msg.get("role") == "assistant":
                raw_content = msg.get("content")
                if isinstance(raw_content, list):
                    content_blocks = self._parse_content_blocks(raw_content)
                elif isinstance(raw_content, str) and raw_content:
                    content_blocks = self._parse_thought_string(raw_content)

            view_msg = MessageView(
                id=i,
                role=msg.get("role", "user"),
                type=self._get_message_type(msg),
                content=self._extract_content(msg),
                content_blocks=content_blocks,
                tool_name=msg.get("tool_name"),
                tool_id=msg.get("tool_id"),
                tool_input=msg.get("tool_input"),
                status=self._get_message_status(msg, session),
                created_at=msg.get("created_at", time.time()),
            )
            messages.append(view_msg)
        return messages

    def _parse_content_blocks(self, content: list) -> list[ContentBlock]:
        """Parse Anthropic content blocks into structured format."""
        blocks: list[ContentBlock] = []
        for block in content:
            if block.get("type") == "text":
                text = block.get("text", "")
                thought_blocks = self._parse_thought_string(text)
                blocks.extend(thought_blocks)
            elif block.get("type") == "thinking":
                blocks.append(ContentBlock(
                    type="thinking",
                    content=block.get("thinking", ""),
                ))
        return blocks

    def _parse_thought_string(self, text: str) -> list[ContentBlock]:
        """Parse <thought> tags from a string into structured blocks."""
        blocks: list[ContentBlock] = []
        thought_regex = re.compile(r"<thought>(.*?)</thought>")
        last_end = 0

        for match in thought_regex.finditer(text):
            if match.start() > last_end:
                segment = text[last_end:match.start()].strip()
                if segment:
                    blocks.append(ContentBlock(type="text", content=segment))
            blocks.append(ContentBlock(type="thinking", content=match.group(1).strip()))
            last_end = match.end()

        if last_end < len(text):
            remaining = text[last_end:].strip()
            if remaining:
                blocks.append(ContentBlock(type="text", content=remaining))

        if not blocks and text.strip():
            blocks.append(ContentBlock(type="text", content=text.strip()))

        return blocks

    def _get_message_type(self, msg: dict) -> str:
        """Determine the message type for display."""
        msg_type = msg.get("type", "text")
        if msg_type in ("text", "thinking", "tool_use", "tool_result", "tool_error"):
            return msg_type
        role = msg.get("role", "user")
        if role == "tool":
            return "tool_result"
        return "text"

    def _extract_content(self, msg: dict) -> str:
        """Extract string content from a message."""
        content = msg.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif block.get("type") == "thinking":
                        parts.append(f"<thought>{block.get('thinking', '')}</thought>")
            return "".join(parts)
        return str(content)

    def _get_message_status(self, msg: dict, session) -> Optional[str]:
        """Determine message status."""
        if msg.get("role") == "tool":
            if msg.get("type") == "tool_error":
                return "error"
            return "success"

        if msg.get("role") == "assistant":
            tool_id = msg.get("tool_id")
            if tool_id:
                for req_id, pending in session._pending_permissions.items():
                    return "pending_approval"
        return None

    def _build_pending_actions(self, session) -> list[PendingAction]:
        """Build list of pending actions from session."""
        actions: list[PendingAction] = []
        for req_id, pending in session._pending_permissions.items():
            actions.append(PendingAction(
                request_id=req_id,
                action_type="permission",
                tool_name=pending.tool_name,
                tool_input=pending.tool_input,
                title=f"Allow {pending.tool_name}?",
                description=f"Permission request for {pending.tool_name}",
            ))
        return actions

    def _build_tool_rules(self, session) -> list[ToolRuleView]:
        """Build tool rules list."""
        rules = session.get_tool_rules()
        return [ToolRuleView(tool=name, rule=rule) for name, rule in rules.items()]

    async def _build_session_list(self) -> list[SessionListItem]:
        """Build session list from both in-memory and database."""
        sessions: list[SessionListItem] = []
        seen_ids: set[str] = set()

        # First: in-memory sessions (authoritative for live state)
        for session in self._manager.list():
            seen_ids.add(session.session_id)
            msg_count = len(session.messages)
            db_session = await self._db.get_session(session.session_id)
            title = "New Session"
            updated_at = session.created_at
            if db_session:
                title = db_session.get("title", "New Session")
                updated_at = db_session.get("updated_at", session.created_at)
            sessions.append(SessionListItem(
                id=session.session_id,
                title=title,
                updated_at=updated_at,
                status=session.status,
                message_count=msg_count,
            ))

        # Then: database sessions not currently in memory
        db_sessions = await self._db.list_sessions()
        for db_sess in db_sessions:
            sid = db_sess.get("id", "")
            if sid in seen_ids:
                continue
            seen_ids.add(sid)
            msg_count = await self._db.get_message_count(sid)
            sessions.append(SessionListItem(
                id=sid,
                title=db_sess.get("title", "New Session"),
                updated_at=db_sess.get("updated_at", 0),
                status=db_sess.get("status", "idle"),
                message_count=msg_count,
            ))

        # Sort by updated_at descending
        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions

    def _build_files(self, messages: list[MessageView]) -> dict[str, list[FileEntry]]:
        """Build files tracking from messages."""
        changed: dict[str, FileEntry] = {}
        recently_read: dict[str, FileEntry] = {}

        write_tools = {"Write", "Replace", "Edit"}
        read_tools = {"Read", "Glob", "Grep"}

        for msg in messages:
            if msg.type == "tool_use" and msg.tool_name and msg.tool_input:
                tool_input = msg.tool_input
                if isinstance(tool_input, str):
                    try:
                        tool_input = json.loads(tool_input)
                    except Exception:
                        continue

                path = tool_input.get("path") or tool_input.get("pattern") or ""
                if not path:
                    continue

                entry = FileEntry(
                    path=path,
                    tool_name=msg.tool_name,
                    timestamp=msg.created_at,
                )

                if msg.tool_name in write_tools:
                    changed[path] = entry
                elif msg.tool_name in read_tools:
                    recently_read[path] = entry

        return {
            "changed": list(changed.values()),
            "recently_read": list(recently_read.values()),
        }

    def _build_usage(self, messages: list[MessageView], active_session) -> UsageData:
        """Build usage data from messages."""
        input_tokens = 0
        output_tokens = 0
        turn_count = 0

        for msg in messages:
            if msg.role == "user":
                input_tokens += max(1, len(msg.content) // 4)
            elif msg.role == "assistant":
                output_tokens += max(1, len(msg.content) // 4)
                turn_count += 1

        cost_per_1k_input = 0.003
        cost_per_1k_output = 0.015
        estimated_cost = (input_tokens / 1000 * cost_per_1k_input) + (output_tokens / 1000 * cost_per_1k_output)

        wall_time = 0.0
        if active_session:
            wall_time = time.time() - active_session.created_at

        used = input_tokens + output_tokens
        max_ctx = 200000
        percentage = (used / max_ctx * 100) if max_ctx > 0 else 0.0

        return UsageData(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=round(estimated_cost, 4),
            wall_time_seconds=round(wall_time, 1),
            context_window=ContextWindow(used=used, max=max_ctx, percentage=round(percentage, 2)),
        )

    def _build_tool_call_log(self, messages: list[MessageView]) -> list[ToolCallLogEntry]:
        """Build tool call log from messages."""
        log: list[ToolCallLogEntry] = []
        tool_results_by_id: dict[str, MessageView] = {}

        for msg in messages:
            if msg.role == "tool" and msg.tool_id:
                tool_results_by_id[msg.tool_id] = msg

        for msg in messages:
            if msg.type == "tool_use" and msg.tool_name:
                tool_input = msg.tool_input or {}
                if isinstance(tool_input, str):
                    try:
                        tool_input = json.loads(tool_input)
                    except Exception:
                        tool_input = {}

                target = str(tool_input.get("path") or tool_input.get("command") or tool_input.get("pattern") or "")[:60]

                result_msg = tool_results_by_id.get(msg.tool_id)
                if result_msg:
                    status = "error" if result_msg.type == "tool_error" else "success"
                else:
                    status = "running"

                log.append(ToolCallLogEntry(
                    tool_name=msg.tool_name,
                    target=target,
                    status=status,
                    timestamp=msg.created_at,
                    tool_id=msg.tool_id or "",
                ))

        return log

    def _build_session_log(self, messages: list[MessageView]) -> list[SessionLogEntry]:
        """Build session log from messages."""
        log: list[SessionLogEntry] = []
        for msg in messages:
            if msg.type == "tool_error":
                log.append(SessionLogEntry(
                    timestamp=msg.created_at,
                    level="error",
                    message=f"Tool {msg.tool_name or 'unknown'} failed: {msg.content[:200]}",
                ))
            elif msg.type == "tool_result":
                log.append(SessionLogEntry(
                    timestamp=msg.created_at,
                    level="info",
                    message=f"Tool {msg.tool_name or 'unknown'} completed",
                ))
        return log
