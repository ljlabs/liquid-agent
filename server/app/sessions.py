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
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    logger.warning("claude_agent_sdk not found, using Mock implementation")
    class AssistantMessage: pass
    class ClaudeAgentOptions:
        def __init__(self, **kwargs):
            for k, v in kwargs.items(): setattr(self, k, v)
    
    class ClaudeSDKClient:
        def __init__(self, options=None):
            self.options = options
            self._interrupt = False
            self._queue = asyncio.Queue()

        async def connect(self): logger.info("Mock connect")
        async def disconnect(self): logger.info("Mock disconnect")
        async def interrupt(self): 
            logger.info("Mock interrupt")
            self._interrupt = True
        async def set_permission_mode(self, mode): logger.info(f"Mock set_permission_mode: {mode}")
        async def set_model(self, model): logger.info(f"Mock set_model: {model}")
        
        async def query(self, content):
            logger.info(f"Mock query: {content}")
            self._interrupt = False
            
            # Simulated tool trigger: "mock_tool: <tool_name>"
            if isinstance(content, str) and content.startswith("mock_tool:"):
                parts = content.split(":")
                tool_name = parts[1].strip()
                tool_input = {"command": "echo hello"}
                tool_id = "mock_tool_id"
                
                await self._queue.put({
                    "type": "content_block_start",
                    "content_block": {
                        "type": "tool_use",
                        "id": tool_id,
                        "name": tool_name,
                        "input": tool_input
                    }
                })
                await asyncio.sleep(0.01)
                
                class MockContext:
                    display_name = tool_name
                    description = f"Mock description for {tool_name}"
                    title = f"Run {tool_name}"
                
                context = MockContext()
                
                if self.options and getattr(self.options, "can_use_tool", None):
                    try:
                        perm_res = await self.options.can_use_tool(tool_name, tool_input, context)
                        is_allowed = False
                        if isinstance(perm_res, PermissionResultAllow) or type(perm_res).__name__ == "PermissionResultAllow":
                            is_allowed = True
                        elif hasattr(perm_res, "approved"):
                            is_allowed = perm_res.approved
                            
                        if is_allowed:
                            await self._queue.put({
                                "type": "tool_result",
                                "tool_id": tool_id,
                                "output": "mock tool output success"
                            })
                        else:
                            msg = getattr(perm_res, "message", "Denied by user")
                            await self._queue.put({
                                "type": "tool_error",
                                "tool_id": tool_id,
                                "error": f"Error: {msg}"
                            })
                    except Exception as e:
                        await self._queue.put({
                            "type": "tool_error",
                            "tool_id": tool_id,
                            "error": str(e)
                        })
                else:
                    await self._queue.put({
                        "type": "tool_result",
                        "tool_id": tool_id,
                        "output": "mock tool output success (no perm check)"
                    })
                
                await asyncio.sleep(0.01)
                await self._queue.put({"type": "message_stop"})
                return

            # Very minimal mock response
            events = [
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

# Canonical tool list shown in the UI sidebar. Each entry has the default
# rule applied to a fresh session: "allow" auto-passes, "ask" emits a
# permission_request, "deny" blocks the tool outright. The same list is
# served from the server so the UI renders these values rather than
# hardcoded markup.
DEFAULT_TOOL_RULES: dict[str, str] = {
    "Read": "allow",
    "Edit": "ask",
    "Write": "ask",
    "Bash": "ask",
    "WebFetch": "allow",
    "Grep": "allow",
}


def default_tool_rules() -> dict[str, str]:
    """Return a fresh copy of the default tool rules."""
    return dict(DEFAULT_TOOL_RULES)


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
        tool_rules: Optional[dict[str, str]] = None,
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

        # Queues for interleaving SDK events with permission events
        self._permission_events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._sdk_message_queue: asyncio.Queue[Any] = asyncio.Queue()
        self._reader_task: Optional[asyncio.Task] = None
        self._turn_complete = asyncio.Event()

        self._client: Optional[ClaudeSDKClient] = None
        self._pending_permissions: dict[str, PendingPermission] = {}
        # tool_name (lowercase) -> "allow" | "ask" | "deny". Seeded with
        # the canonical defaults so the server and UI agree on state
        # before the user touches anything.
        self._tool_rules = {k.lower(): v for k, v in DEFAULT_TOOL_RULES.items()}
        if tool_rules:
            for k, v in tool_rules.items():
                self._tool_rules[k.lower()] = v

        # Initialize SDK options
        self._options = ClaudeAgentOptions(
            cwd=self.cwd,
            model=self.model,
            system_prompt=self.system_prompt,
            permission_mode=self.permission_mode,
            max_turns=self.max_turns,
            allowed_tools=self._preapproved_tools(),
            disallowed_tools=self._disallowed_tools(),
            can_use_tool=self._can_use_tool,
        )

    async def connect(self) -> None:
        """Establish the underlying SDK connection."""
        if self._client is None:
            logger.info(f"Connecting to Claude SDK for session {self.session_id}...")
            self._client = ClaudeSDKClient(options=self._options)
            await self._client.connect()
            logger.info(f"Connected to Claude SDK for session {self.session_id}")

    async def close(self) -> None:
        """Close the SDK connection and clean up."""
        if self._client is not None:
            logger.info(f"Closing session {self.session_id}...")
            try:
                # Cancel the reader task first
                if self._reader_task and not self._reader_task.done():
                    self._reader_task.cancel()
                    try:
                        await self._reader_task
                    except asyncio.CancelledError:
                        pass
                await self._client.disconnect()
            except Exception as e:  # pragma: no cover
                logger.error(f"Error disconnecting session {self.session_id}: {e}")
            finally:
                self._client = None
        self.status = "closed"

    async def interrupt(self) -> None:
        """Interrupt the current in-flight turn."""
        if self._client is not None:
            logger.info(f"Interrupting turn for session {self.session_id}")
            await self._client.interrupt()

    async def set_permission_mode(self, mode: str) -> None:
        """Change the agent's permission mode mid-session."""
        self.permission_mode = mode
        if self._options is not None:
            self._options.permission_mode = mode
            # Refresh allowed/disallowed tools in case they depend on mode
            self._options.allowed_tools = self._preapproved_tools()
            self._options.disallowed_tools = self._disallowed_tools()

        if self._client is not None:
            logger.info(f"Setting permission mode to {mode} for session {self.session_id}")
            try:
                await self._client.set_permission_mode(mode)
            except (AttributeError, NotImplementedError):  # pragma: no cover
                pass

    async def set_model(self, model: str) -> None:
        """Change the agent's model mid-session."""
        self.model = model
        if self._client is not None:
            logger.info(f"Setting model to {model} for session {self.session_id}")
            try:
                await self._client.set_model(model)
            except (AttributeError, NotImplementedError):  # pragma: no cover
                pass

    def set_tool_rule(self, tool_name: str, rule: str) -> None:
        """Set a persistent rule for a specific tool and refresh SDK options."""
        self._tool_rules[tool_name.lower()] = rule
        # Re-sync the SDK's allow/deny lists so the harness immediately
        # reflects the new rule without waiting for a reconnect.
        if self._options is not None:
            self._options.allowed_tools = self._preapproved_tools()
            self._options.disallowed_tools = self._disallowed_tools()

    def get_tool_rules(self) -> dict[str, str]:
        """Return the current effective tool rules keyed by canonical tool name."""
        return {name: self._tool_rules.get(name.lower(), "ask") for name in DEFAULT_TOOL_RULES}

    def _preapproved_tools(self) -> list[str]:
        """Tools the SDK harness can run without consulting _can_use_tool."""
        explicit = set(self.allowed_tools or [])
        
        # Tools explicitly set to 'allow' by the user
        allowed_rules = {name for name, rule in self._tool_rules.items() if rule == "allow"}
        
        # Canonical auto-allow tools, but ONLY if they aren't explicitly set to 'ask' or 'deny'
        auto_allows = {t.lower() for t in DEFAULT_AUTO_ALLOW_TOOLS}
        for name, rule in self._tool_rules.items():
            if rule in ("ask", "deny") and name in auto_allows:
                auto_allows.remove(name)

        return sorted(explicit | allowed_rules | auto_allows)

    def _disallowed_tools(self) -> list[str]:
        """Tools the SDK harness must never run without explicit override."""
        explicit = set(self.disallowed_tools or [])
        # Tools explicitly set to 'deny' by the user
        denied_rules = {name for name, rule in self._tool_rules.items() if rule == "deny"}
        return sorted(explicit | denied_rules)

    async def _can_use_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        context: "ToolPermissionContext",
    ) -> "PermissionResultAllow | PermissionResultDeny":
        """
        SDK callback invoked when a tool needs permission approval.
        Emits a permission_request event to the UI and blocks until the
        UI responds via POST /v1/permissions/respond.
        """
        logger.info(f"Checking permission for {tool_name} in session {self.session_id}. Mode: {self.permission_mode}")

        # 1. Check global permission modes first
        if self.permission_mode == "bypassPermissions":
            return PermissionResultAllow()
        
        if self.permission_mode == "plan":
            # In plan mode, we only allow read-only tools
            if tool_name.lower() in {t.lower() for t in DEFAULT_AUTO_ALLOW_TOOLS}:
                return PermissionResultAllow()
            return PermissionResultDeny(message="Not allowed in plan mode", interrupt=False)

        # 2. Check explicit tool rules (case-insensitive keys)
        rule = self._tool_rules.get(tool_name.lower())
        if rule == "allow":
            return PermissionResultAllow()
        if rule == "deny":
            return PermissionResultDeny(message="Denied by tool rule", interrupt=False)
        
        # 3. Handle acceptEdits mode
        if self.permission_mode == "acceptEdits":
            # Auto-approve edits and common read tools
            if tool_name.lower() in {"edit", "write", "read", "glob", "grep", "webfetch"}:
                return PermissionResultAllow()

        # 4. Auto-allow read-only tools if not explicitly set to 'ask'
        if tool_name.lower() in {t.lower() for t in DEFAULT_AUTO_ALLOW_TOOLS} and rule != "ask":
            return PermissionResultAllow()

        # 5. Otherwise, prompt the UI
        request_id = f"perm_{uuid.uuid4().hex[:8]}"
        pending = PendingPermission(
            request_id=request_id,
            tool_name=tool_name,
            tool_input=tool_input,
        )
        self._pending_permissions[request_id] = pending

        # Push a permission_request event to the permission queue
        display_name = getattr(context, "display_name", None) or tool_name
        description = getattr(context, "description", None) or ""
        title = getattr(context, "title", None) or f"Run {tool_name}"

        logger.info(f"Emitting permission request {request_id} for tool {tool_name}")
        await self._permission_events.put({
            "type": "permission_request",
            "request_id": request_id,
            "tool": tool_name,
            "tool_input": tool_input,
            "display_name": display_name,
            "description": description,
            "title": title,
        })

        # Block until the UI responds
        result = await pending.future
        logger.info(f"Permission request {request_id} resolved: {result.get('approved')}")
        if result.get("approved"):
            return PermissionResultAllow()
        else:
            return PermissionResultDeny(
                message=result.get("message", "Denied by user"),
                interrupt=False,
            )

    async def _start_reader(self) -> None:
        """Per-turn reader: reads SDK messages and feeds them into the queue until turn complete."""
        try:
            async for msg in self._client.receive_response():
                logger.info(f"SDK reader received for session {self.session_id}: {type(msg).__name__ if not IS_MOCK else msg}")
                await self._sdk_message_queue.put(msg)
                # Signal turn complete on ResultMessage (real SDK) or message_stop (mock)
                if IS_MOCK:
                    if isinstance(msg, dict) and msg.get("type") == "message_stop":
                        self._turn_complete.set()
                elif isinstance(msg, ResultMessage):
                    self._turn_complete.set()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"SDK reader error for session {self.session_id}: {e}")
        finally:
            logger.info(f"SDK reader task ending for session {self.session_id}")

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
        logger.info(f"Starting turn for session {self.session_id}. Message: {message}")
        
        # Propagate planning mode to the SDK
        old_mode = self.permission_mode
        if planning_mode:
            await self.set_permission_mode("plan")

        # Drain any stale events and reset turn complete flag
        while not self._sdk_message_queue.empty():
            self._sdk_message_queue.get_nowait()
        while not self._permission_events.empty():
            self._permission_events.get_nowait()
        self._turn_complete.clear()

        # Start reader task BEFORE calling query() so we don't miss any messages
        self._reader_task = asyncio.create_task(self._start_reader())

        # Start query task so it doesn't block the event yielding loop
        query_task = asyncio.create_task(self._client.query(message))

        try:
            # Consume events until turn is complete
            while not self._turn_complete.is_set():
                # Check for pending permission events first
                # We use a small sleep if both queues are empty to avoid tight loop
                if self._permission_events.empty() and self._sdk_message_queue.empty():
                    await asyncio.sleep(0.01)
                
                while not self._permission_events.empty():
                    perm_event = self._permission_events.get_nowait()
                    yield perm_event

                try:
                    # Don't block forever here if there might be permission events
                    msg = await asyncio.wait_for(
                        self._sdk_message_queue.get(), timeout=0.1
                    )
                except asyncio.TimeoutError:
                    continue

                logger.info(f"Turn response for session {self.session_id}. Message: {msg}")
                events = self._handle_sdk_event(msg)
                for event in events:
                    yield event

            # Wait for both tasks to complete
            await asyncio.gather(self._reader_task, query_task)

            # Drain any remaining events after ResultMessage
            while not self._permission_events.empty():
                perm_event = self._permission_events.get_nowait()
                yield perm_event

            while not self._sdk_message_queue.empty():
                msg = self._sdk_message_queue.get_nowait()
                events = self._handle_sdk_event(msg)
                for event in events:
                    yield event

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Turn error for session {self.session_id}: {e}")
            raise e
        finally:
            if planning_mode:
                await self.set_permission_mode(old_mode)
            self.status = "idle"
            logger.info(f"Turn complete for session {self.session_id}")

    def _handle_sdk_event(self, event: Any) -> list[dict[str, Any]]:
        """
        Map a raw SDK event into a list of JSON shapes our UI expects.
        Returns a list because one AssistantMessage can contain multiple content blocks.
        """
        results: list[dict[str, Any]] = []

        # Handle real SDK objects first
        if not IS_MOCK:
            if isinstance(event, AssistantMessage):
                for block in event.content:
                    if isinstance(block, TextBlock):
                        if block.text:
                            results.append({"type": "text", "data": block.text})
                    elif isinstance(block, ThinkingBlock):
                        thinking = getattr(block, "thinking", "")
                        if thinking:
                            results.append({"type": "thinking", "data": thinking, "done": True})
                    elif isinstance(block, ToolUseBlock):
                        results.append({
                            "type": "tool_use",
                            "tool_id": block.id,
                            "name": block.name,
                            "input": block.input,
                        })
                    elif isinstance(block, ToolResultBlock):
                        is_error = getattr(block, "is_error", False)
                        content = block.content or ""
                        if isinstance(content, list):
                            content = " ".join(str(c) for c in content)
                        results.append({
                            "type": "tool_error" if is_error else "tool_result",
                            "tool_id": block.tool_use_id,
                            **({"error": str(content)} if is_error else {"output": str(content)}),
                        })
                return results

            if isinstance(event, ResultMessage):
                return [{
                    "type": "result",
                    "usage": event.usage,
                    "duration_ms": event.duration_ms,
                    "cost_usd": event.total_cost_usd,
                    "num_turns": event.num_turns,
                    "stop_reason": event.stop_reason,
                    "is_error": event.is_error
                }]

            if isinstance(event, SystemMessage):
                return [{"type": "system", "subtype": event.subtype, "data": event.data}]

            if isinstance(event, UserMessage):
                # UserMessage carries ToolResultBlocks after the harness executes tools
                if hasattr(event, "content") and event.content:
                    for block in event.content:
                        if isinstance(block, ToolResultBlock):
                            is_error = getattr(block, "is_error", False)
                            content = block.content or ""
                            if isinstance(content, list):
                                content = " ".join(str(c) for c in content)
                            results.append({
                                "type": "tool_error" if is_error else "tool_result",
                                "tool_id": block.tool_use_id,
                                **({"error": str(content)} if is_error else {"output": str(content)}),
                            })
                return results

        # Handle dict-based events (deltas, or mock events)
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
                results.append({"type": "text", "data": text})
            elif delta_type == "thinking_delta":
                thinking = delta.get("thinking", "") if isinstance(delta, dict) else getattr(delta, "thinking", "")
                results.append({"type": "thinking", "data": thinking, "done": False})

        elif etype == "content_block_start":
            block = event.get("content_block", {}) if isinstance(event, dict) else getattr(event, "content_block", {})
            block_type = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
            if block_type == "tool_use":
                results.append({
                    "type": "tool_use",
                    "tool_id": block.get("id") if isinstance(block, dict) else getattr(block, "id", None),
                    "name": block.get("name") if isinstance(block, dict) else getattr(block, "name", None),
                    "input": (block.get("input", {}) or {}) if isinstance(block, dict) else (getattr(block, "input", {}) or {}),
                })
            elif block_type == "thinking":
                results.append({"type": "thinking", "data": "", "done": False, "start": True})

        elif etype == "content_block_stop":
            results.append({"type": "thinking", "done": True})

        elif etype == "message_stop":
            results.append({"type": "done"})

        elif etype == "tool_result":
            results.append({
                "type": "tool_result",
                "tool_id": event.get("tool_id"),
                "output": event.get("output", "")
            })

        elif etype == "tool_error":
            results.append({
                "type": "tool_error",
                "tool_id": event.get("tool_id"),
                "error": event.get("error", "")
            })

        return results


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
