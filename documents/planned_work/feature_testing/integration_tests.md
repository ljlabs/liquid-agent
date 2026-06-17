# Integration Tests

Based on the expected features spec. Tests are organized by feature area and cover the backend API contract, SSE streaming, and end-to-end flows.

---

## Test Setup

All tests use `httpx.AsyncClient` with `ASGITransport` against the FastAPI app. A fresh `SessionManager` and `ViewDataGenerator` are initialized per fixture. The mock LLM client (when needed) is injected via `unittest.mock.patch`.

```python
@pytest.fixture
async def async_client():
    main.manager = SessionManager()
    main.view_generator = ViewDataGenerator(main.manager, db)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
```

---

## 1. Health Check

### T1.1 — Health endpoint returns 200
```
GET /v1/health
→ 200, status == "ok", sdk_available is bool, active_sessions is int
```

---

## 2. ViewData CRUD via `/v1/view`

### T2.1 — get_view with no session returns empty state
```
POST /v1/view { "action": "get_view" }
→ active_session is null, sessions is empty list, messages is empty list
```

### T2.2 — create_session returns active session
```
POST /v1/view { "action": "create_session", "model": "test" }
→ active_session.id starts with "sess_"
→ active_session.model == "test"
→ active_session.permission_mode == "default"
→ active_session.status == "idle"
→ tool_rules is non-empty (defaults)
```

### T2.3 — get_view with session_id returns session data
```
POST /v1/view { "action": "create_session" }  → save session_id
POST /v1/view { "action": "get_view", "session_id": <id> }
→ active_session.id == <id>
→ messages is empty list
→ tool_rules is non-empty
```

### T2.4 — delete_session removes session
```
POST /v1/view { "action": "create_session" }  → save session_id
POST /v1/view { "action": "delete_session", "session_id": <id> }
→ 200 OK
POST /v1/view { "action": "get_view", "session_id": <id> }
→ active_session is null
```

### T2.5 — switch_session restores session
```
POST /v1/view { "action": "create_session" }  → save session_id
POST /v1/view { "action": "delete_session", "session_id": <id> }
POST /v1/view { "action": "switch_session", "session_id": <id> }
→ active_session.id == <id>
```

---

## 3. Permission Mode

### T3.1 — set_mode updates permission mode
```
POST /v1/view { "action": "create_session" }  → save session_id
POST /v1/view { "action": "set_mode", "session_id": <id>, "permission_mode": "acceptEdits" }
→ active_session.permission_mode == "acceptEdits"
→ ui_state.mode == "acceptEdits"
```

### T3.2 — set_mode persists in DB
```
POST /v1/view { "action": "create_session" }  → save session_id
POST /v1/view { "action": "set_mode", "session_id": <id>, "permission_mode": "plan" }
GET /v1/db/sessions/<id>
→ permission_mode == "plan"
```

### T3.3 — all permission modes accepted
For each mode in ["default", "acceptEdits", "bypassPermissions", "plan"]:
```
POST /v1/view { "action": "set_mode", "session_id": <id>, "permission_mode": <mode> }
→ active_session.permission_mode == <mode>
```

---

## 4. Model Selection

### T4.1 — set_model updates model
```
POST /v1/view { "action": "create_session", "model": "old-model" }  → save session_id
POST /v1/view { "action": "set_model", "session_id": <id>, "model": "new-model" }
→ active_session.model == "new-model"
```

---

## 5. Tool Rules

### T5.1 — default tool rules returned
```
POST /v1/view { "action": "get_view", "session_id": <id> }
→ tool_rules contains Bash (ask), Read (allow), Write (ask), Glob (allow), Grep (allow), WebFetch (allow)
```

### T5.2 — update_tool_rule changes a rule
```
POST /v1/view { "action": "update_tool_rule", "session_id": <id>, "tool_name": "Bash", "tool_rule": "allow" }
→ tool_rules where tool == "Bash" has rule == "allow"
```

### T5.3 — update_tool_rule persists in DB
```
POST /v1/view { "action": "update_tool_rule", "session_id": <id>, "tool_name": "Bash", "tool_rule": "deny" }
GET /v1/sessions/<id>/tool-rules
→ rules for Bash == "deny"
```

### T5.4 — all rule values accepted
For each rule in ["allow", "ask", "deny"]:
```
POST /v1/view { "action": "update_tool_rule", "session_id": <id>, "tool_name": "Bash", "tool_rule": <rule> }
→ matching tool_rule has rule == <rule>
```

---

