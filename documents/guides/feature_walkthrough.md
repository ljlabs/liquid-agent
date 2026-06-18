# Feature Walkthrough Guide

This guide provides an exhaustive inventory of every feature in the Model Containment application. Each feature is described with its expected behavior for use as a golden path test template.

---

## 1. Backend API & Communication

### 1.1 View Endpoint (`POST /v1/view`)
- Single unified endpoint for all frontend-to-backend communication.
- Accepts a `ViewRequest` with an `action` field dispatching to: `send_message`, `switch_session`, `create_session`, `delete_session`, `interrupt`, `respond_permission`, `set_mode`, `set_model`, `update_tool_rule`, `get_view`.
- Returns a complete `ViewData` snapshot as JSON after processing the action.
- The `include_messages` flag (default `true`) controls whether message history is included in the response.

### 1.2 View SSE Stream (`GET /v1/view/stream`)
- Persistent SSE connection for real-time state updates.
- Accepts optional `session_id` query parameter to attach to a specific session.
- On connection, sends an initial `ViewData` snapshot.
- Pushes updated `ViewData` snapshots whenever backend state changes.
- Sends heartbeat events every 30 seconds to prevent connection timeouts.
- Automatically closes with a `done` event when the session becomes idle and no queue is active.
- Reconnects to the correct session after page refresh using the stored `session_id`.

### 1.3 Health Endpoint (`GET /v1/health`)
- Returns `HealthResponse` with fields: `status` ("ok"), `sdk_available` (always `true`), `sdk_version`, `active_sessions` count.
- Used by the frontend to verify server connectivity.

### 1.4 SSE Event Format
- All SSE events are formatted as `data: {json}\n\n`.
- Event types emitted during a turn: `session`, `text`, `thinking`, `tool_use`, `tool_result`, `tool_error`, `permission_request`, `planning_complete`, `result`, `error`, `done`, `heartbeat`.
- The `session` event is emitted at the start of each stream with `session_id`, `title`, `cwd`, `model`, and `permission_mode`.

### 1.5 CORS Configuration
- CORS middleware allows all origins (`*`), all methods, and all headers.

### 1.6 Static File Serving
- The `static/` directory is mounted at `/` with `html=True`, serving the frontend UI directly.

---

## 2. Session Management

### 2.1 Session Creation (`POST /v1/sessions`)
- Creates an in-memory `Session` object and a persistent SQLite database record.
- Accepts options: `cwd`, `model`, `system_prompt`, `permission_mode`, `allowed_tools`, `disallowed_tools`, `mcp_servers`, `max_turns`, `include_partial_messages`.
- Generates a unique `session_id` in the format `sess_{uuid_hex_12}`.
- Default model is `"gpt-4o"`.
- Default permission mode is `"default"`.
- Default max turns is `25`.
- Returns `SessionInfo` with `session_id`, `cwd`, `model`, `permission_mode`, `created_at`, `status`.

### 2.2 Session Listing (`GET /v1/sessions`)
- Returns all in-memory sessions as a `SessionListResponse`.

### 2.3 Session Deletion (`DELETE /v1/sessions/{session_id}`)
- Removes the session from both in-memory storage and the database.
- Returns `{"closed": true}`.
- Returns 404 if session not found.

### 2.4 Session Get-or-Create
- `SessionManager.get_or_create()` lazily recreates a session from the database if it was evicted from memory (e.g., after page refresh).
- Restores `cwd`, `model`, `permission_mode`, and `tool_rules` from the database.
- Reconstructs the full message history from database records.
- Restores pending permissions from the `pending_permissions` table.

### 2.5 Session Status States
- `"idle"`: Session is not actively processing.
- `"running"`: Session is actively processing a turn.
- `"closed"`: Session has been terminated.
- Status transitions: `idle` → `running` (on turn start) → `idle` (on turn end or error).

### 2.6 Session Title Auto-Renaming
- When the first message is sent to a "New Session", the title is set to the first 60 characters of the user's message.
- Subsequent messages do not change the title.

---

## 3. Database Persistence (SQLite)

