# Plan: View Data Architecture Refactor

## Overview

Refactor the architecture so the backend owns all business logic and state management. The frontend becomes a pure renderer that consumes a single `ViewData` object. All communication happens over a single persistent SSE stream endpoint.

---

## Goals

1. **Backend owns state**: `ViewData` module generates structured Pydantic objects as the single source of truth
2. **Single stream endpoint**: One `/v1/view` SSE endpoint handles all requests (messages, session switches, tool decisions, etc.)
3. **Frontend is a thin renderer**: No session management, no message reconstruction, no state logic
4. **Active session only**: Backend returns only the data needed for the current view, not all sessions
5. **Persistent connection**: Single SSE connection maintained for session lifetime, auto-reconnects on refresh
6. **Structured messages**: Backend stores and serves structured message blocks (no frontend parsing of `<thought>` tags)

---

## Architecture

```
Frontend (Renderer)          Backend (State Owner)
┌─────────────────┐          ┌─────────────────────┐
│                 │  SSE     │                     │
│  ViewData       │◄─────────│  /v1/view           │
│  Renderer       │          │       │              │
│                 │  POST    │       ▼              │
│  ViewAction     │─────────►│  ViewData Module    │
│  Dispatcher     │          │       │              │
│                 │          │       ▼              │
│                 │          │  SessionManager     │
│                 │          │  Database           │
└─────────────────┘          └─────────────────────┘
```

---

## Problem Analysis: Why Resumption Fails

### The Re-attachment Gap
When a page refresh occurs:
- **State Loss**: Frontend loses `activeSessionId` and all volatile state (`streaming`, `awaitingApproval`)
- **Connection Gap**: Even if backend session is still running the agent loop, frontend has no mechanism to auto-re-attach to the event stream
- **Passive Restoration**: `switchToSession` only loads history, doesn't check if session is currently `running` to auto-subscribe

### Logic Leaks (Frontend doing Backend work)

#### Message Structuring & Parsing
- **Thought Parsing**: Frontend uses regex to find `<thought>` tags in stored content. Backend stores raw strings, frontend interprets what is "thought" vs "text"
- **Tool-to-Assistant Mapping**: Frontend uses loop variable (`currentAssistantEl`) to guess which tool result belongs to which assistant bubble. Malformed history breaks UI

#### Status Mapping
- **Permission State**: Frontend infers `pending_approval` from `pending_request_id` presence. Truth of whether session is blocked by permission request not surfaced as first-class session status

#### Event Subscription Orchestration
- Frontend decides when to subscribe to events (only after approval). Creates fragmented experience where "live" connection is intermittently opened/closed instead of persistent "remote control" link

---

## Solution: Persistent Remote Control Pattern

### Session Persistence via localStorage
- Store `activeSessionId` in localStorage on every session switch
- On page load, check localStorage and auto-attach to last active session
- Backend provides session status so frontend knows if session is running/awaiting permission

### Auto-Reattach Flow
1. Page loads → check localStorage for `activeSessionId`
2. If found → send `get_view` action with `session_id`
3. Backend returns `ViewData` with `ui_state.streaming = true` if session is running
4. Frontend auto-subscribes to SSE stream for live updates
5. If `pending_actions` exist, render permission cards immediately

### Structured Message Storage
- Backend stores messages as structured blocks: `{type: "thinking", content: "..."}`, `{type: "text", content: "..."}`
- No more `<thought>` tag parsing in frontend
- `MessageView` type field directly indicates message type

---

## New Module: `view_data.py`

### Purpose
Generates `ViewData` Pydantic objects that represent the complete UI state. This is the ONLY data the frontend receives.

### Pydantic Models