## 6. SSE Stream (`/v1/view/stream`)

### T6.1 — stream returns valid SSE with ViewData
```
POST /v1/view { "action": "create_session" }  → save session_id
GET /v1/view/stream?session_id=<id>
→ Content-Type: text/event-stream
→ First "data:" line parses to JSON with type == "view"
→ active_session.id == <id>
→ messages is list
→ tool_rules is list
→ ui_state is dict
```

### T6.2 — stream with no session returns ViewData with no active_session
```
GET /v1/view/stream
→ First "data:" line parses to JSON with type == "view"
→ active_session is null
```

### T6.3 — stream sends heartbeat after timeout
```
GET /v1/view/stream?session_id=<id>  (idle session)
→ After ~30s, receives {"type": "heartbeat"}
```

### T6.4 — stream sends done when session is idle
```
GET /v1/view/stream?session_id=<id>  (idle session)
→ Receives ViewData, then {"type": "done"}
```

---

## 7. Send Message & Streaming Flow

### T7.1 — send_message returns initial ViewData with running status
```
POST /v1/view { "action": "create_session" }  → save session_id
POST /v1/view { "action": "send_message", "session_id": <id>, "message": "hello" }
→ 200 OK, type == "view"
→ ui_state.streaming == true (or false if turn completes quickly)
→ active_session.status == "running" (or "idle" if completed)
```

### T7.2 — send_message creates user message in DB
```
POST /v1/view { "action": "send_message", "session_id": <id>, "message": "hello" }
GET /v1/db/sessions/<id>/messages
→ messages[0].role == "user", messages[0].content == "hello"
```

### T7.3 — send_message with mock LLM produces assistant text
```
POST /v1/view { "action": "send_message", "session_id": <id>, "message": "mock_text: Hello world" }
Wait for session idle
GET /v1/view { "action": "get_view", "session_id": <id> }
→ messages contain an assistant message with content "Hello world"
```

### T7.4 — send_message with mock LLM produces tool_use then tool_result
```
POST /v1/view { "action": "send_message", "session_id": <id>, "message": "mock_tool: Bash" }
Wait for permission, resolve, wait for idle
GET /v1/view { "action": "get_view", "session_id": <id> }
→ messages contain tool_use message with tool_name == "Bash"
→ messages contain tool_result message
```

---

## 8. Permission Flow (via `/v1/view`)

### T8.1 — tool with "ask" rule triggers pending_actions
```
Create session, set Bash to "ask"
POST /v1/view { "action": "send_message", "session_id": <id>, "message": "mock_tool: Bash" }
Wait for permission request
GET /v1/view { "action": "get_view", "session_id": <id> }
→ pending_actions is non-empty
→ pending_actions[0].action_type == "permission"
→ pending_actions[0].tool_name == "Bash"
→ ui_state.awaiting_approval == true
→ active_session.permission_status == "awaiting_approval"
```

### T8.2 — approve permission resumes agent
```
Create session, trigger permission request
POST /v1/view { "action": "respond_permission", "session_id": <id>, "request_id": <rid>, "approved": true }
Wait for idle
GET /v1/view { "action": "get_view", "session_id": <id> }
→ pending_actions is empty
→ ui_state.awaiting_approval == false
→ active_session.permission_status == "none"
→ messages contain tool_result
```

### T8.3 — deny permission blocks tool execution
```
Create session, trigger permission request
POST /v1/view { "action": "respond_permission", "session_id": <id>, "request_id": <rid>, "approved": false }
Wait for idle
GET /v1/view { "action": "get_view", "session_id": <id> }
→ messages contain tool_error with "denied" in content
```

### T8.4 — "always allow" updates tool rule
```
Create session, trigger permission request for Bash
POST /v1/view { "action": "respond_permission", "session_id": <id>, "request_id": <rid>, "approved": true, "always": true }
Wait for idle
GET /v1/view { "action": "get_view", "session_id": <id> }
→ tool_rules where tool == "Bash" has rule == "allow"
```

### T8.5 — tool with "allow" rule skips permission prompt
```
Create session, set Bash to "allow"
POST /v1/view { "action": "send_message", "session_id": <id>, "message": "mock_tool: Bash" }
Wait for idle
GET /v1/view { "action": "get_view", "session_id": <id> }
→ pending_actions is empty
→ messages contain tool_result (no permission_request event)
```

