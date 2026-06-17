# Business Logic Review: Frontend vs Backend Distribution

## Executive Summary

The current architecture has a **critical flaw**: the frontend is doing too much business logic that belongs in the backend. The root cause of chat resumption issues after page refresh or session switching is that **session state (conversation history) is not fully persisted/restored by the backend**, forcing the frontend to reconstruct it.

---

## Architecture Overview

### Backend (Python/FastAPI)
- **Session Management**: `sessions.py` - In-memory `Session` objects with `messages` list
- **Persistence**: `database.py` - SQLite for sessions, messages, permissions
- **API Layer**: `main.py` - REST endpoints for session lifecycle

### Frontend (JavaScript)
- **State**: `state.js` - Minimal (session ID, streaming state)
- **Session Manager**: `session-manager.js` - Session switching, message rendering
- **Stream Handler**: `stream-handler.js` - SSE event processing
- **UI Components**: `ui-components.js` - Message bubbles, tool blocks

---

## Critical Issues Found

### Issue 1: Session Messages Not Loaded on Restore

**Location**: `sessions.py:676-706` (`get_or_create` method)

**Problem**: When a session is recreated (after page refresh or switching), the backend:
1. Creates a new `Session` object with an **empty `messages` list**
2. Only restores `pending_permissions` from database
3. Does NOT load conversation history into `Session.messages`

**Code Path**:
```python
async def get_or_create(self, session_id: Optional[str], **kwargs: Any) -> Session:
    if session_id:
        existing = self.get(session_id)
        if existing is not None:
            return existing
    # Creates new Session - messages is empty!
    session = await self.create(**kwargs)
    # Only restores pending_permissions, NOT messages
    if session_id:
        pending_perms = await db.get_pending_permissions(session_id)
        # ... restore pending perms only
    return session
```

**Impact**:
- Agent has no conversation context when continuing
- LLM cannot reference previous messages
- Session appears to "forget" everything after refresh

---

### Issue 2: Dual State Management (Backend + Frontend)

**Backend State**:
- `Session.messages` - In-memory list (source of truth for LLM)
- `messages` table in SQLite - Persistence layer

**Frontend State**:
- Reconstructed from DB messages via `/v1/db/sessions/{sessionId}/messages`
- UI rendering logic in `session-manager.js:switchToSession()`

**Problem**: These can get out of sync:
- Backend modifies `Session.messages` during turn
- Backend writes to DB asynchronously
- Frontend reads from DB, may see stale data
- No transactional consistency between in-memory and DB

---

### Issue 3: Frontend Does Conversation Reconstruction

**Location**: `session-manager.js:27-152` (`switchToSession` function)

**What Frontend Does** (should be backend):
1. Fetches messages from DB: `dbFetch('/v1/db/sessions/${sessionId}/messages')`
2. Iterates through messages and reconstructs UI
3. Handles thinking blocks, tool use, tool results
4. Renders pending permission cards
5. Manages UI state (streaming, approval status)

**This is business logic that belongs in the backend**. The frontend should be a thin display layer, not a state reconstruction engine.

---

### Issue 4: Incomplete Session Restore in `get_or_create`

**Current Behavior**:
```python
# Restores: pending_permissions ✓
# Does NOT restore: messages ✗
# Does NOT restore: conversation context ✗
```

**Required Behavior**:
```python
# Should restore:
# 1. pending_permissions ✓
# 2. messages from DB into Session.messages
# 3. Reconstruct conversation history for LLM
# 4. Rebuild tool results and context
```

---

## Specific Code Locations

### Backend Issues

| File | Lines | Issue |
|------|-------|-------|
| `sessions.py` | 676-706 | `get_or_create()` doesn't load messages |
| `sessions.py` | 92 | `self.messages: List[Dict[str, Any]] = []` - empty on recreate |
| `sessions.py` | 478-658 | `run_turn()` assumes messages list has history |
| `main.py` | 342-496 | `/v1/sessions/stream` - doesn't restore history before turn |

### Frontend Issues (Business Logic in Wrong Place)

| File | Lines | Issue |
|------|-------|-------|
| `session-manager.js` | 27-152 | `switchToSession()` - reconstructs conversation from DB |
| `session-manager.js` | 42-119 | Message rendering logic - should be backend-provided |
| `session-manager.js` | 121-148 | Pending permission handling - frontend reconstruction |
| `stream-handler.js` | 105-248 | `handleStreamEvent()` - UI state management |

---

## Root Cause Analysis

**Why chat resumption fails after page refresh**:

1. **Page Refresh Flow**:
   - Frontend clears all state (JavaScript in-memory)
   - Frontend calls `switchToSession()` with session ID
   - Backend creates new `Session` object (empty messages)
   - Backend returns 404 or empty session
   - Frontend fetches messages from DB and reconstructs UI
   - **But**: Backend `Session.messages` is still empty
   - **Result**: Next message sent has no conversation context