### 3.1 Database Schema
- **sessions** table: `id` (PK), `title`, `cwd`, `model`, `permission_mode`, `tool_rules` (JSON), `status`, `created_at`, `updated_at`.
- **messages** table: `id` (autoincrement PK), `session_id` (FK), `role`, `type`, `content`, `tool_name`, `tool_id`, `tool_input`, `pending_request_id`, `created_at`.
- **permissions** table: `id` (autoincrement PK), `session_id` (FK), `request_id`, `tool_name`, `tool_input`, `approved`, `always`, `created_at`.
- **pending_permissions** table: `id` (autoincrement PK), `session_id` (FK), `request_id`, `tool_name`, `tool_id`, `tool_input`, `created_at`.
- Indexes on `messages(session_id, id)`, `permissions(session_id, id)`, `pending_permissions(session_id)`.

### 3.2 Database Configuration
- Uses `aiosqlite` for async SQLite access.
- WAL journal mode enabled.
- Foreign keys enabled.
- Database file stored at `server/data/sessions.db`.
- Auto-creates parent directories if they don't exist.

### 3.3 Schema Migration
- Backwards-compatible: adds `tool_rules` column to `sessions` if missing.
- Backwards-compatible: adds `pending_request_id` column to `messages` if missing.
- Backwards-compatible: adds `tool_id` column to `pending_permissions` if missing.

### 3.4 Session CRUD
- `create_session()`: Inserts a new session with default values.
- `get_session()`: Fetches a single session by ID.
- `update_session()`: Updates arbitrary fields and bumps `updated_at`.
- `list_sessions()`: Returns up to 50 sessions ordered by `updated_at` descending.
- `delete_session()`: Deletes a session by ID, cascading to messages via foreign key.

### 3.5 Message CRUD
- `add_message()`: Inserts a message and bumps the parent session's `updated_at`.
- `get_messages()`: Returns all messages for a session ordered by `id`.
- `get_message_count()`: Returns the count of messages for a session.

### 3.6 Permission Persistence
- `store_pending_permission()`: Persists a pending permission request to survive page refresh.
- `remove_pending_permission()`: Removes a pending permission and clears `pending_request_id` on the associated tool_use message.
- `get_pending_permissions()`: Returns all pending permissions for a session.
- `log_permission()`: Logs a resolved permission decision (approved/denied, always flag).

### 3.7 Database Session Endpoints
- `GET /v1/db/sessions`: Lists all persistent sessions.
- `GET /v1/db/sessions/{session_id}`: Gets a single persistent session.
- `DELETE /v1/db/sessions/{session_id}`: Deletes a persistent session (also closes in-memory session).
- `GET /v1/db/sessions/{session_id}/messages`: Returns all persisted messages for a session.

---

## 4. LLM Integration

### 4.1 Custom LLM Wrapper
- Uses Anthropic Messages API format (`/v1/messages` endpoint).
- Configurable via environment variables: `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL` (default `http://localhost:8000`), `ANTHROPIC_MODEL`.
- Default model fallback: `"default"`.
- Supports non-streaming mode only (full response returned at once).
- Max tokens per request: `4096`.

### 4.2 System Prompt Loading
- Loads system prompt from `server/system_prompt.md` if it exists.
- Appends user-provided `system_prompt` to the base prompt.
- System prompt is logged at INFO level (length and first 100 chars).

### 4.3 Available Models
- Hardcoded list: `claude-opus-4-6`, `claude-sonnet-4-6`, `claude-haiku-4-5`, `gpt-4o`, `gpt-4o-mini`, `gemma-4-31b`, `mock-model`.

---

## 5. Agent Turn Execution

### 5.1 Turn Loop (`run_turn`)
- Runs a while loop up to `max_turns` iterations (default 25).
- Each iteration calls the LLM, processes the response, and handles tool calls.
- Loop exits early if: interrupt flag is set, no tool uses in response, max turns reached, or **all tool calls in a turn were denied**.
- On completion, emits `{"type": "result", "num_turns": N}` and sets status to `"idle"`.
- **Known issue (fixed):** Previously, when a tool call was denied, the error result was sent back to the LLM which could produce another response or tool call. The fix adds an `all_denied` flag that breaks the loop when every tool in a turn is denied, halting the agent and waiting for user input.