### T8.6 — tool with "deny" rule blocks immediately
```
Create session, set Bash to "deny"
POST /v1/view { "action": "send_message", "session_id": <id>, "message": "mock_tool: Bash" }
Wait for idle
GET /v1/view { "action": "get_view", "session_id": <id> }
→ pending_actions is empty
→ messages contain tool_error with "denied" in content
```

### T8.7 — "bypassPermissions" mode skips all permissions
```
Create session, set mode to "bypassPermissions"
POST /v1/view { "action": "send_message", "session_id": <id>, "message": "mock_tool: Bash" }
Wait for idle
GET /v1/view { "action": "get_view", "session_id": <id> }
→ pending_actions is empty
→ messages contain tool_result
```

---

## 9. Page Refresh Resumption

### T9.1 — pending permission survives in-memory session removal
```
Create session, trigger permission request
GET /v1/sessions → DELETE all sessions (simulate refresh)
GET /v1/sessions/<id>/pending-permissions
→ permissions list contains the request_id
```

### T9.2 — approve permission after session removal restores session
```
Create session, trigger permission request, drop session from memory
POST /v1/sessions/<id>/permissions/respond { "request_id": <rid>, "approved": true }
Wait for agent loop to finish
GET /v1/db/sessions/<id>/messages
→ contains tool_result and assistant text
→ pending-permissions is empty
```

### T9.3 — deny permission after session removal stops agent
```
Create session, trigger permission request, drop session from memory
POST /v1/sessions/<id>/permissions/respond { "request_id": <rid>, "approved": false }
GET /v1/db/sessions/<id>/messages
→ contains "denied" in tool message
```

---

## 10. Interrupt

### T10.1 — interrupt stops running session
```
Create session, send long-running message
POST /v1/view { "action": "interrupt", "session_id": <id> }
Wait briefly
GET /v1/view { "action": "get_view", "session_id": <id> }
→ active_session.status == "idle"
```

---

## 11. Session List

### T11.1 — session list updates after create
```
POST /v1/view { "action": "get_view" }
→ sessions is empty

POST /v1/view { "action": "create_session" }
→ sessions has 1 item with matching id
```

### T11.2 — session list updates after delete
```
POST /v1/view { "action": "create_session" }  → save session_id
POST /v1/view { "action": "delete_session", "session_id": <id> }
POST /v1/view { "action": "get_view" }
→ sessions is empty
```

### T11.3 — session list shows multiple sessions
```
POST /v1/view { "action": "create_session", "model": "m1" }
POST /v1/view { "action": "create_session", "model": "m2" }
POST /v1/view { "action": "get_view" }
→ sessions has 2 items
```

---

## 12. ViewData Structure Validation

### T12.1 — ViewData has correct top-level fields
```
POST /v1/view { "action": "get_view" }
→ has fields: type, active_session, sessions, ui_state, messages, pending_actions, tool_rules, files, usage, tool_call_log, session_log
→ type == "view"
```

### T12.2 — SessionView has all required fields
```
POST /v1/view { "action": "create_session" }
→ active_session has: id, title, cwd, model, permission_mode, status, permission_status, created_at, updated_at, turn_count, current_pending_request
```

### T12.3 — UIState has correct structure
```
POST /v1/view { "action": "get_view", "session_id": <id> }
→ ui_state has: streaming (bool), awaiting_approval (bool), mode (str), turn_tag (str), should_attach (bool)
```

### T12.4 — MessageView has correct structure
```
POST /v1/view { "action": "send_message", "session_id": <id>, "message": "hello" }
Wait for idle
GET /v1/view { "action": "get_view", "session_id": <id> }
→ messages[0] has: id, role, type, content, content_blocks, tool_name, tool_id, tool_input, status, created_at
```

### T12.5 — ToolRuleView has correct structure
```
POST /v1/view { "action": "get_view", "session_id": <id> }
→ tool_rules[0] has: tool (str), rule (one of "allow", "ask", "deny")
```

### T12.6 — Files view has correct structure
```
POST /v1/view { "action": "get_view", "session_id": <id> }
→ files has: changed (list), recently_read (list)
→ files.changed[0] has: path (str), tool_name (str), timestamp (float)
→ files.recently_read[0] has: path (str), tool_name (str), timestamp (float)
```

### T12.7 — Usage view has correct structure
```
POST /v1/view { "action": "get_view", "session_id": <id> }
→ usage has: input_tokens (int), output_tokens (int), estimated_cost (float), wall_time_seconds (float)
→ usage.context_window has: used (int), max (int), percentage (float)
```

