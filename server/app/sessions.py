"""
Session management layer around the Claude Agent SDK.

Each Session wraps a long-lived ClaudeSDKClient connection so the UI can:
  - send messages and stream responses (text deltas, tool use, tool
    results, thinking blocks, result/usage info) over SSE
  - receive permission_request events when a tool needs approval, and
    respond to them asynchronously via a separate HTTP call
  - interrupt an in-flight turn
  - switch permission mode / model mid-session
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

try:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        ResultMessage,
        SystemMessage,
        TextBlock,
        ThinkingBlock,
        ToolResultBlock,
        ToolUseBlock,
        UserMessage,
    )

    SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - allows the server to boot for /v1/health
    SDK_AVAILABLE = False

    AssistantMessage = object  # type: ignore
    ClaudeAgentOptions = None  # type: ignore
    ClaudeSDKClient = None  # type: ignore
    ResultMessage = object  # type: ignore
    SystemMessage = object  # type: ignore
    TextBlock = object  # type: ignore
    ThinkingBlock = object  # type: ignore
    ToolResultBlock = object  # type: ignore
    ToolUseBlock = object  # type: ignore
    UserMessage = object  # type: ignore

try:
    from claude_agent_sdk.types import StreamEvent
except ImportError:  # pragma: no cover - older SDK versions
    StreamEvent = None  # type: ignore

try:
    from claude_agent_sdk.types import (
        PermissionResultAllow,
        PermissionResultDeny,
        ToolPermissionContext,
    )
except ImportError:  # pragma: no cover
    PermissionResultAllow = None  # type: ignore
    PermissionResultDeny = None  # type: ignore
    ToolPermissionContext = None  # type: ignore


# Tools considered "always safe" -- never trigger a permission prompt
# regardless of permission_mode, mirroring the read-only tool set shown
# in the UI sidebar.
DEFAULT_AUTO_ALLOW_TOOLS = {"Read", "Glob", "Grep", "WebFetch", "WebSearch", "TodoWrite"}


@dataclass
class PendingPermission:
    """Tracks an in-flight permission request awaiting a UI decision."""

    request_id: str
    tool_name: str
    tool_input: dict[str, Any]
    future: "asyncio.Future[dict[str, Any]]" = field(
        default_factory=lambda: asyncio.get_event_loop().create_future()
    )


class Session:
    """A single conversation with the Claude Agent SDK."""

    def __init__(
        self,
        session_id: str,
        *,
        cwd: Optional[str] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        permission_mode: str = "default",
        allowed_tools: Optional[list[str]] = None,
        disallowed_tools: Optional[list[str]] = None,
        mcp_servers: Optional[dict[str, Any]] = None,
        max_turns: Optional[int] = None,
        include_partial_messages: bool = True,
    ) -> None:
        self.session_id = session_id
        self.cwd = cwd
        self.model = model or "claude-sonnet-4-6"
        self.permission_mode = permission_mode
        self.created_at = time.time()
        self.status: str = "idle"

        # Per-tool override rules set via the UI's permission badges.
        # e.g. {"Bash": "ask", "Edit": "allow", "Write": "deny"}
        self.tool_rules: dict[str, str] = {}

        self._pending_permissions: dict[str, PendingPermission] = {}
        self._lock = asyncio.Lock()
        self._closed = False

        if not SDK_AVAILABLE:
            raise RuntimeError(
                "claude_agent_sdk is not installed; install it with "
                "`pip install claude-agent-sdk` to create sessions."
            )

        self._options = ClaudeAgentOptions(
            cwd=cwd,
            model=self.model,
            system_prompt=system_prompt,
            permission_mode=permission_mode,
            allowed_tools=allowed_tools,
            disallowed_tools=disallowed_tools,
            mcp_servers=mcp_servers or {},
            max_turns=max_turns,
            include_partial_messages=include_partial_messages,
            can_use_tool=self._can_use_tool,
        )

        self._client: Optional[ClaudeSDKClient] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        if self._client is None:
            self._client = ClaudeSDKClient(options=self._options)
            await self._client.connect()

    async def close(self) -> None:
        self._closed = True
        if self._client is not None:
            await self._client.disconnect()
            self._client = None
        self.status = "closed"
        # Resolve any dangling permission futures so callers don't hang.
        for pending in self._pending_permissions.values():
            if not pending.future.done():
                pending.future.set_result({"approved": False, "always": False})

    # ------------------------------------------------------------------
    # Permission bridge
    # ------------------------------------------------------------------

    async def _can_use_tool(
        self, tool_name: str, input_data: dict[str, Any], context: Any
    ) -> Any:
        """
        Called by the SDK whenever a tool wants to run. We translate this
        into a permission_request event consumed by the UI via SSE, then
        block until the UI calls resolve_permission().
        """

        # Per-tool rule overrides from the sidebar take precedence.
        rule = self.tool_rules.get(tool_name)
        if rule == "allow":
            return self._allow()
        if rule == "deny":
            return self._deny("Denied by session tool rule")

        # Tools in the auto-allow set never prompt.
        if tool_name in DEFAULT_AUTO_ALLOW_TOOLS:
            return self._allow()

        # bypassPermissions / acceptEdits modes are handled by the SDK
        # itself for most tools, but we still keep this hook so explicit
        # per-tool "ask" rules can override a permissive session mode.
        if self.permission_mode == "bypassPermissions" and rule != "ask":
            return self._allow()

        if self.permission_mode == "plan":
            # Plan mode: only allow read-only inspection tools.
            if tool_name not in DEFAULT_AUTO_ALLOW_TOOLS:
                return self._deny(
                    "Plan mode is active: this tool will not run until the "
                    "plan is approved."
                )
            return self._allow()

        if self.permission_mode == "acceptEdits" and tool_name in (
            "Edit",
            "MultiEdit",
            "Write",
            "NotebookEdit",
        ) and rule != "ask":
            return self._allow()

        # Otherwise: ask the UI.
        request_id = str(uuid.uuid4())
        pending = PendingPermission(
            request_id=request_id, tool_name=tool_name, tool_input=input_data
        )
        self._pending_permissions[request_id] = pending

        # Surface to the event queue consumed by the SSE generator.
        await self._emit(
            {
                "type": "permission_request",
                "request_id": request_id,
                "tool": tool_name,
                "input": input_data,
            }
        )

        decision = await pending.future
        del self._pending_permissions[request_id]

        if decision.get("always"):
            self.tool_rules[tool_name] = "allow" if decision["approved"] else "deny"

        if decision["approved"]:
            return self._allow()
        return self._deny(decision.get("message") or "Denied by user")

    def _allow(self) -> Any:
        if PermissionResultAllow is not None:
            return PermissionResultAllow()
        return {"behavior": "allow"}

    def _deny(self, message: str) -> Any:
        if PermissionResultDeny is not None:
            return PermissionResultDeny(message=message)
        return {"behavior": "deny", "message": message}

    def resolve_permission(
        self, request_id: str, approved: bool, always: bool = False, message: str | None = None
    ) -> bool:
        pending = self._pending_permissions.get(request_id)
        if pending is None or pending.future.done():
            return False
        pending.future.set_result(
            {"approved": approved, "always": always, "message": message}
        )
        return True

    def set_tool_rule(self, tool_name: str, rule: str) -> None:
        self.tool_rules[tool_name] = rule

    # ------------------------------------------------------------------
    # Event queue (bridges async generator <-> can_use_tool callback)
    # ------------------------------------------------------------------

    _queue: "asyncio.Queue[dict[str, Any]]"

    async def _emit(self, event: dict[str, Any]) -> None:
        if not hasattr(self, "_queue"):
            self._queue = asyncio.Queue()
        await self._queue.put(event)

    # ------------------------------------------------------------------
    # Mid-session controls
    # ------------------------------------------------------------------

    async def interrupt(self) -> None:
        if self._client is not None:
            await self._client.interrupt()

    async def set_permission_mode(self, mode: str) -> None:
        self.permission_mode = mode
        if self._client is not None:
            try:
                await self._client.set_permission_mode(mode)
            except AttributeError:
                # Older SDKs may not expose this; the can_use_tool hook
                # above still enforces plan/acceptEdits behavior.
                pass

    async def set_model(self, model: str) -> None:
        self.model = model
        if self._client is not None:
            try:
                await self._client.set_model(model)
            except AttributeError:
                pass

    # ------------------------------------------------------------------
    # Main streaming turn
    # ------------------------------------------------------------------

    async def run_turn(
        self,
        message: str,
        *,
        planning_mode: bool = False,
        image_paths: Optional[list[str]] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Send `message` to the agent and yield UI-facing event dicts as the
        response streams in. Event shapes match what index.html expects:

          {"type": "text", "data": "..."}
          {"type": "thinking", "data": "...", "done": bool}
          {"type": "tool_use", "tool_id": "...", "name": "...", "input": {...}}
          {"type": "tool_result", "tool_id": "...", "output": "..."}
          {"type": "tool_error", "tool_id": "...", "error": "..."}
          {"type": "permission_request", "request_id": "...", "tool": "...", "input": {...}}
          {"type": "planning_complete", "plan": "..."}
          {"type": "result", "usage": {...}, "cost_usd": ..., "duration_ms": ..., "stop_reason": "..."}
          {"type": "error", "message": "..."}
        """

        async with self._lock:
            if self._client is None:
                await self.connect()

            self.status = "running"
            self._queue = asyncio.Queue()

            prompt = message
            if planning_mode:
                prompt = (
                    "Before making any changes, create a concise step-by-step "
                    "plan for the following request and present it for review. "
                    "Do not edit files or run commands that change state yet — "
                    "use only read-only tools to investigate.\n\n"
                    f"Request: {message}"
                )

            content: Any = prompt
            if image_paths:
                blocks: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
                for path in image_paths:
                    blocks.append(
                        {
                            "type": "image",
                            "source": {"type": "file", "path": path},
                        }
                    )
                content = blocks

            try:
                await self._client.query(content)
            except Exception as exc:  # noqa: BLE001
                yield {"type": "error", "message": str(exc)}
                self.status = "idle"
                return

            receive_task = asyncio.create_task(self._drain_receive())

            try:
                while True:
                    queue_task = asyncio.create_task(self._queue.get())
                    done, _ = await asyncio.wait(
                        {receive_task, queue_task}, return_when=asyncio.FIRST_COMPLETED
                    )

                    if queue_task in done:
                        yield queue_task.result()
                    else:
                        queue_task.cancel()

                    if receive_task in done:
                        result = receive_task.result()
                        # Flush any remaining queued events before exiting.
                        while not self._queue.empty():
                            yield self._queue.get_nowait()
                        if result is not None:
                            yield result
                        break
            finally:
                self.status = "idle"

            if planning_mode:
                yield {"type": "planning_complete"}

    async def _drain_receive(self) -> Optional[dict[str, Any]]:
        """
        Consume messages from client.receive_response(), translating each
        into queue events. Returns the final 'result' event (or an error
        event) once the turn completes.
        """

        assert self._client is not None
        final_event: Optional[dict[str, Any]] = None

        async for msg in self._client.receive_response():
            if StreamEvent is not None and isinstance(msg, StreamEvent):
                await self._handle_stream_event(msg)
                continue

            if isinstance(msg, AssistantMessage):
                # Non-streaming fallback (include_partial_messages=False)
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        await self._emit({"type": "text", "data": block.text})
                    elif isinstance(block, ThinkingBlock):
                        await self._emit(
                            {"type": "thinking", "data": block.thinking, "done": True}
                        )
                    elif isinstance(block, ToolUseBlock):
                        await self._emit(
                            {
                                "type": "tool_use",
                                "tool_id": block.id,
                                "name": block.name,
                                "input": block.input,
                            }
                        )
                continue

            if isinstance(msg, UserMessage):
                # Tool results come back wrapped in a UserMessage.
                if isinstance(msg.content, list):
                    for block in msg.content:
                        if isinstance(block, ToolResultBlock):
                            if block.is_error:
                                await self._emit(
                                    {
                                        "type": "tool_error",
                                        "tool_id": block.tool_use_id,
                                        "error": _stringify_tool_content(block.content),
                                    }
                                )
                            else:
                                await self._emit(
                                    {
                                        "type": "tool_result",
                                        "tool_id": block.tool_use_id,
                                        "output": _stringify_tool_content(block.content),
                                    }
                                )
                continue

            if isinstance(msg, SystemMessage):
                await self._emit(
                    {"type": "system", "subtype": msg.subtype, "data": msg.data}
                )
                continue

            if isinstance(msg, ResultMessage):
                final_event = {
                    "type": "result",
                    "is_error": msg.is_error,
                    "stop_reason": getattr(msg, "stop_reason", None),
                    "num_turns": msg.num_turns,
                    "duration_ms": msg.duration_ms,
                    "cost_usd": getattr(msg, "total_cost_usd", None),
                    "usage": getattr(msg, "usage", None),
                    "result": getattr(msg, "result", None),
                }
                break

        return final_event

    async def _handle_stream_event(self, msg: Any) -> None:
        event = msg.event
        event_type = event.get("type")

        if event_type == "content_block_delta":
            delta = event.get("delta", {})
            delta_type = delta.get("type")
            if delta_type == "text_delta":
                await self._emit({"type": "text", "data": delta.get("text", "")})
            elif delta_type == "thinking_delta":
                await self._emit(
                    {"type": "thinking", "data": delta.get("thinking", ""), "done": False}
                )
            elif delta_type == "input_json_delta":
                # Partial tool-input JSON; UI shows the tool block once
                # content_block_start fires, so partial input deltas are
                # safe to ignore for rendering purposes.
                pass

        elif event_type == "content_block_start":
            block = event.get("content_block", {})
            if block.get("type") == "tool_use":
                await self._emit(
                    {
                        "type": "tool_use",
                        "tool_id": block.get("id"),
                        "name": block.get("name"),
                        "input": block.get("input", {}) or {},
                    }
                )
            elif block.get("type") == "thinking":
                await self._emit({"type": "thinking", "data": "", "done": False, "start": True})

        elif event_type == "content_block_stop":
            # No direct UI event needed; tool_result / final text handled
            # elsewhere. Could be used to mark a thinking block complete.
            pass


def _stringify_tool_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


class SessionManager:
    """In-memory registry of active sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()

    async def create(self, **kwargs: Any) -> Session:
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        session = Session(session_id, **kwargs)
        async with self._lock:
            self._sessions[session_id] = session
        await session.connect()
        return session

    def get(self, session_id: str) -> Optional[Session]:
        return self._sessions.get(session_id)

    async def get_or_create(self, session_id: Optional[str], **kwargs: Any) -> Session:
        if session_id:
            existing = self.get(session_id)
            if existing is not None:
                return existing
        return await self.create(**kwargs)

    def list(self) -> list[Session]:
        return list(self._sessions.values())

    async def close(self, session_id: str) -> bool:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        await session.close()
        return True

    async def close_all(self) -> None:
        for session_id in list(self._sessions.keys()):
            await self.close(session_id)
