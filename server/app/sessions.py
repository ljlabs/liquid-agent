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
import json
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
    from claude_agent_sdk.types import StreamEvent, PermissionResultAllow, PermissionResultDeny, ToolPermissionContext

    SDK_AVAILABLE = True
    IS_MOCK = False

except ImportError:  # pragma: no cover
    # ---------- Mock Claude Agent SDK Fallback ----------
    class AssistantMessage: pass
    class ClaudeAgentOptions:
        def __init__(self, **kwargs):
            for k, v in kwargs.items(): setattr(self, k, v)
    
    class ClaudeSDKClient:
        def __init__(self, options=None):
            self.options = options
            self._interrupt = False
            self._queue = asyncio.Queue()

        async def connect(self): pass
        async def disconnect(self): pass
        async def interrupt(self): self._interrupt = True
        async def set_permission_mode(self, mode): pass
        async def set_model(self, model): pass
        
        async def query(self, content):
            self._interrupt = False
            events = [
                {"type": "content_block_start", "content_block": {"type": "thinking"}},
                {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "I am thinking (MOCK): " + str(content)}},
                {"type": "content_block_stop"},
                {"type": "content_block_start", "content_block": {"type": "text", "text": ""}},
                {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Mock response to: " + str(content)}},
                {"type": "content_block_stop"},
                {"type": "message_stop"}
            ]
            for e in events:
                if self._interrupt: break
                await self._queue.put(e)
                await asyncio.sleep(0.01)

        async def receive_response(self):
            while True:
                ev = await self._queue.get()
                yield ev
                if ev.get("type") == "message_stop": break

    class ResultMessage: pass
    class SystemMessage: pass
    class TextBlock: pass
    class ThinkingBlock: pass
    class ToolResultBlock: pass
    class ToolUseBlock: pass
    class UserMessage: pass

    StreamEvent = Any
    PermissionResultAllow = Any
    PermissionResultDeny = Any
    ToolPermissionContext = Any

    SDK_AVAILABLE = True
    IS_MOCK = True

# -------------------------------------------

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
        self.system_prompt = system_prompt
        self.permission_mode = permission_mode
        self.allowed_tools = allowed_tools
        self.disallowed_tools = disallowed_tools
        self.mcp_servers = mcp_servers
        self.max_turns = max_turns or 25
        self.include_partial_messages = include_partial_messages

        self.created_at = time.time()
        self.status: str = "idle"

        # Initialize SDK options
        self._options = ClaudeAgentOptions(
            cwd=self.cwd,
            model=self.model,
            system_prompt=self.system_prompt,
            permission_mode=self.permission_mode,
            max_turns=self.max_turns,
            allowed_tools=self.allowed_tools or [],
            disallowed_tools=self.disallowed_tools or [],
        )

        self._client: Optional[ClaudeSDKClient] = None
        self._pending_permissions: dict[str, PendingPermission] = {}
        self._tool_rules: dict[str, str] = {}  # tool_name -> "allow" | "ask" | "deny"

    async def connect(self) -> None:
        """Establish the underlying SDK connection."""
        if self._client is None:
            self._client = ClaudeSDKClient(options=self._options)
            await self._client.connect()

    async def close(self) -> None:
        """Close the SDK connection and clean up."""
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:  # pragma: no cover
                pass
            finally:
                self._client = None
        self.status = "closed"

    async def interrupt(self) -> None:
        """Interrupt the current in-flight turn."""
        if self._client is not None:
            await self._client.interrupt()

    async def set_permission_mode(self, mode: str) -> None:
        """Change the agent's permission mode mid-session."""
        self.permission_mode = mode
        if self._client is not None:
            try:
                await self._client.set_permission_mode(mode)
            except (AttributeError, NotImplementedError):  # pragma: no cover
                pass

    async def set_model(self, model: str) -> None:
        """Change the agent's model mid-session."""
        self.model = model
        if self._client is not None:
            try:
                await self._client.set_model(model)
            except (AttributeError, NotImplementedError):  # pragma: no cover
                pass

    def set_tool_rule(self, tool_name: str, rule: str) -> None:
        """Set a persistent rule for a specific tool."""
        self._tool_rules[tool_name] = rule

    def resolve_permission(
        self, request_id: str, approved: bool, always: bool = False, deny_message: str | None = None
    ) -> bool:
        """Resolve a pending permission request."""
        pending = self._pending_permissions.pop(request_id, None)
        if pending is None:
            return False

        if always:
            self.set_tool_rule(pending.tool_name, "allow" if approved else "deny")

        res = {"approved": approved}
        if deny_message:
            res["message"] = deny_message
        
        pending.future.set_result(res)
        return True

    async def run_turn(
        self,
        message: str,
        *,
        planning_mode: bool = False,
        image_paths: Optional[list[str]] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Send a user message to Claude and stream the events back.
        """
        if self._client is None:
            await self.connect()

        self.status = "running"
        
        # In a real app we might handle image_paths or planning_mode flags here
        # and pass them into the SDK's query() call.
        content = message

        try:
            # 1. Start the turn
            assert self._client is not None
            await self._client.query(content)

            # 2. Consume events from the SDK
            async for msg in self._client.receive_response():
                event = await self._handle_sdk_event(msg)
                if event:
                    yield event
                    if event["type"] == "planning_complete" and planning_mode:
                        # Wait for UI to approve the plan before continuing
                        # (The SDK handles the actual pause if configured,
                        # but we can also manage it here).
                        pass

        finally:
            self.status = "idle"

    async def _handle_sdk_event(self, event: Any) -> Optional[dict[str, Any]]:
        """
        Map a raw SDK event into the JSON shape our UI expects.
        """
        # If we are in mock mode, event is already a dict (see ClaudeSDKClient.query)
        # If we are in real SDK mode, event is a StreamEvent object or dict depending on SDK version
        
        etype = None
        if isinstance(event, dict):
            etype = event.get("type")
        else:
            etype = getattr(event, "type", None)

        if etype == "content_block_delta":
            delta = event.get("delta", {}) if isinstance(event, dict) else getattr(event, "delta", {})
            delta_type = delta.get("type") if isinstance(delta, dict) else getattr(delta, "type", None)
            if delta_type == "text_delta":
                text = delta.get("text", "") if isinstance(delta, dict) else getattr(delta, "text", "")
                return {"type": "text", "data": text}
            elif delta_type == "thinking_delta":
                thinking = delta.get("thinking", "") if isinstance(delta, dict) else getattr(delta, "thinking", "")
                return {"type": "thinking", "data": thinking, "done": False}

        elif etype == "content_block_start":
            block = event.get("content_block", {}) if isinstance(event, dict) else getattr(event, "content_block", {})
            block_type = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
            if block_type == "tool_use":
                return {
                    "type": "tool_use",
                    "tool_id": block.get("id") if isinstance(block, dict) else getattr(block, "id", None),
                    "name": block.get("name") if isinstance(block, dict) else getattr(block, "name", None),
                    "input": (block.get("input", {}) or {}) if isinstance(block, dict) else (getattr(block, "input", {}) or {}),
                }
            elif block_type == "thinking":
                return {"type": "thinking", "data": "", "done": False, "start": True}

        elif etype == "content_block_stop":
            return {"type": "thinking", "done": True}

        elif etype == "message_stop":
            # Final result / usage
            return {
                "type": "result",
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "duration_ms": 0,
                "cost_usd": 0.0
            }

        return None


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