2. **Session Switching Flow**:
   - User clicks different session in sidebar
   - Frontend calls `switchToSession(newSessionId)`
   - Backend may or may not have the session in memory
   - If not in memory: recreates with empty messages
   - Frontend reconstructs UI from DB
   - **But**: Backend `Session.messages` is empty
   - **Result**: Agent cannot continue coherently

---

## Recommended Fixes

### Fix 1: Backend Session Restore (Priority: Critical)

**File**: `sessions.py:676-706`

Add message loading to `get_or_create()`:

```python
async def get_or_create(self, session_id: Optional[str], **kwargs: Any) -> Session:
    if session_id:
        existing = self.get(session_id)
        if existing is not None:
            return existing
    
    session = await self.create(**kwargs)
    
    if session_id:
        # Restore pending permissions
        pending_perms = await db.get_pending_permissions(session_id)
        for perm in pending_perms:
            # ... existing restore logic ...
        
        # NEW: Restore messages from DB
        db_messages = await db.get_messages(session_id)
        session.messages = self._reconstruct_messages(db_messages)
    
    return session

def _reconstruct_messages(self, db_messages: list[dict]) -> list[dict]:
    """Convert DB messages to LLM format."""
    messages = []
    for msg in db_messages:
        if msg["role"] == "user":
            messages.append({"role": "user", "content": msg["content"]})
        elif msg["role"] == "assistant":
            # Reconstruct content blocks from stored data
            content_blocks = []
            if msg["type"] == "text":
                content_blocks.append({"type": "text", "text": msg["content"]})
            elif msg["type"] == "tool_use":
                content_blocks.append({
                    "type": "tool_use",
                    "id": msg["tool_id"],
                    "name": msg["tool_name"],
                    "input": json.loads(msg["tool_input"]) if msg["tool_input"] else {}
                })
            messages.append({"role": "assistant", "content": content_blocks})
        elif msg["role"] == "tool":
            # Tool results go in user message with other tool results
            messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": msg["tool_id"],
                    "content": msg["content"],
                    "is_error": msg["type"] == "tool_error"
                }]
            })
    return messages
```

### Fix 2: Frontend as Thin Display Layer

**File**: `session-manager.js`

Simplify `switchToSession()` to only display what backend provides:

```javascript
export async function switchToSession(sessionId, title, clickedItem) {
    state.activeSessionId = sessionId;
    document.getElementById('session-id-tag').textContent = sessionId;
    document.getElementById('session-title').textContent = title || 'Session';
    document.getElementById('conversation').innerHTML = '';
    
    // Load tool rules (display only)
    await loadSessionToolRules(sessionId);
    
    // Backend should provide rendered messages, not raw DB records
    // For now, continue with current approach but acknowledge it's wrong
    try {
        const data = await dbFetch(`/v1/db/sessions/${sessionId}/messages`);
        renderMessages(data.messages);
    } catch (e) {
        console.error('Failed to load messages:', e);
    }
}
```

### Fix 3: Add Backend Message Rendering Endpoint

**File**: `main.py`

Add endpoint that returns pre-rendered messages:

```python
@app.get("/v1/sessions/{session_id}/rendered-messages")
async def get_rendered_messages(session_id: str):
    """Return messages in format ready for frontend display."""
    session = manager.get(session_id)
    if session is None:
        # Recreate session to get messages
        session = await manager.get_or_create(session_id)
    
    return {
        "messages": [
            {
                "role": msg["role"],
                "content": msg.get("content", ""),
                "type": msg.get("type", "text"),
                "tool_name": msg.get("tool_name"),
                "tool_id": msg.get("tool_id"),
                "tool_input": msg.get("tool_input"),
                "pending_request_id": msg.get("pending_request_id"),
            }
            for msg in session.messages
        ]
    }
```

---

## Summary of Findings

| Category | Issue | Severity | Location |
|----------|-------|----------|----------|
| **Architecture** | Frontend doing backend work | High | `session-manager.js` |
| **Data Flow** | Session state not fully persisted | Critical | `sessions.py:676-706` |
| **State Management** | Dual state (memory + DB) | High | `sessions.py`, `database.py` |
| **Session Restore** | Messages not loaded | Critical | `sessions.py:get_or_create()` |
| **Frontend Role** | Too much business logic | Medium | `session-manager.js:27-152` |

---

## Conclusion

The frontend should be a **thin remote control** for the backend agent loop. Currently, it's doing significant state reconstruction that belongs in the backend. The core issue is that `Session.messages` is not restored from the database when a session is recreated, forcing the frontend to compensate.

**Priority Fix**: Update `get_or_create()` in `sessions.py` to load messages from the database and reconstruct the conversation history for the LLM.