```python
# view_data.py

from pydantic import BaseModel
from typing import Optional, Literal
from enum import Enum

class ViewData(BaseModel):
    """Complete UI state sent to frontend."""
    type: Literal["view"] = "view"
    
    # Active session state
    active_session: Optional[SessionView] = None
    
    # Sidebar data (lightweight - no messages)
    sessions: list[SessionListItem] = []
    
    # UI state
    ui_state: UIState = UIState()
    
    # Messages for active session ONLY
    messages: list[MessageView] = []
    
    # Pending actions requiring user input
    pending_actions: list[PendingAction] = []
    
    # Tool permissions for active session
    tool_rules: list[ToolRuleView] = []

class SessionView(BaseModel):
    """Active session metadata with first-class status."""
    id: str
    title: str
    cwd: str
    model: str
    permission_mode: str
    status: Literal["idle", "running", "closed"]
    # First-class permission status (not inferred from pending_request_id)
    permission_status: Optional[Literal["none", "awaiting_approval", "awaiting_planning"]] = None
    created_at: float
    updated_at: float
    turn_count: int = 0
    # Current pending request if awaiting permission
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
    # Whether to auto-attach to session stream
    should_attach: bool = False

class MessageView(BaseModel):
    """Single message for display - structured, no parsing needed."""
    id: int
    role: Literal["user", "assistant", "tool"]
    # Structured type - frontend doesn't need to parse <thought> tags
    type: Literal["text", "thinking", "tool_use", "tool_result", "tool_error"]
    content: str
    # For assistant messages with multiple blocks, provide pre-parsed blocks
    content_blocks: Optional[list[ContentBlock]] = None
    tool_name: Optional[str] = None
    tool_id: Optional[str] = None
    tool_input: Optional[dict] = None
    # First-class status - frontend doesn't infer from pending_request_id
    status: Optional[Literal["running", "success", "error", "pending_approval"]] = None
    created_at: float

class ContentBlock(BaseModel):
    """Pre-parsed content block for assistant messages."""
    type: Literal["text", "thinking"]
    content: str

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
```

### ViewData Generator

```python
class ViewDataGenerator:
    """Generates ViewData from backend state."""
    
    async def generate(
        self,
        session_id: Optional[str] = None,
        include_messages: bool = True,
    ) -> ViewData:
        """Generate complete view data for current state."""
        
        # Get active session
        active_session = None
        messages = []
        tool_rules = []
        pending_actions = []
        
        if session_id:
            session = self.session_manager.get(session_id)
            if session:
                # Determine permission_status (first-class, not inferred)
                permission_status = "none"
                current_pending = None
                if session._pending_permissions:
                    permission_status = "awaiting_approval"
                    # Get the first pending request for current_pending_request
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
                
                active_session = SessionView(
                    id=session.session_id,
                    title=await self._get_title(session_id),
                    cwd=session.cwd,
                    model=session.model,
                    permission_mode=session.permission_mode,
                    status=session.status,
                    permission_status=permission_status,
                    created_at=session.created_at,
                    updated_at=await self._get_updated_at(session_id),
                    turn_count=len([m for m in session.messages if m["role"] == "user"]),
                    current_pending_request=current_pending,
                )
                
                if include_messages:
                    messages = await self._build_messages(session)
                
                tool_rules = self._build_tool_rules(session)
                pending_actions = self._build_pending_actions(session)
        
        # Get all sessions for sidebar (lightweight)
        sessions = await self._build_session_list()
        
        # Build UI state
        ui_state = UIState(
            streaming=active_session.status == "running" if active_session else False,
            awaiting_approval=len(pending_actions) > 0,
            mode=self._get_mode(active_session),
            turn_tag=f"Turn {active_session.turn_count}" if active_session else "Turn 0",
            # Auto-attach if session is running or has pending actions
            should_attach=(
                (active_session.status == "running") or 
                (len(pending_actions) > 0)
            ) if active_session else False,
        )
        
        return ViewData(
            active_session=active_session,
            sessions=sessions,
            ui_state=ui_state,
            messages=messages,
            pending_actions=pending_actions,
            tool_rules=tool_rules,
        )
    
    async def _build_messages(self, session: Session) -> list[MessageView]:
        """Convert session messages to view format with structured blocks."""
        messages = []
        for i, msg in enumerate(session.messages):
            # Parse content blocks for assistant messages
            content_blocks = None
            if msg["role"] == "assistant" and isinstance(msg.get("content"), list):
                content_blocks = self._parse_content_blocks(msg["content"])
            
            view_msg = MessageView(
                id=i,
                role=msg["role"],
                type=self._get_message_type(msg),
                content=self._extract_content(msg),
                content_blocks=content_blocks,
                tool_name=msg.get("tool_name"),
                tool_id=msg.get("tool_id"),
                tool_input=msg.get("tool_input"),
                status=self._get_message_status(msg, session),
                created_at=msg.get("created_at", 0),
            )
            messages.append(view_msg)
        return messages
    
    def _parse_content_blocks(self, content: list) -> list[ContentBlock]:
        """Parse Anthropic content blocks into structured format."""
        blocks = []
        for block in content:
            if block.get("type") == "text":
                blocks.append(ContentBlock(type="text", content=block.get("text", "")))
            elif block.get("type") == "tool_use":
                # Tool use blocks are handled separately via tool_name/tool_input
                pass
        return blocks
    
    def _build_pending_actions(self, session: Session) -> list[PendingAction]:
        """Build list of pending actions from session."""
        actions = []
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
    
    def _build_tool_rules(self, session: Session) -> list[ToolRuleView]:
        """Build tool rules list."""
        rules = session.get_tool_rules()
        return [ToolRuleView(tool=name, rule=rule) for name, rule in rules.items()]
    
    async def _build_session_list(self) -> list[SessionListItem]:
        """Build lightweight session list for sidebar."""
        sessions = []
        for session in self.session_manager.list():
            msg_count = len(session.messages)
            sessions.append(SessionListItem(
                id=session.session_id,
                title=await self._get_title(session.session_id),
                updated_at=session.created_at,
                status=session.status,
                message_count=msg_count,
            ))
        return sessions
```