### 5.2 Message History
- User messages are appended as `{"role": "user", "content": "text"}`.
- Assistant messages are appended as `{"role": "assistant", "content": [content_blocks]}`.
- Tool results are appended as `{"role": "user", "content": [tool_result_blocks]}` in Anthropic format.
- Message history is maintained in-memory and reconstructed from the database on session restore.

### 5.3 Text Streaming
- Text content from the LLM is yielded as `{"type": "text", "data": "chunk"}` events.
- All text chunks are accumulated in `assistant_text_buffer` and persisted as a single message when a tool_use or result event follows.

### 5.4 Thinking/Extended Thinking
- Thinking blocks from the LLM (type `"thinking"`) are yielded as `{"type": "thinking", "data": "...", "done": true/false}` events.
- Thinking content is persisted to the database as a separate message with `type="thinking"`.

### 5.5 Interrupt Handling
- Setting `_interrupt_flag = True` causes the turn loop to break.
- An `[Interrupted]` text event is yielded when interrupted mid-response.
- The session status is set to `"idle"` and the `result` event is emitted.

---

## 6. Tool System

### 6.1 Available Tools
| Tool | Description | Default Rule |
|------|-------------|-------------|
| **Read** | Read file content with optional line range | `allow` |
| **Write** | Write/overwrite file content | `ask` |
| **Replace** | Surgical string replacement in a file | `ask` |
| **Bash** | Execute shell commands (Git Bash on Windows) | `ask` |
| **Glob** | Find files by glob pattern | `allow` |
| **Grep** | Search files by regex pattern | `allow` |
| **WebFetch** | Fetch URL content (truncated to 10000 chars) | `allow` |
| **Delegate** | Delegate task to sub-agent (stub) | `ask` |

### 6.2 Tool Execution
- `execute_tool()` dispatches to the matching tool's `execute()` method.
- Returns `ToolResult` with `output`, `error`, and `is_error` fields.
- Tools receive `cwd` parameter for path resolution.

### 6.3 Tool Events
- `tool_use` event: Emitted when the LLM requests a tool call. Contains `tool_id`, `name`, `input`, `pending_request_id`.
- `tool_result` event: Emitted on successful tool execution. Contains `tool_id`, `output`.
- `tool_error` event: Emitted on tool failure or permission denial. Contains `tool_id`, `error`.

### 6.4 Tool Output Truncation
- Tool output in the UI is truncated to 500 characters.
- A "Show full output" button expands to the full output.
- A "Collapse output" button returns to the truncated view.

### 6.5 Bash Tool - Windows Compatibility
- On Windows, searches for Git Bash at standard installation paths.
- Falls back to error message if Git Bash is not found.
- Uses `-c` flag for command execution via Git Bash.
- Command timeout: 30 seconds.

### 6.6 Replace Tool - Match Validation
- Returns error if `old_string` is not found in the file.
- Returns error if `old_string` matches multiple locations (requires more context).

---

## 7. Permission System

### 7.1 Permission Modes
- **`default`**: Prompts for permission on most tools. Read-only tools (Read, Glob, Grep, WebFetch) are auto-allowed.
- **`acceptEdits`**: Auto-approves file modification tools (Write, Replace). Other tools still prompt.
- **`bypassPermissions`**: Disables all permission prompts, granting full autonomy.
- **`plan`**: Read-only mode; the agent can analyze but cannot execute modification tools.

### 7.2 Tool Rules
- Per-tool permission rules: `"allow"`, `"ask"`, or `"deny"`.
- Default rules are defined in `DEFAULT_TOOL_RULES` dict.
- Rules are stored as JSON in the session's database record.
- Rules can be changed mid-session via the sidebar UI.

### 7.3 Permission Request Flow
1. LLM requests a tool call.
2. Backend checks the tool's rule and the permission mode.
3. If permission is needed, a `PendingPermission` is created with a unique `request_id`.
4. The pending permission is persisted to the `pending_permissions` database table.
5. A `permission_request` SSE event is emitted to the frontend.
6. The agent loop pauses, awaiting the user's decision via `pending.future`.
7. User responds via `POST /v1/sessions/{session_id}/permissions/respond`.
8. `resolve_permission()` resolves the future, optionally updates the tool rule if "always" is selected.
9. If the session was idle (no active stream), `_resume_after_permission()` executes the tool and continues the agent loop.