### T12.8 — Tool call log has correct structure
```
POST /v1/view { "action": "get_view", "session_id": <id> }
→ tool_call_log is list
→ tool_call_log[0] has: tool_name (str), target (str), status (str), timestamp (float), tool_id (str)
```

### T12.9 — Session log has correct structure
```
POST /v1/view { "action": "get_view", "session_id": <id> }
→ session_log is list
→ session_log[0] has: timestamp (float), level (str), message (str)
```

---

## 13. Right Panel — Files Tracking

### T13.1 — Edit tool adds file to changed list
```
Create session, send message that triggers Edit tool
Wait for idle
GET /v1/view { "action": "get_view", "session_id": <id> }
→ files.changed is non-empty
→ files.changed[0].path matches the edited file
→ files.changed[0].tool_name == "Edit"
```

### T13.2 — Write tool adds file to changed list
```
Create session, send message that triggers Write tool
Wait for idle
GET /v1/view { "action": "get_view", "session_id": <id> }
→ files.changed contains entry with tool_name == "Write"
```

### T13.3 — Replace tool adds file to changed list
```
Create session, send message that triggers Replace tool
Wait for idle
GET /v1/view { "action": "get_view", "session_id": <id> }
→ files.changed contains entry with tool_name == "Replace"
```

### T13.4 — Read tool adds file to recently_read list
```
Create session, send message that triggers Read tool
Wait for idle
GET /v1/view { "action": "get_view", "session_id": <id> }
→ files.recently_read is non-empty
→ files.recently_read[0].tool_name == "Read"
```

### T13.5 — Glob tool adds file to recently_read list
```
Create session, send message that triggers Glob tool
Wait for idle
GET /v1/view { "action": "get_view", "session_id": <id> }
→ files.recently_read contains entry with tool_name == "Glob"
```

### T13.6 — Grep tool adds file to recently_read list
```
Create session, send message that triggers Grep tool
Wait for idle
GET /v1/view { "action": "get_view", "session_id": <id> }
→ files.recently_read contains entry with tool_name == "Grep"
```

### T13.7 — duplicate files are deduplicated
```
Create session, send message that reads same file twice (via Read tool)
Wait for idle
GET /v1/view { "action": "get_view", "session_id": <id> }
→ files.recently_read has only 1 entry for that path
→ most recent timestamp wins
```

### T13.8 — files lists are empty for new session
```
POST /v1/view { "action": "create_session" }
→ files.changed is empty list
→ files.recently_read is empty list
```

---

## 14. Right Panel — Usage Tracking

### T14.1 — usage tokens are zero for new session
```
POST /v1/view { "action": "create_session" }
→ usage.input_tokens == 0
→ usage.output_tokens == 0
→ usage.estimated_cost == 0.0
```

### T14.2 — usage tokens increase after message
```
Create session, send "hello", wait for idle
GET /v1/view { "action": "get_view", "session_id": <id> }
→ usage.input_tokens > 0
→ usage.output_tokens > 0
→ usage.estimated_cost > 0
```

### T14.3 — wall_time_seconds is positive
```
Create session, send message, wait for idle
GET /v1/view { "action": "get_view", "session_id": <id> }
→ usage.wall_time_seconds > 0
```

### T14.4 — context_window has valid max
```
POST /v1/view { "action": "get_view", "session_id": <id> }
→ usage.context_window.max > 0
→ usage.context_window.used >= 0
→ usage.context_window.percentage >= 0.0
→ usage.context_window.percentage <= 100.0
```

### T14.5 — usage accumulates across multiple turns
```
Create session, send "hello", wait for idle
Record input_tokens_1, output_tokens_1
Send "world", wait for idle
GET /v1/view { "action": "get_view", "session_id": <id> }
→ usage.input_tokens > input_tokens_1
→ usage.output_tokens > output_tokens_1
```

---

## 15. Right Panel — Tool Call Log

### T15.1 — tool_call_log is empty for new session
```
POST /v1/view { "action": "create_session" }
→ tool_call_log is empty list
```

### T15.2 — tool_use event adds entry to tool_call_log
```
Create session, send message that triggers Bash tool
Wait for idle
GET /v1/view { "action": "get_view", "session_id": <id> }
→ tool_call_log is non-empty
→ tool_call_log[0].tool_name == "Bash"
→ tool_call_log[0].status in ["success", "error"]
→ tool_call_log[0].timestamp > 0
```

### T15.3 — tool_call_log entries ordered chronologically
```
Create session, send message that triggers multiple tools
Wait for idle
GET /v1/view { "action": "get_view", "session_id": <id> }
→ for i in 1..len(tool_call_log)-1:
    tool_call_log[i].timestamp >= tool_call_log[i-1].timestamp
```