---

## New Endpoint: `/v1/view`

### SSE Stream for All Communication

```python
# main.py

@app.post("/v1/view")
async def view_stream(req: ViewRequest) -> StreamingResponse:
    """
    Single endpoint for all frontend communication.
    
    Frontend sends actions, backend responds with ViewData.
    """
    
    async def event_stream():
        try:
            # Process the action
            await _process_view_action(req)
            
            # Generate and send view data
            view_data = await view_generator.generate(
                session_id=req.session_id,
                include_messages=req.include_messages if hasattr(req, 'include_messages') else True,
            )
            yield _sse(view_data.model_dump())
            
            # If streaming, keep connection open for updates
            if view_data.ui_state.streaming:
                session = manager.get(req.session_id)
                if session:
                    queue = session.subscribe_events()
                    try:
                        while True:
                            try:
                                event = await asyncio.wait_for(queue.get(), timeout=30)
                                # Regenerate view data on each event
                                updated_view = await view_generator.generate(
                                    session_id=req.session_id,
                                )
                                yield _sse(updated_view.model_dump())
                                if updated_view.ui_state.status == "idle":
                                    break
                            except asyncio.TimeoutError:
                                yield _sse({"type": "heartbeat"})
                    finally:
                        session.unsubscribe_events(queue)
            
            yield _sse({"type": "done"})
            
        except Exception as exc:
            yield _sse({"type": "error", "message": str(exc)})
    
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class ViewRequest(BaseModel):
    """Request from frontend."""
    action: Literal[
        "send_message",
        "switch_session", 
        "create_session",
        "delete_session",
        "interrupt",
        "respond_permission",
        "set_mode",
        "set_model",
        "update_tool_rule",
        "get_view",
    ]
    session_id: Optional[str] = None
    message: Optional[str] = None
    model: Optional[str] = None
    permission_mode: Optional[str] = None
    tool_name: Optional[str] = None
    tool_rule: Optional[str] = None
    request_id: Optional[str] = None
    approved: Optional[bool] = None
    always: Optional[bool] = None
    include_messages: bool = True


async def _process_view_action(req: ViewRequest) -> None:
    """Process frontend action and update backend state."""
    
    if req.action == "send_message":
        # Send message to session - get_or_create handles restore
        session = await manager.get_or_create(req.session_id)
        # Run turn in background so we can stream events
        asyncio.create_task(session.run_turn(req.message))
        
    elif req.action == "switch_session":
        # Restore session if not in memory
        if req.session_id:
            await manager.get_or_create(req.session_id)
        
    elif req.action == "get_view":
        # Just return current state, no action needed
        pass
        
    elif req.action == "create_session":
        session = await manager.create(
            model=req.model,
            cwd=req.cwd if hasattr(req, 'cwd') else None,
        )
        await db.create_session(
            session_id=session.session_id,
            title="New Session",
            cwd=session.cwd or "",
            model=session.model,
            permission_mode=session.permission_mode,
        )
        
    elif req.action == "delete_session":
        await manager.close(req.session_id)
        await db.delete_session(req.session_id)
        
    elif req.action == "interrupt":
        session = manager.get(req.session_id)
        if session:
            await session.interrupt()
            
    elif req.action == "respond_permission":
        session = manager.get(req.session_id)
        if session:
            session.resolve_permission(
                req.request_id,
                req.approved,
                req.always or False,
            )
            
    elif req.action == "set_mode":
        session = manager.get(req.session_id)
        if session:
            await session.set_permission_mode(req.permission_mode)
            await db.update_session(req.session_id, permission_mode=req.permission_mode)
            
    elif req.action == "set_model":
        session = manager.get(req.session_id)
        if session:
            await session.set_model(req.model)
            
    elif req.action == "update_tool_rule":
        session = manager.get(req.session_id)
        if session:
            session.set_tool_rule(req.tool_name, req.tool_rule)
            rules = session.get_tool_rules()
            await db.update_session(req.session_id, tool_rules=json.dumps(rules))
```

