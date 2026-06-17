# Business Logic Review: Session Management & Resumption

## Core Issue: Frontend State vs. Backend Truth
The primary reason resuming chats after a refresh or switch is problematic is that the **Frontend is acting as the primary state manager** for the active conversation's "live" state, while the Backend treats the session as a transient object that is largely forgotten by the UI until a new turn is started.

### 1. The "Resumption" Gap
When a page refresh occurs:
- **State Loss**: The frontend loses `activeSessionId` and all volatile state (`streaming`, `awaitingApproval`).
- **Connection Gap**: Even if the backend `Session` is still running the agent loop (because it's an `async` task), the frontend has no mechanism to automatically re-attach to the event stream.
- **Passive Restoration**: `switchToSession` only loads *history*. It does not check if the session is currently in a `running` state to automatically call `subscribeToSessionEvents`.

### 2. Logic Leaks (Frontend doing Backend work)
The frontend is performing "reconstruction" logic that should be handled by the backend:

#### A. Message Structuring & Parsing
- **Thought Parsing**: `session-manager.js` uses regex to find `<thought>` tags in stored content. This means the backend is storing "raw" logs, and the frontend is responsible for the semantic interpretation of what is a "thought" vs "text".
- **Tool-to-Assistant Mapping**: The frontend uses a loop variable (`currentAssistantEl`) to guess which tool result belongs to which assistant bubble. If the message history is slightly malformed, the UI breaks.

#### B. Status Mapping
- **Permission State**: The frontend determines if a tool block is `pending_approval` based on the presence of `pending_request_id`. While correct, the *truth* of whether a session is currently blocked by a permission request is not surfaced as a first-class session status from the API.

#### C. Event Subscription Orchestration
- The frontend decides *when* to subscribe to events (e.g., only after an approval). This creates a fragmented experience where the "live" connection is intermittently opened and closed, rather than being a persistent "remote control" link to the agent loop.

---

## Recommendations for "Thin Client" Architecture

### 1. Structured Message Schema
Instead of storing raw strings with `<thought>` tags, the backend should store and serve messages as structured blocks:
- `type: "thinking", content: "..."`
- `type: "text", content: "..."`
- `type: "tool_use", ...`
This removes all parsing logic from the frontend.

### 2. First-Class Session State
The `/v1/db/sessions/{id}` endpoint should return a rich `state` object:
- `status`: `idle` | `running` | `awaiting_permission`
- `current_pending_request`: The full permission object if `awaiting_permission`.
- `last_active_turn`: Which turn is currently executing.

### 3. Active Session "Attach" Flow
The frontend should implement a "Re-attach" logic on load:
1. Determine `activeSessionId` (e.g., from URL or last-used in localStorage).
2. Call a "get session status" endpoint.
3. If status is `running` or `awaiting_permission`, immediately call `subscribeToSessionEvents` and render the pending permission cards.

### 4. Persistent Event Stream
Instead of subscribing only on approval, the frontend should maintain a single, stable SSE connection to the active session for its entire lifetime. The backend should handle the "idle" periods with heartbeats, and the frontend should simply pipe these events to the UI.