### T15.4 — tool_call_log includes target excerpt
```
Create session, send "read /path/to/file.txt" (triggers Read)
Wait for idle
GET /v1/view { "action": "get_view", "session_id": <id> }
→ tool_call_log contains entry where target contains "/path/to/file.txt" or excerpt
```

### T15.5 — tool_call_log reflects denied tools
```
Create session, set Bash to "deny"
Send message that triggers Bash
Wait for idle
GET /v1/view { "action": "get_view", "session_id": <id> }
→ tool_call_log contains entry with tool_name == "Bash" and status == "error"
```

---

## 16. Right Panel — Session Logs

### T16.1 — session_log is empty for new session
```
POST /v1/view { "action": "create_session" }
→ session_log is empty list
```

### T16.2 — session_log captures errors
```
Create session, send message that causes LLM error
Wait for idle
GET /v1/view { "action": "get_view", "session_id": <id> }
→ session_log contains entry with level == "error"
```

### T16.3 — session_log entries have valid structure
```
POST /v1/view { "action": "get_view", "session_id": <id> }
→ session_log is list
→ each entry has: timestamp (float), level (str in ["info", "warn", "error"]), message (str)
```

### T16.4 — session_log entries ordered by timestamp
```
POST /v1/view { "action": "get_view", "session_id": <id> }
→ for i in 1..len(session_log)-1:
    session_log[i].timestamp >= session_log[i-1].timestamp
```

---

## 17. Database Persistence

### T17.1 — session created in DB via view endpoint
```
POST /v1/view { "action": "create_session", "model": "test" }
GET /v1/db/sessions
→ contains session with model == "test"
```

### T17.2 — session deleted from DB via view endpoint
```
POST /v1/view { "action": "create_session" }  → save session_id
POST /v1/view { "action": "delete_session", "session_id": <id> }
GET /v1/db/sessions
→ does not contain session
```

### T17.3 — messages persisted in DB
```
POST /v1/view { "action": "send_message", "session_id": <id>, "message": "hello" }
GET /v1/db/sessions/<id>/messages
→ messages[0].role == "user", messages[0].content == "hello"
```

### T17.4 — tool rules persisted in DB
```
POST /v1/view { "action": "update_tool_rule", "session_id": <id>, "tool_name": "Bash", "tool_rule": "allow" }
GET /v1/sessions/<id>/tool-rules
→ Bash rule == "allow"
```

### T17.5 — pending permissions persisted in DB
```
Create session, set Bash to "ask"
POST /v1/view { "action": "send_message", "session_id": <id>, "message": "mock_tool: Bash" }
Wait for permission
GET /v1/sessions/<id>/pending-permissions
→ permissions list is non-empty, contains request_id
```

---

## 18. Error Handling

### T18.1 — create_session with invalid action returns 422
```
POST /v1/view { "action": "invalid_action" }
→ 422 Unprocessable Entity
```

### T18.2 — get_view with nonexistent session returns empty state
```
POST /v1/view { "action": "get_view", "session_id": "nonexistent" }
→ active_session is null
```

### T18.3 — delete_session with nonexistent session is idempotent
```
POST /v1/view { "action": "delete_session", "session_id": "nonexistent" }
→ 200 OK
```

### T18.4 — respond_permission with invalid request_id returns 404
```
POST /v1/view { "action": "respond_permission", "session_id": <id>, "request_id": "invalid", "approved": true }
→ 404
```

---

## 19. Legacy Endpoint Compatibility

These tests verify the old endpoints still work alongside the new `/v1/view` endpoint.

### T19.1 — POST /v1/sessions still creates sessions
```
POST /v1/sessions { "cwd": "/tmp", "model": "test" }
→ 200, session_id present
```

### T19.2 — GET /v1/sessions still lists sessions
```
GET /v1/sessions
→ 200, sessions is list
```

### T19.3 — DELETE /v1/sessions/{id} still closes sessions
```
POST /v1/sessions { "cwd": "/tmp" }  → save session_id
DELETE /v1/sessions/<id>
→ 200, closed == true
```

### T19.4 — POST /v1/sessions/stream still streams
```
POST /v1/sessions/stream { "message": "hello" }
→ 200, text/event-stream
```

### T19.5 — GET /v1/tool-defaults returns canonical tool list
```
GET /v1/tool-defaults
→ 200, tools is list of all DEFAULT_TOOL_RULES keys
```