---

## Frontend Changes

### New `renderer.js` Module

```javascript
// renderer.js - Pure renderer, no business logic

import { state } from './state.js';

/**
 * Render ViewData to DOM.
 * This is the ONLY function that touches the DOM.
 */
export function renderViewData(viewData) {
    // Update session list (sidebar)
    renderSessionList(viewData.sessions);
    
    // Update active session display
    if (viewData.active_session) {
        renderActiveSession(viewData.active_session);
    }
    
    // Update messages (only if changed)
    if (viewData.messages && viewData.messages.length > 0) {
        renderMessages(viewData.messages);
    }
    
    // Update UI state
    renderUIState(viewData.ui_state);
    
    // Update pending actions (first-class, not inferred)
    renderPendingActions(viewData.pending_actions);
    
    // Update tool rules
    renderToolRules(viewData.tool_rules);
}

function renderSessionList(sessions) {
    const list = document.getElementById('session-list');
    list.innerHTML = '';
    
    for (const session of sessions) {
        const item = document.createElement('div');
        item.className = 'session-item';
        item.dataset.session = session.id;
        item.innerHTML = `
            <span class="dot"></span>
            <span class="title">${escapeHtml(session.title)}</span>
            <span class="meta">${session.message_count} msgs</span>
        `;
        item.addEventListener('click', () => {
            // Send action to backend, not handle locally
            sendAction({
                action: 'switch_session',
                session_id: session.id,
            });
        });
        list.appendChild(item);
    }
}

function renderActiveSession(session) {
    document.getElementById('session-id-tag').textContent = session.id;
    document.getElementById('session-title').textContent = session.title;
    document.getElementById('cwd-display').textContent = session.cwd;
    document.getElementById('turn-tag').textContent = `Turn ${session.turn_count}`;
    
    // Update permission mode dropdown
    const permSelect = document.getElementById('perm-mode-select');
    if (permSelect) permSelect.value = session.permission_mode;
    
    // Update model dropdown
    const modelSelect = document.getElementById('model-select');
    if (modelSelect) modelSelect.value = session.model;
}

function renderMessages(messages) {
    const conversation = document.getElementById('conversation');
    
    // Check if messages changed (simple hash comparison)
    const newHash = JSON.stringify(messages.map(m => m.id));
    if (conversation.dataset.hash === newHash) return;
    conversation.dataset.hash = newHash;
    
    conversation.innerHTML = '';
    
    for (const msg of messages) {
        if (msg.role === 'user') {
            appendUserMessage(msg);
        } else if (msg.role === 'assistant') {
            // Use pre-parsed content blocks if available
            appendAssistantMessage(msg, msg.content_blocks);
        } else if (msg.role === 'tool') {
            appendToolMessage(msg);
        }
    }
}

function renderUIState(uiState) {
    state.streaming = uiState.streaming;
    state.awaitingApproval = uiState.awaiting_approval;
    
    // Update send button
    const sendBtn = document.getElementById('send-btn');
    if (uiState.streaming) {
        sendBtn.classList.add('stop');
    } else {
        sendBtn.classList.remove('stop');
    }
    
    // Update status
    document.getElementById('stream-status').textContent = 
        uiState.streaming ? 'streaming...' : 'idle';
}

function renderPendingActions(actions) {
    // Clear existing permission cards
    document.querySelectorAll('.permission-card').forEach(el => el.remove());
    
    if (actions.length > 0) {
        const conversation = document.getElementById('conversation');
        const lastMsg = conversation.querySelector('.msg:last-child');
        
        for (const action of actions) {
            if (action.action_type === 'permission') {
                appendPermissionCard(lastMsg, action);
            }
        }
    }
}

function appendAssistantMessage(msg, contentBlocks) {
    const conversation = document.getElementById('conversation');
    const msgEl = appendAssistantStub();
    
    // Remove cursor blink
    msgEl.querySelector('.cursor-blink')?.remove();
    
    const bodyEl = msgEl.querySelector('.msg-body');
    
    if (contentBlocks && contentBlocks.length > 0) {
        // Use pre-parsed content blocks (no <thought> parsing needed)
        for (const block of contentBlocks) {
            if (block.type === 'thinking') {
                appendOrUpdateThinking(msgEl, { data: block.content, done: true });
            } else if (block.type === 'text') {
                const contentEl = document.createElement('div');
                contentEl.className = 'msg-content markdown-body rendered';
                contentEl.innerHTML = marked.parse(block.content);
                bodyEl.appendChild(contentEl);
            }
        }
    } else if (msg.content) {
        // Fallback: render as plain text
        const contentEl = document.createElement('div');
        contentEl.className = 'msg-content markdown-body rendered';
        contentEl.innerHTML = marked.parse(msg.content);
        bodyEl.appendChild(contentEl);
    }
    
    // Add tool use blocks if present
    if (msg.tool_name) {
        appendToolBlock(bodyEl, {
            id: msg.tool_id || `hist_${msg.id}`,
            name: msg.tool_name,
            target: String(msg.tool_input?.path || msg.tool_input?.command || '').slice(0, 60),
            status: msg.status || 'success',
            input: msg.tool_input || {},
        });
    }
}
```

