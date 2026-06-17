"""
Custom session management layer replacing Claude Agent SDK.
"""

from __future__ import annotations

import asyncio
import time
import uuid
import logging
import json
import os
from pathlib import Path
from typing import Any, AsyncIterator, Optional, List, Dict

from .llm import CustomLLMWrapper
from .tools import execute_tool, get_tool_definitions

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SDK_AVAILABLE = True # Always True now as we use our own implementation

DEFAULT_AUTO_ALLOW_TOOLS = {"Read", "Glob", "Grep", "WebFetch"}

DEFAULT_TOOL_RULES: dict[str, str] = {
    "Read": "allow",
    "Write": "ask",
    "Replace": "ask",
    "Bash": "ask",
    "Glob": "allow",
    "Grep": "allow",
    "WebFetch": "allow",
    "Delegate": "ask",
}

def default_tool_rules() -> dict[str, str]:
    return dict(DEFAULT_TOOL_RULES)

from dataclasses import dataclass, field

class PermissionResultAllow:
    def __init__(self, behavior: str = "allow", **kwargs):
        self.behavior = behavior

class PermissionResultDeny:
    def __init__(self, behavior: str = "deny", message: str = "Denied", interrupt: bool = False, **kwargs):
        self.behavior = behavior
        self.message = message
        self.interrupt = interrupt

@dataclass
class PendingPermission:
    request_id: str
    tool_name: str
    tool_input: dict[str, Any]
    future: "asyncio.Future[dict[str, Any]]" = field(
        default_factory=lambda: asyncio.get_event_loop().create_future()
    )

