# Expected Web UI Features

This document spec's all features the web UI is expected to support after the business logic refactor. Backend owns all state; frontend is a pure renderer consuming `ViewData` objects.

---

## 1. Backend API Contract (`/v1/view`)

### 1.1 Actions

| Action | Purpose | Required Fields | Optional Fields |
|---|---|---|---|
| `get_view` | Fetch current ViewData snapshot | — | `session_id`, `include_messages` |
| `create_session` | Create a new session | — | `session_id`, `model`, `cwd` |
| `delete_session` | Close and remove a session | `session_id` | — |
| `switch_session` | Switch active session (restores from DB) | `session_id` | — |
| `send_message` | Send a user message and start agent turn | `session_id`, `message` | — |
| `interrupt` | Interrupt a running agent turn | `session_id` | — |
| `respond_permission` | Approve or deny a pending tool permission | `session_id`, `request_id`, `approved` | `always`, `deny_message` |
| `set_mode` | Change permission mode | `session_id`, `permission_mode` | — |
| `set_model` | Change the LLM model | `session_id`, `model` | — |
| `update_tool_rule` | Change a tool's permission rule | `session_id`, `tool_name`, `tool_rule` | — |

### 1.2 Response Format

`POST /v1/view` returns a JSON `ViewData` object. `GET /v1/view/stream` returns an SSE stream of `ViewData` objects.

```json
{
  "type": "view",
  "active_session": {
    "id": "sess_abc123",
    "title": "Fix login bug",
    "cwd": "/path/to/project",
    "model": "claude-sonnet-4-6",
    "permission_mode": "default",
    "status": "idle|running|closed",
    "permission_status": "none|awaiting_approval|awaiting_planning",
    "created_at": 1718000000.0,
    "updated_at": 1718000060.0,
    "turn_count": 3,
    "current_pending_request": null
  },
  "sessions": [
    { "id": "sess_abc123", "title": "Fix login bug", "updated_at": 1718000060.0, "status": "idle", "message_count": 6 }
  ],
  "ui_state": {
    "streaming": false,
    "awaiting_approval": false,
    "mode": "default|plan|acceptEdits",
    "turn_tag": "Turn 3",
    "should_attach": false
  },
  "messages": [
    {
      "id": 0,
      "role": "user|assistant|tool",
      "type": "text|thinking|tool_use|tool_result|tool_error",
      "content": "Hello",
      "content_blocks": [
        { "type": "text|thinking", "content": "..." }
      ],
      "tool_name": "Bash",
      "tool_id": "toolu_abc",
      "tool_input": { "command": "pwd" },
      "status": "running|success|error|pending_approval",
      "created_at": 1718000000.0
    }
  ],
  "pending_actions": [
    {
      "request_id": "perm_abc123",
      "action_type": "permission",
      "tool_name": "Bash",
      "tool_input": { "command": "rm -rf /tmp/test" },
      "title": "Allow Bash?",
      "description": "Permission request for Bash"
    }
  ],
  "tool_rules": [
    { "tool": "Bash", "rule": "ask|allow|deny" }
  ],
  "files": {
    "changed": [
      { "path": "/src/main.py", "tool_name": "Edit", "timestamp": 1718000010.0 }
    ],
    "recently_read": [
      { "path": "/README.md", "tool_name": "Read", "timestamp": 1718000005.0 }
    ]
  },
  "usage": {
    "input_tokens": 12500,
    "output_tokens": 3200,
    "estimated_cost": 0.042,
    "wall_time_seconds": 45.2,
    "context_window": {
      "used": 15700,
      "max": 200000,
      "percentage": 7.85
    }
  },
  "tool_call_log": [
    {
      "tool_name": "Bash",
      "target": "pwd",
      "status": "success",
      "timestamp": 1718000010.0,
      "tool_id": "toolu_abc"
    }
  ],
  "session_log": [
    {
      "timestamp": 1718000010.0,
      "level": "info",
      "message": "Session started"
    }
  ]
}
```

#### Files
- `files.changed`: List of files modified during the session.
- `files.recently_read`: List of files read during the session.
- Deduplicated by path, most recent first.

#### Usage
- `usage.input_tokens`: Cumulative input tokens across all turns.
- `usage.output_tokens`: Cumulative output tokens across all turns.
- `usage.estimated_cost`: Estimated cost in USD based on model pricing.
- `usage.wall_time_seconds`: Elapsed seconds since session creation.
- `usage.context_window.used`: Current context window token count.
- `usage.context_window.max`: Maximum context window for the model.
- `usage.context_window.percentage`: `used / max * 100`.