### New `stream.js` Module

```javascript
// stream.js - Persistent single connection to backend

let eventSource = null;
let reconnectTimeout = null;
let currentSessionId = null;

const STORAGE_KEY = 'activeSessionId';

/**
 * Connect to the view stream.
 * Single persistent connection for session lifetime.
 */
export function connectViewStream() {
    if (eventSource) {
        eventSource.close();
    }
    
    eventSource = new EventSource('/v1/view/stream');
    
    eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);
        
        if (data.type === 'done') {
            // Stream complete, but keep connection open
            return;
        }
        
        if (data.type === 'heartbeat') {
            return;
        }
        
        if (data.type === 'error') {
            console.error('Stream error:', data.message);
            return;
        }
        
        // Update current session ID from ViewData
        if (data.active_session) {
            currentSessionId = data.active_session.id;
            localStorage.setItem(STORAGE_KEY, currentSessionId);
        }
        
        // Render the ViewData
        renderViewData(data);
        
        // Auto-attach if backend says we should
        if (data.ui_state?.should_attach && currentSessionId) {
            ensureAttached(currentSessionId);
        }
    };
    
    eventSource.onerror = () => {
        console.error('Stream connection error');
        // Reconnect after delay
        reconnectTimeout = setTimeout(connectViewStream, 3000);
    };
}

/**
 * Ensure we're attached to the session stream.
 * Called on page load and after session switch.
 */
export function ensureAttached(sessionId) {
    if (!sessionId) {
        // Check localStorage
        sessionId = localStorage.getItem(STORAGE_KEY);
    }
    
    if (sessionId && sessionId !== currentSessionId) {
        // Switch to different session
        sendAction({
            action: 'switch_session',
            session_id: sessionId,
        });
    }
}

/**
 * Send an action to the backend.
 */
export async function sendAction(action) {
    try {
        const response = await fetch('/v1/view', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(action),
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        // Response is handled by the SSE stream
    } catch (err) {
        console.error('Failed to send action:', err);
    }
}

/**
 * Get last active session from localStorage.
 */
export function getLastActiveSession() {
    return localStorage.getItem(STORAGE_KEY);
}
```

### Simplified `app.js`

```javascript
// app.js - Minimal, just wiring

import { connectViewStream, sendAction, getLastActiveSession, ensureAttached } from './stream.js';

// Connect to view stream on load
document.addEventListener('DOMContentLoaded', () => {
    connectViewStream();
    
    // Auto-attach to last active session from localStorage
    const lastSession = getLastActiveSession();
    if (lastSession) {
        ensureAttached(lastSession);
    }
});

// Wire up UI events to send actions
document.getElementById('send-btn').addEventListener('click', () => {
    const input = document.getElementById('prompt-input');
    const message = input.value.trim();
    if (!message) return;
    
    sendAction({
        action: 'send_message',
        session_id: state.activeSessionId,
        message: message,
    });
    
    input.value = '';
});

document.getElementById('new-session').addEventListener('click', () => {
    sendAction({
        action: 'create_session',
        model: document.getElementById('model-select').value,
    });
});

// ... other UI event handlers
```

