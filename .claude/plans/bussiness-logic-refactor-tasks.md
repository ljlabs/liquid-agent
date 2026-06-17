# Tasks: Business Logic Refactor

## Phase 1: Backend View Data Module
- [ ] Create `view_data.py` with Pydantic models
- [ ] Implement `ViewDataGenerator` class
- [ ] Add helper methods for message conversion (structured blocks)
- [ ] Add helper methods for pending actions
- [ ] Add helper methods for tool rules
- [ ] Add first-class `permission_status` to SessionView
- [ ] Add `should_attach` flag to UIState

## Phase 2: Backend Stream Endpoint
- [ ] Create `/v1/view` POST endpoint
- [ ] Create `/v1/view/stream` SSE endpoint
- [ ] Implement `_process_view_action()` function
- [ ] Handle all action types including `get_view`
- [ ] Add `switch_session` action to restore session from DB
- [ ] Add streaming support for long-running operations
- [ ] Run `send_message` in background task for streaming

## Phase 3: Backend Session Restore
- [ ] Update `get_or_create()` to load messages from DB
- [ ] Reconstruct `Session.messages` from database records
- [ ] Parse Anthropic content blocks into structured format
- [ ] Handle `<thought>` tag extraction during restore

## Phase 4: Frontend Renderer
- [ ] Create `renderer.js` module
- [ ] Implement `renderViewData()` function
- [ ] Implement message rendering with pre-parsed content blocks
- [ ] Implement session list rendering
- [ ] Implement pending actions rendering (first-class status)
- [ ] Implement UI state rendering
- [ ] Remove `<thought>` regex parsing (backend handles this)

## Phase 5: Frontend Stream Client
- [ ] Create `stream.js` module
- [ ] Implement persistent SSE connection
- [ ] Implement `sendAction()` function
- [ ] Add localStorage for `activeSessionId`
- [ ] Add auto-attach on page load
- [ ] Add reconnection logic

## Phase 6: Refactor Frontend
- [ ] Remove `session-manager.js` business logic
- [ ] Remove `stream-handler.js` event handling
- [ ] Simplify `app.js` to just wiring + auto-attach
- [ ] Remove `api.js` direct fetch calls
- [ ] Keep `ui-components.js` for DOM helpers only

## Phase 7: Cleanup
- [ ] Remove old endpoints from `main.py`
- [ ] Remove `db/sessions` endpoints (replaced by ViewData)
- [ ] Update database queries if needed
- [ ] Test full flow including page refresh resumption
- [ ] Test session switching
- [ ] Test permission approval after refresh
