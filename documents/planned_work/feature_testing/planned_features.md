# Planned Features — Pending Test Coverage

These frontend features exist in the codebase but have no JavaScript unit test coverage. Each needs a test added to `server/app/static/js/__tests__/`.

---

## 1. Keyboard Shortcuts (app.js)

### 1.1 Enter sends message
- When user presses Enter (without Shift), `handleSend()` is called.
- If input is empty, nothing happens.
- If streaming, sends interrupt instead.

### 1.2 Shift+Enter inserts newline
- Shift+Enter does not trigger send, allows newline in textarea.

### 1.3 Escape interrupts streaming
- When streaming, pressing Escape sends `interrupt` action.
- When not streaming, Escape does nothing.

---

## 2. Input Area Behavior (app.js)

### 2.1 Textarea auto-resize
- Input event sets textarea height to `min(scrollHeight, 160)`.

### 2.2 Character count updates
- Input event updates `#char-count` with `input.value.length`.

### 2.3 Send button clears input
- After sending, input is cleared and height reset to `auto`.
- Character count resets to `0`.

### 2.4 Conversation hash reset on send
- `conversation.dataset.hash` is cleared before sending to force re-render.

---

## 3. Slash Command Menu (app.js)

### 3.1 Menu opens on `/`
- Typing `/` as first character opens `#slash-menu`.

### 3.2 Menu closes on non-`/` input
- When input no longer starts with `/`, menu closes.

### 3.3 Command insertion
- Clicking a slash item inserts the command text into input and closes menu.
- Input is focused after insertion.

---

## 4. Mode Pill Cycling (app.js)

### 4.1 Click cycles through modes
- Click cycles: `plan` → `acceptEdits` → `default` → `plan`.

### 4.2 Sends set_mode action
- On click with active session, sends `set_mode` action with new mode.

### 4.3 No action without session
- When no active session, click only updates local state.

---

## 5. Permission Mode Dropdown (app.js)

### 5.1 Change event sends set_mode
- Selecting a new mode sends `set_mode` action.
- No action if no active session.

---

## 6. Model Dropdown (app.js)

### 6.1 Change event sends set_model
- Selecting a new model sends `set_model` action.
- No action if no active session.

---

## 7. Sidebar Toggle (app.js)

### 7.1 Mobile toggle opens/closes sidebar
- Clicking `#mobile-toggle` toggles `.open` class on `#sidebar`.

---

## 8. Collapsible Sections (app.js)

### 8.1 Sidebar section toggle
- Clicking `[data-toggle]` header toggles `.collapsed` on parent.
- Chevron rotates when collapsed.

### 8.2 Tool block header toggle
- Clicking `[data-toggle-tool]` toggles `.hidden` on tool body.
- Chevron toggles `.open` class.

### 8.3 Tool output header toggle
- Clicking `.tool-output-header` toggles `.hidden` on output body.
- Chevron toggles `.open` class.

---

## 9. Right Panel Tabs (app.js)

### 9.1 Tab click switches content
- Clicking a `.rp-tab` removes `.active` from all tabs and content.
- Adds `.active` to clicked tab and matching `[data-rp-content]`.

---

## 10. Max Turns Slider (app.js)

### 10.1 Slider updates label
- Moving `#max-turns` slider updates `#max-turns-val` text.

---

## 11. Session Deletion (session-manager.js)

### 11.1 Delete session from sidebar
- Delete action sends `delete_session` via `sendAction`.
- Session removed from list, conversation cleared.

---

## 12. Session Event Subscription (stream-handler.js)

### 12.1 subscribeToSessionEvents
- Creates EventSource to `/v1/sessions/{id}/events`.
- Handles all event types via `handleStreamEvent`.
- Skips heartbeat events.
- Sets streaming to false on completion.

---

## 13. New Session Button (app.js)

### 13.1 Click creates session
- Clicking `#new-session` sends `create_session` with selected model.

---

## 14. Options Toggles (app.js — currently no-ops)

### 14.1 Extended thinking toggle
- Toggle state tracked (currently UI-only, no backend wiring).

### 14.2 Stream partial messages toggle
- Toggle state tracked (currently UI-only).

### 14.3 Persist transcript toggle
- Toggle state tracked (currently UI-only).

---

## Priority Order

1. **Keyboard shortcuts** — critical UX, easy to test
2. **Slash command menu** — user-facing feature
3. **Mode pill cycling** — core permission UX
4. **Collapsible sections** — DOM behavior
5. **Right panel tabs** — DOM behavior
6. **Session deletion** — CRUD completeness
7. **Input auto-resize/char count** — DOM behavior
8. **Model/permission dropdowns** — event handlers
9. **Max turns slider** — simple DOM
10. **Session event subscription** — SSE feature