---

## Implementation Tasks

### Phase 1: Backend View Data Module
- [ ] Create `view_data.py` with Pydantic models
- [ ] Implement `ViewDataGenerator` class
- [ ] Add helper methods for message conversion (structured blocks)
- [ ] Add helper methods for pending actions
- [ ] Add helper methods for tool rules
- [ ] Add first-class `permission_status` to SessionView
- [ ] Add `should_attach` flag to UIState

### Phase 2: Backend Stream Endpoint
- [ ] Create `/v1/view` POST endpoint
- [ ] Create `/v1/view/stream` SSE endpoint
- [ ] Implement `_process_view_action()` function
- [ ] Handle all action types including `get_view`
- [ ] Add `switch_session` action to restore session from DB
- [ ] Add streaming support for long-running operations
- [ ] Run `send_message` in background task for streaming

### Phase 3: Backend Session Restore
- [ ] Update `get_or_create()` to load messages from DB
- [ ] Reconstruct `Session.messages` from database records
- [ ] Parse Anthropic content blocks into structured format
- [ ] Handle `<thought>` tag extraction during restore

### Phase 4: Frontend Renderer
- [ ] Create `renderer.js` module
- [ ] Implement `renderViewData()` function
- [ ] Implement message rendering with pre-parsed content blocks
- [ ] Implement session list rendering
- [ ] Implement pending actions rendering (first-class status)
- [ ] Implement UI state rendering
- [ ] Remove `<thought>` regex parsing (backend handles this)

### Phase 5: Frontend Stream Client
- [ ] Create `stream.js` module
- [ ] Implement persistent SSE connection
- [ ] Implement `sendAction()` function
- [ ] Add localStorage for `activeSessionId`
- [ ] Add auto-attach on page load
- [ ] Add reconnection logic

### Phase 6: Refactor Frontend
- [ ] Remove `session-manager.js` business logic
- [ ] Remove `stream-handler.js` event handling
- [ ] Simplify `app.js` to just wiring + auto-attach
- [ ] Remove `api.js` direct fetch calls
- [ ] Keep `ui-components.js` for DOM helpers only

### Phase 7: Cleanup
- [ ] Remove old endpoints from `main.py`
- [ ] Remove `db/sessions` endpoints (replaced by ViewData)
- [ ] Update database queries if needed
- [ ] Test full flow including page refresh resumption
- [ ] Test session switching
- [ ] Test permission approval after refresh

---

## Files to Create/Modify

### New Files
- `server/app/view_data.py` - View data module
- `server/app/static/js/renderer.js` - Frontend renderer
- `server/app/static/js/stream.js` - Frontend stream client

### Modified Files
- `server/app/main.py` - Add `/v1/view` endpoint
- `server/app/sessions.py` - Add helper methods if needed
- `server/app/static/js/app.js` - Simplify to minimal wiring
- `server/app/static/js/state.js` - Minimal state

### Files to Remove/Deprecate
- `server/app/static/js/session-manager.js` - Business logic moves to backend
- `server/app/static/js/stream-handler.js` - Replaced by stream.js
- `server/app/static/js/api.js` - Replaced by stream.js
- `server/app/static/js/permission-manager.js` - Business logic moves to backend

---

## Success Criteria

1. **Single Endpoint**: All communication via `/v1/view`
2. **Backend Owns State**: No session/message management in frontend
3. **Pure Renderer**: Frontend only renders ViewData objects
4. **Active Session Only**: ViewData contains messages for active session only
5. **Real-time Updates**: SSE stream keeps frontend in sync
6. **No Reconstruction**: Frontend never reconstructs state from database
7. **Persistent Connection**: Single SSE connection maintained for session lifetime
8. **Auto-Reattach**: Page refresh automatically reconnects to running session
9. **Structured Messages**: No `<thought>` tag parsing in frontend
10. **First-Class Status**: Permission status is explicit, not inferred
11. **localStorage Persistence**: Active session remembered across refreshes