class Session:
    """A single conversation session using CustomLLMWrapper."""

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
        self.cwd = cwd or os.getcwd()
        self.model = model or "gpt-4o"
        self.user_system_prompt = system_prompt
        self.permission_mode = permission_mode
        self.allowed_tools = allowed_tools
        self.disallowed_tools = disallowed_tools
        self.max_turns = max_turns or 25
        self.include_partial_messages = include_partial_messages

        self.created_at = time.time()
        self.status: str = "idle"
        self.messages: List[Dict[str, Any]] = []
        
        self._permission_events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._pending_permissions: dict[str, PendingPermission] = {}
        self._tool_rules = {k.lower(): v for k, v in DEFAULT_TOOL_RULES.items()}
        if tool_rules:
            for k, v in tool_rules.items():
                self._tool_rules[k.lower()] = v

        self._llm = CustomLLMWrapper(model=self.model)
        self._system_prompt_content = self._load_system_prompt()
        self._interrupt_flag = False

    def _load_system_prompt(self) -> str:
        prompt_path = Path(__file__).parent.parent / "system_prompt.md"
        content = ""
        if prompt_path.exists():
            content = prompt_path.read_text(encoding="utf-8")
        
        if self.user_system_prompt:
            content += "\n\n" + self.user_system_prompt
        
        return content

    async def connect(self) -> None:
        logger.info(f"Session {self.session_id} connected")

    async def close(self) -> None:
        self.status = "closed"
        logger.info(f"Session {self.session_id} closed")

    async def interrupt(self) -> None:
        self._interrupt_flag = True
        logger.info(f"Interrupting session {self.session_id}")

    async def set_permission_mode(self, mode: str) -> None:
        self.permission_mode = mode

    async def set_model(self, model: str) -> None:
        self.model = model
        self._llm.model = model

    def set_tool_rule(self, tool_name: str, rule: str) -> None:
        self._tool_rules[tool_name.lower()] = rule

    def get_tool_rules(self) -> dict[str, str]:
        return {name: self._tool_rules.get(name.lower(), "ask") for name in DEFAULT_TOOL_RULES}

    async def _check_permission(
        self,
        tool_name: str,
        tool_input: dict[str, Any]
    ) -> bool:
        if self.permission_mode == "bypassPermissions":
            return True

        rule = self._tool_rules.get(tool_name.lower())
        if rule == "allow":
            return True
        if rule == "deny":
            return False

        if tool_name.lower() in {t.lower() for t in DEFAULT_AUTO_ALLOW_TOOLS} and rule != "ask":
            return True

        # Prompt the UI
        request_id = f"perm_{uuid.uuid4().hex[:8]}"
        pending = PendingPermission(
            request_id=request_id,
            tool_name=tool_name,
            tool_input=tool_input,
        )
        self._pending_permissions[request_id] = pending

        await self._permission_events.put({
            "type": "permission_request",
            "request_id": request_id,
            "tool": tool_name,
            "tool_input": tool_input,
            "display_name": tool_name,
            "description": f"Allow {tool_name}?",
            "title": f"Run {tool_name}",
        })

        result = await pending.future
        return result.get("approved", False)

    def resolve_permission(
        self,
        request_id: str,
        approved: bool,
        always: bool = False,
        deny_message: str | None = None,
    ) -> bool:
        pending = self._pending_permissions.pop(request_id, None)
        if pending is None:
            return False
        if always:
            self.set_tool_rule(pending.tool_name, "allow" if approved else "deny")
        res: dict[str, Any] = {"approved": approved}
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
        self.status = "running"
        self._interrupt_flag = False
        
        self.messages.append({"role": "user", "content": message})
        
        # Use Anthropic format (matches Claude Code)
        tool_format = "anthropic"
        
        logger.info(f"System prompt length: {len(self._system_prompt_content) if self._system_prompt_content else 0}")
        logger.info(f"System prompt preview: {self._system_prompt_content[:100] if self._system_prompt_content else 'None'}")
        
        turn_count = 0
        while turn_count < self.max_turns and not self._interrupt_flag:
            turn_count += 1
            
            assistant_content = ""
            tool_calls = []
            
            # Get response from LLM (Anthropic Messages API format)
            response = None
            async for chunk in self._llm.chat_completion(
                messages=self.messages,
                system=self._system_prompt_content,
                tools=get_tool_definitions(format=tool_format),
                stream=False  # Non-streaming for now
            ):
                if chunk.get("type") == "error":
                    yield chunk
                    return
                response = chunk
                break
            
            if not response:
                yield {"type": "error", "message": "No response from LLM"}
                return
            
            # Parse Anthropic Messages API response
            content_blocks = response.get("content", [])
            
            assistant_content = ""
            tool_uses = []
            
            for block in content_blocks:
                block_type = block.get("type")
                
                if block_type == "text":
                    text = block.get("text", "")
                    assistant_content += text
                    yield {"type": "text", "data": text}
                
                elif block_type == "tool_use":
                    tool_uses.append(block)

            logger.info(f"LLM Turn completed. Content length: {len(assistant_content)}, Tool uses: {len(tool_uses)}")

            if self._interrupt_flag:
                yield {"type": "text", "data": "\n[Interrupted]"}
                break

            # Add assistant message to history (Anthropic format)
            self.messages.append({
                "role": "assistant",
                "content": content_blocks
            })

            if not tool_uses:
                break

            # Handle tool calls
            tool_results = []
            for tool_use in tool_uses:
                tool_id = tool_use.get("id")
                tool_name = tool_use.get("name")
                tool_input = tool_use.get("input", {})

                yield {
                    "type": "tool_use",
                    "tool_id": tool_id,
                    "name": tool_name,
                    "input": tool_input
                }

                # Check permission
                allowed = False
                if self.permission_mode == "bypassPermissions":
                    allowed = True
                else:
                    rule = self._tool_rules.get(tool_name.lower())
                    if rule == "allow":
                        allowed = True
                    elif rule == "deny":
                        allowed = False
                    elif tool_name.lower() in {t.lower() for t in DEFAULT_AUTO_ALLOW_TOOLS} and rule != "ask":
                        allowed = True
                    else:
                        # Prompt the UI
                        request_id = f"perm_{uuid.uuid4().hex[:8]}"
                        pending = PendingPermission(
                            request_id=request_id,
                            tool_name=tool_name,
                            tool_input=tool_input,
                        )
                        self._pending_permissions[request_id] = pending

                        yield {
                            "type": "permission_request",
                            "request_id": request_id,
                            "tool": tool_name,
                            "tool_input": tool_input,
                            "display_name": tool_name,
                            "description": f"Allow {tool_name}?",
                            "title": f"Run {tool_name}",
                        }

                        result = await pending.future
                        allowed = result.get("approved", False)
                
                if allowed:
                    result = await execute_tool(tool_name, tool_input, cwd=self.cwd)
                    if result.is_error:
                        yield {"type": "tool_error", "tool_id": tool_id, "error": result.error}
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": f"Error: {result.error}",
                            "is_error": True
                        })
                    else:
                        yield {"type": "tool_result", "tool_id": tool_id, "output": result.output}
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": result.output
                        })
                else:
                    yield {"type": "tool_error", "tool_id": tool_id, "error": "Permission denied"}
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": "Error: Permission denied by user",
                        "is_error": True
                    })
            
            # Add tool results to messages in Anthropic format
            self.messages.append({
                "role": "user",
                "content": tool_results
            })

        self.status = "idle"
        yield {"type": "result", "num_turns": turn_count}

class SessionManager:
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