#### Tool Call Log
- `tool_call_log`: Chronological list of all tool invocations.
- Each entry: `tool_name`, `target` (path or command excerpt), `status`, `timestamp`, `tool_id`.

#### Session Log
- `session_log`: Backend log entries for the session.
- Each entry: `timestamp`, `level` (info/warn/error), `message`.

---

## 2. Session Management

### 2.1 Create Session
- User clicks "New session" button in sidebar.
- Frontend sends `create_session` with the selected model.
- Backend creates in-memory session + DB record.
- ViewData returned with `active_session` populated.

### 2.2 Switch Session
- User clicks a session in the sidebar.
- Frontend sends `switch_session` with `session_id`.
- Backend restores session from DB if not in memory.
- ViewData returned with that session's messages and state.

### 2.3 Delete Session
- Backend supports `delete_session` action.
- Closes in-memory session and removes DB record.

### 2.4 Session List (Sidebar)
- Lightweight `SessionListItem` objects: `id`, `title`, `updated_at`, `status`, `message_count`.
- Active session highlighted.
- Click triggers `switch_session`.

---

## 3. Messaging

### 3.1 Send Message
- User types in textarea, presses Enter or clicks send.
- Frontend sends `send_message` with `session_id` and `message`.
- Backend creates `run_turn` as background task.
- Initial ViewData snapshot returned immediately.
- Subsequent ViewData updates arrive via SSE stream.

### 3.2 Receive Messages
- Messages rendered from `ViewData.messages` array.
- User messages: rendered with markdown.
- Assistant messages: rendered using `content_blocks` (pre-parsed `text` and `thinking` blocks). No frontend `<thought>` tag parsing.
- Tool messages: rendered as collapsible tool blocks with status and output.

### 3.3 Message Types
| Type | Description |
|---|---|
| `text` | Normal text content |
| `thinking` | Collapsible thinking block (parsed from `<thought>` tags by backend) |
| `tool_use` | Tool invocation with name, input, and status |
| `tool_result` | Successful tool output |
| `tool_error` | Failed tool output |

### 3.4 Message Status
- `running`: Tool call in progress.
- `success`: Tool completed successfully.
- `error`: Tool failed.
- `pending_approval`: Waiting for user permission decision.

---

## 4. Permissions

### 4.1 Permission Request Flow
1. LLM requests a tool that requires permission.
2. Backend emits `permission_request` event.
3. ViewData includes `pending_actions` with `action_type: "permission"`.
4. Frontend renders permission card with Allow / Always Allow / Deny buttons.
5. User clicks a button; frontend sends `respond_permission`.
6. Backend resolves the permission and continues the agent loop.

### 4.2 Permission Modes
| Mode | Behavior |
|---|---|
| `default` | Ask for permission on each tool use (except auto-allowed tools) |
| `acceptEdits` | Auto-approve edit tools; ask for destructive tools |
| `bypassPermissions` | Skip all permission prompts |
| `plan` | Read-only mode; no tool execution |

### 4.3 Permission Mode UI
- Dropdown in sidebar with all four modes.
- Mode pill in input toolbar cycles through plan → acceptEdits → default.
- Changing mode sends `set_mode` action.

### 4.4 First-Class Permission Status
- `SessionView.permission_status` is explicit: `"none"`, `"awaiting_approval"`, or `"awaiting_planning"`.
- Frontend does not infer permission state from `pending_request_id` presence.
- `ui_state.awaiting_approval` is `true` when `pending_actions` is non-empty.

---

## 5. Tool Rules

### 5.1 Default Rules
| Tool | Default Rule |
|---|---|
| Read | allow |
| Write | ask |
| Replace | ask |
| Bash | ask |
| Glob | allow |
| Grep | allow |
| WebFetch | allow |
| Delegate | ask |

### 5.2 Rule Display
- Tool rules rendered in sidebar under "Permission mode" section.
- Each rule shown as a badge: `allow` (green), `ask` (yellow), `deny` (red).
- Clicking a badge cycles through allow → ask → deny and sends `update_tool_rule`.

### 5.3 Rule Enforcement
- Backend enforces rules in `_can_use_tool` / permission check logic.
- `allow` skips the permission prompt entirely.
- `deny` immediately blocks the tool.
- `ask` triggers a permission request event.

---

## 6. SSE Stream (`/v1/view/stream`)

### 6.1 Connection Lifecycle
- Frontend opens `GET /v1/view/stream` on page load.
- Connection persists for session lifetime.
- On session switch, old connection closed, new one opened.

### 6.2 Events
| Event | Description |
|---|---|
| `view` (type) | Full `ViewData` object — the primary update mechanism |
| `heartbeat` | Sent every 30s to keep connection alive |
| `done` | Stream complete (agent turn finished or no active session) |
| `error` | Error occurred |

