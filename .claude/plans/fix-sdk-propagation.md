# Plan: Fix Permission Requests, Tool Results, and Planning Mode Propagation

## Root Causes

### Issue 1: No tool input/output bubbles
The SDK's `receive_response()` yields `AssistantMessage` objects whose `.content` list can contain `ToolUseBlock` and `ToolResultBlock` alongside `TextBlock` and `ThinkingBlock`. The current `_handle_sdk_event` only extracts `TextBlock` from `AssistantMessage` and silently ignores `ToolUseBlock` and `ToolResultBlock`. This means:
- Tool use blocks are never emitted to the UI → no "running" tool bubbles
- Tool result blocks are never emitted → tool bubbles never update to "success"/"error"

### Issue 1b: No permission requests
The SDK handles permissions via a `can_use_tool` async callback on `ClaudeAgentOptions` — not via events in the stream. When a tool needs approval, the SDK calls `can_use_tool(tool_name, tool_input, context)` and awaits the result. The current code never sets this callback, so the SDK uses its default behavior (which auto-approves in `acceptEdits` mode, or blocks the CLI's own permission prompt in `default` mode — meaning the UI never sees a permission request).

### Issue 2: Planning mode not propagated
The SDK uses `permission_mode: "plan"` in `ClaudeAgentOptions` to activate plan mode. The current code accepts a `planning_mode: bool` flag from the UI but never maps it to the SDK's `permission_mode` option. The `ClaudeAgentOptions` already supports `permission_mode` (including `"plan"`), but it's only set during session creation and never updated when the user toggles planning mode.

## Changes

### 1. Handle ToolUseBlock and ToolResultBlock in `_handle_sdk_event`
**File**: `server/app/sessions.py`, method `Session._handle_sdk_event`

Currently the `AssistantMessage` branch only yields `TextBlock` content. Add handling for:
- `ToolUseBlock` → yield `{"type": "tool_use", "tool_id": block.id, "name": block.name, "input": block.input}`
- `ToolResultBlock` → yield `{"type": "tool_result" if not block.is_error else "tool_error", "tool_id": block.tool_use_id, "output": block.content}` (or `"error"` for `is_error=True`)
- `ThinkingBlock` → yield `{"type": "thinking", "data": block.thinking, "done": True}`

Since one `AssistantMessage` may contain multiple blocks, the handler must iterate and yield one dict per block (converting to a list and having the caller iterate).

### 2. Wire up `can_use_tool` callback for permission handling
**File**: `server/app/sessions.py`, method `Session.__init__` and `Session.connect`

Set `ClaudeAgentOptions.can_use_tool` to an async callback that:
1. Generates a `request_id`
2. Creates a `PendingPermission` future
3. Yields a `{"type": "permission_request", "request_id": ..., "tool": ..., "input": ...}` event to the stream
4. Awaits the future (which is resolved when the UI calls `POST /v1/permissions/respond`)
5. Returns `PermissionResultAllow()` or `PermissionResultDeny(message=...)` based on the UI decision

Implementation: Since `can_use_tool` is a callback (not yielding into the stream), we need to emit the permission_request event *outside* the normal event stream and have the run_turn loop be aware of it. The cleanest approach is to use an `asyncio.Queue` that the `can_use_tool` callback pushes events into, and have `run_turn` interleave SDK events with queue events.

Actually, a simpler approach: since the SDK's `receive_response()` is an async iterator that pauses while it waits for the `can_use_tool` callback to return, we can:
1. In the `can_use_tool` callback, set `self._pending_permission_event` to the permission request dict
2. Have `run_turn` check for pending permission events after each SDK event and yield them before continuing

But the cleanest approach is an `asyncio.Queue`:
- `can_use_tool` pushes a permission_request event to `self._permission_events: asyncio.Queue`
- `run_turn` uses `asyncio.wait` to consume from both the SDK stream and the permission queue simultaneously

### 3. Map planning_mode to permission_mode in the SDK
**File**: `server/app/sessions.py`

Two sub-changes:
a) **Session creation**: When `planning_mode=True` is passed during `run_turn`, update `self._options.permission_mode` to `"plan"` before calling `query()`.
b) **Mid-session toggle**: When the user clicks the mode pill to switch to plan mode, the UI should call `set_permission_mode("plan")` on the session (already supported), which updates the SDK client.

For `run_turn`, before calling `self._client.query(message)`:
- If `planning_mode` is True, set `self._options.permission_mode = "plan"` and call `self._client.set_permission_mode("plan")`
- Otherwise, restore to the stored `self.permission_mode`

## Test Plan
1. **Tool bubbles**: Send a prompt requiring tool use (e.g., "list files in the current directory"). Verify tool_use block appears with input, then tool_result block updates it to success with output.
2. **Permissions**: Set mode to "Default mode". Trigger a tool that needs approval (e.g., file write). Verify permission_request card appears, blocks execution, and resolves when Allow/Deny is clicked.
3. **Planning mode**: Click mode pill to "Plan mode". Send a prompt. Verify the agent runs in plan mode (readOnly behavior, planning_complete event).