### 7.4 Permission Response
- `approved`: Whether the tool call is allowed.
- `always`: If true, updates the tool rule to "allow" (or "deny" if not approved).
- `deny_message`: Optional message explaining the denial.
- Permission decisions are logged to the `permissions` database table.

### 7.5 Pending Permission Recovery
- On page refresh, pending permissions are restored from the database.
- The frontend fetches pending permissions via `GET /v1/sessions/{session_id}/pending-permissions`.
- Permission cards are re-rendered for any unresolved requests.
- The input and send button are disabled while awaiting approval.

### 7.6 Auto-Approve Mode
- When `auto_approve=true` in a `StreamRequest` and the session is in `"default"` mode, the permission mode is switched to `"acceptEdits"` before the turn starts.
- This is applied directly to the session object (not via the SDK's `set_permission_mode`).

---

## 8. View Data Generation

### 8.1 ViewData Structure
- `type`: Always `"view"`.
- `active_session`: `SessionView` with full session metadata.
- `sessions`: List of `SessionListItem` for the sidebar.
- `ui_state`: `UIState` with streaming status, approval status, mode, turn tag.
- `messages`: List of `MessageView` objects.
- `pending_actions`: List of unresolved `PendingAction` objects.
- `tool_rules`: List of `ToolRuleView` for the current session.
- `files`: Dict with `changed` and `recently_read` file lists.
- `usage`: `UsageData` with token counts, cost, wall time, context window.
- `tool_call_log`: Chronological list of tool invocations.
- `session_log`: Backend log entries (info, warn, error).
- `available_models`: List of available model names.

### 8.2 Session List Building
- Combines in-memory sessions and database-only sessions.
- In-memory sessions are authoritative for live state.
- Database sessions not in memory are included with their persisted state.
- Sorted by `updated_at` descending.

### 8.3 Message Building
- Handles Anthropic-format messages with list content (text + tool_use blocks).
- Handles user messages with tool_result blocks.
- Parses `<thought>` tags into structured `ContentBlock` objects.
- Tool use blocks include status: `running`, `success`, `error`, `pending_approval`.

### 8.4 File Tracking
- Changed files: Tracked from `Write`, `Replace`, `Edit` tool uses.
- Recently read files: Tracked from `Read`, `Glob`, `Grep` tool uses.
- Deduped by path, showing the most recent access.

### 8.5 Usage Metrics
- Input tokens: Estimated from user message content length (chars / 4).
- Output tokens: Estimated from assistant message content length (chars / 4).
- Estimated cost: Based on per-1k-token rates ($0.003 input, $0.015 output).
- Wall time: Time since session creation.
- Context window: Used tokens vs. max (200,000), with percentage.

### 8.6 Tool Call Log
- Each tool_use message creates a log entry with `tool_name`, `target` (path/command/pattern), `status`, `timestamp`, `tool_id`.
- Status is determined by matching against tool_result messages.

### 8.7 Session Log
- Tool errors generate `"error"` level log entries.
- Tool completions generate `"info"` level log entries.

---

## 9. Frontend UI

### 9.1 Layout
- Three-column layout: Sidebar (280px) | Main (flex) | Right Panel (300px).
- Responsive breakpoints: Right panel hidden at <1000px, sidebar hidden at <720px.
- Mobile sidebar toggle button appears at <720px.

### 9.2 Sidebar

#### 9.2.1 Header
- Logo ("C" in accent color), title "Claude Code", settings button.

#### 9.2.2 New Session Button
- Creates a new session with the currently selected model.
- Clears the conversation and focuses the input.

#### 9.2.3 Session List
- Displays all sessions with title, relative time ("just now", "5m ago", "2h ago", "3d ago").
- Active session is highlighted with accent background and left border.
- Running sessions show a pulsing green dot.
- Clicking a session switches to it (loads messages from database).

#### 9.2.4 Connection Section
- Wrapper endpoint input (default `http://localhost:8787`).
- Model dropdown (populated from `available_models`).
- Working directory input.

#### 9.2.5 Permission Mode Section
- Dropdown with options: Default, Accept edits automatically, Bypass permissions, Plan mode (read-only).
- Tool permission list: Each tool shows its current rule (allow/ask/deny) as a clickable badge.
- Clicking a badge cycles through: allow → ask → deny → allow.

#### 9.2.6 MCP Servers Section
- Collapsible section showing "No MCP servers configured".

#### 9.2.7 Options Section
- Collapsible section with toggles:
  - Extended thinking (default: on)
  - Stream partial messages (default: on)
  - Persist transcript (default: on)
  - Max turns slider (1-100, default: 25)

#### 9.2.8 Footer
- Connection status dot (green = connected, red = disconnected).
- Connection status text.
- SDK version display.

### 9.3 Main Panel

#### 9.3.1 Header
- Mobile hamburger toggle (visible at <720px).
- Breadcrumb: Session title / Working directory.
- Spacer.
- Turn tag: "Turn N" showing total agent responses.
- Session ID tag: Displays the current session ID.
- Export transcript button (download icon).

#### 9.3.2 Conversation Area
- Scrollable message list with auto-scroll to bottom.
- Messages hash comparison to avoid unnecessary re-renders.

#### 9.3.3 User Messages
- Avatar "U" with border styling.
- Role label "You" with timestamp.
- Content rendered as markdown via `marked.parse()`.

#### 9.3.4 Assistant Messages
- Avatar "A" with accent background.
- Role label "Claude" with timestamp.
- Content rendered as markdown.
- Supports `content_blocks` with mixed text and thinking blocks.
- Falls back to plain content if no blocks.

#### 9.3.5 Thinking Blocks
- Collapsible block with clock icon and "Thinking" label.
- Clicking toggles between collapsed and expanded states.
- Shows italicized content in a left-bordered container.
- Streaming thinking blocks have a `.streaming` class.

#### 9.3.6 Tool Blocks
- Collapsible block with chevron, file icon, tool name, target path, and status badge.
- Status badges: `running` (blue), `success` (green), `error` (red), `pending_approval` (yellow), `approved` (green), `denied` (red).
- Input section shows JSON-formatted tool input.
- Output section (added after execution) with collapsible header.
- Output truncated to 500 chars with expand/collapse button.

#### 9.3.7 Tool Messages
- Attached to the last assistant message's body.
- Updates the corresponding tool block's status and output.

#### 9.3.8 Message Stats
- Per-message footer showing: duration, input tokens, output tokens, estimated cost.
- Displayed after the `result` event.

### 9.4 Input Area

#### 9.4.1 Queued Row
- Area for displaying queued message chips (currently unused in main flow).

#### 9.4.2 Input Box
- Border highlights on focus (accent color).
- Auto-resizing textarea (max height 160px).
- Character count display.

#### 9.4.3 Input Toolbar
- Left side: Mode pill, Attach file button, Add image button.
- Right side: Character count, Send button.

#### 9.4.4 Mode Pill
- Clickable pill cycling through: Plan mode (blue), Auto-accept edits (green), Default mode.
- Updates the session's permission mode on click.

#### 9.4.5 Send Button
- Arrow icon when idle.
- Square (stop) icon when streaming.
- Red background when streaming.
- Disabled state with reduced opacity.
- Click sends message or interrupts if streaming.

#### 9.4.6 Keyboard Shortcuts
- `Enter`: Send message (when not streaming).
- `Shift+Enter`: New line in textarea.
- `Escape`: Interrupt streaming agent.

#### 9.4.7 Slash Command Menu
- Triggered when input starts with `/`.
- Commands: `/clear`, `/compact`, `/resume`, `/permissions`, `/cost`, `/mcp`.
- Clicking a command inserts it into the input.
- Menu closes when input no longer starts with `/`.

#### 9.4.8 Hint Row
- Shows keyboard shortcut hints.
- Displays stream status: "idle", "streaming…", "awaiting approval…".

### 9.5 Right Panel

#### 9.5.1 Tab Navigation
- Three tabs: Files, Usage, Logs.
- Active tab has accent bottom border.
- Content switches on tab click.

#### 9.5.2 Files Tab
- Changed files section: Lists files modified by Write/Replace/Edit tools.
- Recently read section: Lists files accessed by Read/Glob/Grep tools.
- Each file shows path with tool name badge.

#### 9.5.3 Usage Tab
- Context window card: Progress bar showing used/max tokens with percentage.
- Session totals card: Input tokens, output tokens, estimated cost, wall time.
- Tool calls card: Chronological list of tool invocations with status.

#### 9.5.4 Logs Tab
- Real-time log stream with timestamp and level indicator.
- Levels: `info` (blue "i"), `warn` (yellow "!"), `error` (red "✕").
- Auto-scrolls to bottom.

---

## 10. Streaming & Real-Time Updates

### 10.1 View Stream Connection
- Single persistent SSE connection to `/v1/view/stream`.
- Reconnects automatically on error (3-second delay).
- Tracks current session ID and persists to `localStorage`.

### 10.2 Action Dispatch
- All frontend actions go through `sendAction()` via `POST /v1/view`.
- Initial ViewData snapshot is rendered immediately for fast UI response.
- Subsequent updates arrive on the SSE stream.

### 10.3 Stream Event Handling
- `session`: Updates session ID, title, cwd in UI. Loads session list and tool rules.
- `text`: Appends text to active message element. Handles `<thought>` tag parsing inline. Maintains streaming cursor.
- `thinking`: Creates or updates thinking block with streaming class.
- `tool_use`: Finalizes current text element, creates tool block with status.
- `tool_result`: Updates tool block status to "success" with output.
- `tool_error`: Updates tool block status to "error" with error message.
- `permission_request`: Adds pending permission, disables input, renders permission card.
- `planning_complete`: Shows planning approval card in plan mode.
- `system`: Adds log line.
- `result`: Finalizes message with stats (duration, tokens, cost). Updates turn tag.
- `error`: Appends error message to current content element.
- `done`: Removes streaming classes and cursor blink.

### 10.4 Streaming State Management
- `setStreaming(true)`: Shows stop icon, disables send button text, updates status text.
- `setStreaming(false)`: Shows arrow icon, restores status to "idle".
- `setAwaitingApproval(true)`: Disables input and send button, shows "awaiting approval…".
- `setAwaitingApproval(false)`: Re-enables input and send button.

### 10.5 Session Event Subscription
- `GET /v1/sessions/{session_id}/events`: Alternative SSE endpoint for session-specific events.
- Used for subscribing to events of a session that may already be running.

---

## 11. Permission UI Components

### 11.1 Permission Card
- Yellow-bordered card with shield icon.
- Title: "Permission requested".
- Description: "Claude wants to run `{tool_name}`".
- Three action buttons:
  - **Allow once**: Approves this single call.
  - **Always allow `{tool}`**: Approves and updates tool rule to "allow".
  - **Deny**: Denies the call.
- On response: Button is disabled, result text is shown, card fades out after 1 second.
- Associated tool block is updated to "approved" or "denied" status.

### 11.2 Planning Approval Card
- Blue-bordered card with shield icon.
- Title: "Plan ready for review".
- Plan content displayed in a scrollable, left-bordered container.
- Two action buttons:
  - **Proceed with plan**: Approves the plan.
  - **Ask to revise**: Requests plan revision.

---

## 12. Session Switching & Restoration

### 12.1 Session Switching
- Clicking a session in the sidebar triggers `switchStream(sessionId)`.
- Disconnects the current SSE stream.
- Connects a new stream to the selected session.
- Updates `localStorage` with the new session ID.
- Loads session tool rules from the database.
- Fetches and renders all persisted messages.
- **Known issue (fixed):** Previously, `state.activeSessionId` was updated after `renderSessionList()`, causing the session highlight to be one behind. The fix updates `state.activeSessionId` from `viewData.active_session` before rendering the session list in `renderViewData()`.

### 12.2 Message Restoration
- User messages rendered with markdown parsing.
- Assistant messages rendered with content blocks (text + thinking).
- Tool use messages rendered as tool blocks with correct status.
- Tool result messages update the corresponding tool block.
- Thinking tags (`<thought>...</thought>`) are parsed into thinking blocks.

### 12.3 Page Refresh Resumption
- Active session ID is persisted in `localStorage` under key `"activeSessionId"`.
- On page load, `getLastActiveSession()` retrieves the stored ID.
- If a stored session exists, `get_view` action is sent to restore state.
- The view stream reconnects to the stored session.

---

## 13. Collapsible UI Sections

### 13.1 Sidebar Sections
- All sidebar sections (Sessions, Connection, Permission mode, MCP servers, Options) are collapsible.
- Clicking the section header toggles the collapsed state.
- Chevron icon rotates when collapsed.

### 13.2 Tool Blocks
- Tool blocks have a collapsible header (chevron + tool name + target + status).
- Clicking the header toggles the tool body (input section).
- Tool output section has its own collapsible header.

### 13.3 Thinking Blocks
- Thinking blocks are collapsible.
- Clicking toggles between collapsed and expanded states.

---

## 14. Responsive Design

### 14.1 Desktop (>1000px)
- Full three-column layout: Sidebar (280px) | Main | Right Panel (300px).

### 14.2 Tablet (720px-1000px)
- Right panel is hidden.
- Two-column layout: Sidebar (240px) | Main.

### 14.3 Mobile (<720px)
- Sidebar is hidden by default.
- Hamburger toggle button appears in the main header.
- Clicking toggle shows sidebar as a fixed overlay with shadow.
- Single-column layout.

---

## 15. CSS & Styling

### 15.1 Theme
- Dark theme with VS Code-inspired color palette.
- CSS custom properties for all colors, fonts, and spacing.
- Monospace font: SF Mono / JetBrains Mono / Consolas.
- Sans font: System font stack.

### 15.2 Status Colors
- `--ok` (green): Success states, running dots, allow badges.
- `--warn` (yellow): Pending states, ask badges.
- `--err` (red): Error states, deny badges.
- `--info` (blue): Running tool status, plan mode.
- `--accent` (orange): Primary accent, send button, active elements.

### 15.3 Animations
- `pulse`: Pulsing green dot for running sessions.
- `blink`: Blinking cursor for streaming text.

### 15.4 Scrollbars
- Custom webkit scrollbar styling.
- Dark thumb on transparent track.

---

## 16. Error Handling

### 16.1 Backend Error Events
- LLM errors yield `{"type": "error", "message": "..."}`.
- Turn exceptions yield error events and set status to "idle".
- CancelledError re-raises after setting status to "idle".

### 16.2 Frontend Error Display
- Stream errors logged to console.
- HTTP errors displayed in the message content area with red styling.
- Connection errors trigger automatic reconnection.

### 16.3 Tool Error Handling
- Tool execution errors yield `tool_error` events.
- Tool blocks update to "error" status with the error message.
- Permission denied yields `tool_error` with "Permission denied by user".

---

## 17. Data Flow Summary

1. User types message → `handleSend()` → `sendAction({action: 'send_message', ...})`.
2. Frontend sends `POST /v1/view` with action.
3. Backend processes action, returns initial `ViewData` snapshot.
4. Frontend renders snapshot immediately.
5. Backend starts agent turn in background (`asyncio.create_task`).
6. Agent turn emits events to session queue.
7. SSE stream picks up events, regenerates `ViewData`, pushes to frontend.
8. Frontend renders updated `ViewData` on each push.
9. On turn completion, `result` event is emitted, status returns to "idle".
10. `done` event closes the stream response.

---

## 18. Configuration & Environment

### 18.1 Server Configuration
- Host: `0.0.0.0`, Port: `8787`.
- Reload enabled in development mode.
- Windows: Uses `ProactorEventLoopPolicy` for asyncio.

### 18.2 Environment Variables
- `ANTHROPIC_API_KEY`: API key for LLM requests.
- `ANTHROPIC_BASE_URL`: Base URL for LLM API (default `http://localhost:8000`).
- `ANTHROPIC_MODEL`: Default model name.

### 18.3 Dependencies
- `fastapi`, `uvicorn[standard]`, `pydantic`: Standard FastAPI stack.
- `aiosqlite`: Async SQLite access.
- `httpx`: Async HTTP client for LLM requests.