### 6.3 Auto-Attach
- `ui_state.should_attach` is `true` when session is `running` or has `pending_actions`.
- Frontend should auto-subscribe when `should_attach` is true.
- On page load, frontend checks `localStorage` for `activeSessionId` and sends `get_view`.

### 6.4 Reconnection
- On SSE error, frontend reconnects after 3 seconds.
- Reconnection preserves `currentSessionId`.

---

## 7. Page Refresh Resumption

### 7.1 localStorage Persistence
- Active session ID stored in `localStorage` under key `activeSessionId`.
- Updated on every session switch and ViewData received.

### 7.2 Auto-Reattach Flow
1. Page loads → `DOMContentLoaded` fires.
2. `connectViewStream()` opens SSE connection.
3. If `localStorage` has `activeSessionId`, frontend sends `get_view` with that ID.
4. Backend restores session from DB (messages, tool rules, pending permissions).
5. If session is `running`, `ui_state.should_attach` is `true` → frontend receives live updates.
6. If `pending_actions` exist, permission cards render immediately.

---

## 8. UI Components

### 8.1 Sidebar
- **New session button**: Creates a session with the selected model.
- **Session list**: Clickable items showing title and time ago.
- **Connection section**: Endpoint input, model dropdown, working directory.
- **Permission mode section**: Mode dropdown, tool rules list.
- **MCP servers section**: Placeholder (collapsed).
- **Options section**: Extended thinking, stream partial, persist transcript, max turns slider.
- **Footer**: Connection status dot, SDK version.

### 8.2 Main Panel
- **Header**: Breadcrumb (title / cwd), turn tag, session ID tag, export button.
- **Conversation**: Scrollable message list.
- **Input area**: Textarea with slash commands menu, mode pill, attach/image buttons, send button, character count, keyboard hints, stream status.

### 8.3 Right Panel

#### Files Tab
Tracks all files touched during the session, split into two lists:

**Changed files** (`#changed-files-list`):
- Files modified by Edit, Write, or Replace tool calls.
- Populated from tool_use events where `tool_name` is one of `Edit`, `Write`, `Replace`.
- Shows file path extracted from `tool_input.path`.

**Recently read** (`#recent-files-list`):
- Files accessed by Read, Glob, or Grep tool calls.
- Populated from tool_use events where `tool_name` is one of `Read`, `Glob`, `Grep`.
- Shows file path extracted from `tool_input.path` or `tool_input.pattern`.

Both lists deduplicate by path. Most recent at top.

#### Usage Tab
Tracks token usage and context window status for the active session.

**Context window** (`#ctx-used`, `#ctx-bar`):
- Shows used tokens vs. max context window as "used / max".
- Progress bar fill percentage = `(used / max) * 100`.
- Data sourced from LLM response `usage` fields or estimated from message count.

**Session totals** (`#tot-input`, `#tot-output`, `#tot-cost`, `#tot-time`):
- `Input tokens`: Total input tokens sent across all turns.
- `Output tokens`: Total output tokens received across all turns.
- `Cost`: Estimated cost based on token counts and model pricing.
- `Wall time`: Total elapsed time since session creation.

**Tool calls** (`#tool-calls-list`):
- List of all tool invocations in the session, ordered chronologically.
- Each entry shows: tool name, target (path/command), status (success/error/pending), duration if available.
- Derived from messages where `type == "tool_use"` and `type == "tool_result"`.

#### Logs Tab
Shows backend debug/info logs for the current session.

- Log entries streamed in real-time during the session.
- Each entry has: timestamp, level (info/warn/error), message.
- Useful for diagnosing LLM errors, permission failures, and tool execution issues.
- Content comes from backend session events of type `error` and general log output.

---

## 9. Slash Commands

| Command | Description |
|---|---|
| `/clear` | Clear conversation history |
| `/compact` | Compact context to free up space |
| `/resume` | Resume a previous session |
| `/permissions` | Edit tool permission rules |
| `/cost` | Show session token usage and cost |
| `/mcp` | Manage MCP server connections |

Slash commands shown in a dropdown menu when user types `/`.

---

## 10. Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Enter` | Send message |
| `Shift+Enter` | Newline in textarea |
| `Escape` | Interrupt running session |

---

## 11. Streaming State

- `ui_state.streaming` is `true` while the agent turn is running.
- Send button changes to a stop icon during streaming.
- Stream status text shows "streaming...", "awaiting approval...", or "idle".
- Textarea and send button disabled during `awaiting_approval`.
