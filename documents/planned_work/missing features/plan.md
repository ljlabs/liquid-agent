# Missing Features Implementation Plan

**Date:** 2026-06-19
**Source:** `documents/planned_work/feature_testing/planned_features.md`
**Scope:** 14 frontend features requiring JavaScript unit test coverage

---

## Overview

All 14 features are frontend-only (DOM/event behavior). They live in three JS files:
- `app.js` — 12 features (keyboard, input, slash menu, mode pill, dropdowns, sidebar, collapsibles, tabs, slider, new session, options)
- `session-manager.js` — 1 feature (session deletion)
- `stream-handler.js` — 1 feature (session event subscription)

## Coding Philosophy

- **Unit tests**: Isolated — no real LLM, DB, network, or filesystem. All dependencies mocked via `vi.mock()`, `vi.fn()`, `Object.defineProperty`.
- **Integration tests**: Use `mock-model` ID, mock LLM server (`server/tests/mock_llm_server.py`), and HTTP-only interaction. No server startup fixtures.
- **Test infrastructure**: vitest 3.2.1 + jsdom 26.1.0, `globals: true`, `setupFiles: ['./__tests__/setup.js']`.

## Critical Prerequisite: app.js Refactoring

`app.js` wires all event listeners at module load time (no exported `init()` function). This blocks testability. **Before any agent can test app.js features, it must refactor to export an `init()` function** that registers event listeners. Tests call `init()` after setting up controlled DOM.

**Refactor scope:**
- Extract all `addEventListener` calls into `export function init()`
- Export testable helper functions (`handleSend`, `handleSlashCommand`, `cycleMode`, etc.)
- Preserve module-load behavior for production (call `init()` at bottom of file)
- All existing features must continue working unchanged

---

## Agent Execution Order

Agents should execute in this order to manage dependencies:

1. **Agent A** (app.js refactor) — MUST complete first, all other app.js agents depend on it
2. **Agents B–E** (app.js feature clusters) — Can run in parallel after Agent A
3. **Agents F–G** (session-manager.js, stream-handler.js) — Independent, can run any time

---

## Agent A: app.js Refactoring + Keyboard Shortcuts + Slash Menu

**Files to modify:** `server/app/static/js/app.js`, `server/app/static/js/__tests__/app.test.js` (new)

### Cluster Rationale

This agent does the foundational refactor AND implements the first two feature groups. The refactor is prerequisite for all app.js testing. Keyboard shortcuts and slash menu are tightly coupled (both are input event handlers) and share the same `handleSend` function.

### Deliverables

1. Refactor `app.js` to export `init()` and testable helpers
2. Write `app.test.js` with tests for features 1.1–1.3 and 3.1–3.3

### Unit Tests (app.test.js)

```
Feature 1.1 — Enter sends message
├── test: Enter without Shift calls handleSend()
├── test: Enter on empty input does nothing
├── test: Enter during streaming sends interrupt action
└── test: Shift+Enter does NOT call handleSend()

Feature 1.2 — Shift+Enter inserts newline
├── test: Shift+Enter inserts \n into textarea
└── test: Shift+Enter does NOT trigger send

Feature 1.3 — Escape interrupts streaming
├── test: Escape during streaming sends interrupt action
├── test: Escape when NOT streaming does nothing
└── test: Escape calls sendAction with interrupt payload

Feature 3.1 — Menu opens on /
├── test: Typing / as first character shows #slash-menu
├── test: Typing / not as first character does NOT show menu
└── test: Menu has correct command items

Feature 3.2 — Menu closes on non-/ input
├── test: Changing input away from / hides #slash-menu
├── test: Empty input hides menu
└── test: Input starting with / keeps menu open

Feature 3.3 — Command insertion
├── test: Clicking slash item inserts command text into input
├── test: Clicking slash item closes menu
├── test: Input is focused after insertion
└── test: Inserted text matches command value
```

**Total: ~16 unit tests**

### Integration Tests (feature_completion_tests/test_keyboard_slash.py)

```
Feature 1.1+1.2+1.3 — Keyboard shortcuts via mock LLM
├── test_keyboard_enter_sends_message
│   Create session, type message, simulate Enter → message sent, assistant responds
├── test_shift_enter_inserts_newline
│   Type message, simulate Shift+Enter → newline in textarea, no send
└── test_escape_interrupts_streaming
    Send message (mock LLM delays), simulate Escape → streaming stops, status=idle

Feature 3.1+3.2+3.3 — Slash menu
├── test_slash_menu_opens_on_slash
│   Type "/" → menu visible with correct commands
├── test_slash_menu_command_insertion
│   Type "/", click command → command in input, menu hidden
└── test_slash_menu_closes_on_non_slash
    Type "/", backspace → menu hidden
```

**Total: ~6 integration tests**

### Verification Criteria

- [ ] `app.js` exports `init()` function
- [ ] All existing app.js behavior preserved (manual smoke test)
- [ ] `app.test.js` passes: `cd server/app/static/js && npm test`
- [ ] Integration tests pass with mock LLM server
- [ ] No real LLM, DB, or network calls in unit tests

---

## Agent B: Input Area + Options Toggles + Max Turns Slider

**Files to modify:** `server/app/static/js/app.js` (add tests), `server/app/static/js/__tests__/app.test.js` (extend)

### Cluster Rationale

These three feature groups are all simple DOM update behaviors with no cross-dependencies. They share the `app.js` test file but test independent event handlers (input event, change events, input events on slider).

### Deliverables

Extend `app.test.js` with tests for features 2.1–2.4, 10.1, and 14.1–14.3.

### Unit Tests

```
Feature 2.1 — Textarea auto-resize
├── test: Input event sets textarea height to min(scrollHeight, 160)
├── test: Textarea height resets to auto after send
└── test: Auto-resize respects max height of 160px

Feature 2.2 — Character count updates
├── test: Input event updates #char-count with value.length
├── test: Empty input shows "0"
└── test: Long text shows correct character count

Feature 2.3 — Send button clears input
├── test: After send, textarea value is empty
├── test: After send, textarea height is "auto"
└── test: After send, #char-count shows "0"

Feature 2.4 — Conversation hash reset on send
├── test: Send clears conversation.dataset.hash
└── test: Hash is cleared BEFORE sending action

Feature 10.1 — Max turns slider
├── test: Moving #max-turns slider updates #max-turns-val text
├── test: Slider value matches displayed text
└── test: Default slider value is 25

Feature 14.1 — Extended thinking toggle
├── test: Toggle click updates toggle state
└── test: Toggle state is tracked (UI-only, no backend call)

Feature 14.2 — Stream partial messages toggle
├── test: Toggle click updates toggle state
└── test: Toggle state is tracked (UI-only)

Feature 14.3 — Persist transcript toggle
├── test: Toggle click updates toggle state
└── test: Toggle state is tracked (UI-only)
```

**Total: ~18 unit tests**

### Integration Tests

```
Feature 2.1+2.2+2.3 — Input behavior end-to-end
├── test_auto_resize_updates_with_input
│   Type long text → textarea height increases, capped at 160px
├── test_character_count_updates_live
│   Type text → character count updates in real-time
└── test_send_clears_input_and_count
    Type text, send → textarea empty, count=0, height=auto

Feature 10.1 — Max turns slider end-to-end
├── test_slider_updates_max_turns_label
│   Move slider → label text updates
└── test_slider_value_matches_backend
    Move slider, create session → session max_turns matches slider value

Feature 14.1-14.3 — Options toggles
├── test_extended_thinking_toggle_state
│   Click toggle → state tracked
└── test_options_toggles_initial_state
    On load → all toggles default to "on"
```

**Total: ~7 integration tests**

### Verification Criteria

- [ ] All input area behaviors work (auto-resize, char count, clear on send)
- [ ] `app.test.js` passes with new tests
- [ ] Integration tests pass with mock LLM
- [ ] No overlap with Agent A's test cases

---

## Agent C: Mode Pill + Permission Dropdown + Model Dropdown

**Files to modify:** `server/app/static/js/app.js` (add tests), `server/app/static/js/__tests__/app.test.js` (extend)

### Cluster Rationale

These three features all involve selecting a mode or model and sending an action to the backend. They share the pattern: user interaction → update local state → if session exists, send action. Grouped because they test the same `sendAction` integration pattern.

### Deliverables

Extend `app.test.js` with tests for features 4.1–4.3, 5.1, and 6.1.

### Unit Tests

```
Feature 4.1 — Click cycles through modes
├── test: Click cycles plan → acceptEdits → default → plan
├── test: Mode pill text updates on cycle
└── test: Mode pill CSS class changes on cycle

Feature 4.2 — Sends set_mode action
├── test: Click with active session sends set_mode action
├── test: Action payload includes new mode name
└── test: Action payload includes session_id

Feature 4.3 — No action without session
├── test: Click without active session only updates local state
├── test: No sendAction called when session is null
└── test: Mode state still cycles even without session

Feature 5.1 — Permission mode dropdown
├── test: Change event sends set_mode action with selected value
├── test: No action if no active session
├── test: Dropdown options match expected modes
└── test: Default selection is "default" mode

Feature 6.1 — Model dropdown
├── test: Change event sends set_model action with selected model
├── test: No action if no active session
├── test: Dropdown populated from available_models
└── test: Default model matches session model
```

**Total: ~16 unit tests**

### Integration Tests

```
Feature 4.1+4.2+4.3 — Mode pill cycling
├── test_mode_pill_cycles_through_modes
│   Click mode pill 3 times → returns to original mode
├── test_mode_pill_sends_action_to_backend
│   Create session, click mode pill → session permission_mode updated
└── test_mode_pill_without_session_no_action
    No session, click pill → mode cycles locally, no API call

Feature 5.1 — Permission mode dropdown
├── test_permission_dropdown_sends_mode
│   Create session, change dropdown → permission_mode updated
└── test_permission_dropdown_persists
    Change mode, switch sessions, switch back → mode preserved

Feature 6.1 — Model dropdown
├── test_model_dropdown_sends_model
│   Create session, change dropdown → model updated
└── test_model_dropdown_populated
    On load → dropdown shows all available_models
```

**Total: ~7 integration tests**

### Verification Criteria

- [ ] Mode pill cycles correctly through all three modes
- [ ] Permission dropdown sends correct action
- [ ] Model dropdown sends correct action
- [ ] All tests pass without real backend calls (unit) or with mock LLM (integration)

---

## Agent D: Sidebar Toggle + Collapsible Sections + Right Panel Tabs

**Files to modify:** `server/app/static/js/app.js` (add tests), `server/app/static/js/__tests__/app.test.js` (extend)

### Cluster Rationale

These are pure DOM toggle behaviors with no backend communication. They test CSS class toggling and content visibility. Grouped because they share the same testing pattern: click element → assert class/visibility change.

### Deliverables

Extend `app.test.js` with tests for features 7.1, 8.1–8.3, and 9.1.

### Unit Tests

```
Feature 7.1 — Mobile sidebar toggle
├── test: Click #mobile-toggle adds .open to #sidebar
├── test: Click #mobile-toggle again removes .open from #sidebar
└── test: Toggle does not affect sidebar on desktop

Feature 8.1 — Sidebar section toggle
├── test: Click [data-toggle] header toggles .collapsed on parent
├── test: Chevron rotates when collapsed
└── test: Multiple sections toggle independently

Feature 8.2 — Tool block header toggle
├── test: Click [data-toggle-tool] toggles .hidden on tool body
├── test: Chevron toggles .open class
└── test: Tool block defaults to expanded

Feature 8.3 — Tool output header toggle
├── test: Click .tool-output-header toggles .hidden on output body
├── test: Chevron toggles .open class
└── test: Output section defaults to collapsed

Feature 9.1 — Right panel tabs
├── test: Click .rp-tab removes .active from all tabs
├── test: Click .rp-tab adds .active to clicked tab
├── test: Click .rp-tab adds .active to matching [data-rp-content]
├── test: Click .rp-tab removes .active from non-matching content
└── test: Default active tab is first tab
```

**Total: ~16 unit tests**

### Integration Tests

```
Feature 7.1 — Sidebar toggle
├── test_mobile_toggle_opens_sidebar
│   Simulate mobile viewport, click toggle → sidebar visible
└── test_mobile_toggle_closes_sidebar
    Sidebar open, click toggle → sidebar hidden

Feature 8.1-8.3 — Collapsible sections
├── test_sidebar_section_collapses
│   Click section header → section body hidden
├── test_tool_block_collapses
│   Create tool block, click header → tool body hidden
└── test_tool_output_collapses
    Tool block with output, click output header → output hidden

Feature 9.1 — Right panel tabs
├── test_tab_click_switches_content
│   Click "Usage" tab → usage content visible, files content hidden
└── test_tab_switch_multiple
    Click Files → Usage → Logs → correct content shown each time
```

**Total: ~7 integration tests**

### Verification Criteria

- [ ] Sidebar toggle works on mobile viewport
- [ ] Collapsible sections toggle correctly
- [ ] Right panel tabs switch content
- [ ] All CSS class assertions match expected states

---

## Agent E: New Session Button

**Files to modify:** `server/app/static/js/app.js` (add tests), `server/app/static/js/__tests__/app.test.js` (extend)

### Cluster Rationale

Small standalone feature. Kept separate from Agent C (mode/model) because new session creation has different behavior (creates session, clears conversation, focuses input) vs. mode/model (changes existing session properties).

### Deliverables

Extend `app.test.js` with tests for feature 13.1.

### Unit Tests

```
Feature 13.1 — New session button
├── test: Click #new-session sends create_session action
├── test: Action includes selected model
├── test: Conversation area is cleared after creation
├── test: Input is focused after creation
└── test: Button is disabled during creation
```

**Total: ~5 unit tests**

### Integration Tests

```
Feature 13.1 — New session creation
├── test_new_session_button_creates_session
│   Click #new-session → new session appears in sidebar, becomes active
├── test_new_session_clears_conversation
│   Existing session with messages, click new → conversation empty
└── test_new_session_focuses_input
    Click new session → textarea receives focus
```

**Total: ~3 integration tests**

### Verification Criteria

- [ ] New session button creates a session with correct model
- [ ] Conversation clears on new session
- [ ] Input receives focus after creation

---

## Agent F: Session Deletion (session-manager.js)

**Files to modify:** `server/app/static/js/session-manager.js`, `server/app/static/js/__tests__/session-manager.test.js` (extend existing)

### Cluster Rationale

Standalone feature in session-manager.js. Already has 8 existing tests; this adds the deletion test. No overlap with app.js agents.

### Deliverables

Extend `session-manager.test.js` with tests for feature 11.1.

### Unit Tests

```
Feature 11.1 — Delete session from sidebar
├── test: Delete action sends delete_session via sendAction
├── test: Session removed from sidebar list
├── test: Conversation area cleared after deletion
├── test: Active session reset if deleted session was active
└── test: Delete non-active session does not clear conversation
```

**Total: ~5 unit tests**

### Integration Tests

```
Feature 11.1 — Session deletion
├── test_delete_session_removes_from_sidebar
│   Create session, delete → session no longer in sidebar
├── test_delete_active_session_clears_conversation
│   Active session with messages, delete → conversation empty
└── test_delete_non_active_session_preserves_view
    Two sessions, delete non-active → active session unchanged
```

**Total: ~3 integration tests**

### Verification Criteria

- [ ] Session deletion removes from sidebar
- [ ] Active session deletion clears conversation
- [ ] Non-active deletion preserves current view

---

## Agent G: Session Event Subscription (stream-handler.js)

**Files to modify:** `server/app/static/js/stream-handler.js`, `server/app/static/js/__tests__/stream-handler.test.js` (extend existing)

### Cluster Rationale

Standalone feature in stream-handler.js. Already has 16 existing tests; this adds the subscription test. No overlap with other agents.

### Deliverables

Extend `stream-handler.test.js` with tests for feature 12.1.

### Unit Tests

```
Feature 12.1 — subscribeToSessionEvents
├── test: Creates EventSource to /v1/sessions/{id}/events
├── test: Handles all event types via handleStreamEvent
├── test: Skips heartbeat events
├── test: Sets streaming to false on completion
├── test: Cleans up EventSource on disconnect
└── test: Handles EventSource connection error
```

**Total: ~6 unit tests**

### Integration Tests

```
Feature 12.1 — Session event subscription
├── test_subscribe_to_session_events
│   Create session, subscribe → EventSource connected to correct URL
├── test_session_events_update_ui
│   Subscribe, mock LLM emits events → UI updates with each event
└── test_subscription_cleanup_on_disconnect
    Subscribe, disconnect → EventSource closed, no memory leak
```

**Total: ~3 integration tests**

### Verification Criteria

- [ ] EventSource connects to correct session URL
- [ ] All event types handled correctly
- [ ] Heartbeat events skipped
- [ ] Cleanup on disconnect

---

## Documentation Update Steps

After all agents complete, run a final documentation sweep:

### Step 1: Update Feature Walkthrough (`documents/guides/feature_walkthrough.md`)

For each tested feature, add a note under the relevant section:

```
**Test coverage:** Unit tests in `app.test.js` / `session-manager.test.js` / `stream-handler.test.js`.
Integration tests in `test_keyboard_slash.py`, etc.
```

Specific sections to update:
- §9.4.6 Keyboard Shortcuts — add test references
- §9.4.7 Slash Command Menu — add test references
- §9.4.2 Input Box — add test references for auto-resize, char count
- §9.4.4 Mode Pill — add test references
- §9.2.5 Permission Mode Section — add test references
- §9.2.4 Connection Section — add test references for model dropdown
- §9.2.8 Options Section — add test references
- §9.3.1 Header — add test references for max turns slider
- §9.2.3 Session List — add test references for new session button
- §13.1 Sidebar Sections — add test references
- §13.2 Tool Blocks — add test references
- §9.5.1 Tab Navigation — add test references
- §9.1 Mobile toggle — add test references

### Step 2: Update Test Feature Mapping (`documents/guides/test_feature_mapping.md`)

Add new rows to the Feature Coverage Matrix:

- §9 Frontend UI — fill in the "(No frontend unit tests exist)" placeholders
- §13 Collapsible UI Sections — fill in
- Add new subsections for each feature with test file references

Update the Test Inventory Summary table:
- Add `app.test.js` row with test count
- Update `session-manager.test.js` and `stream-handler.test.js` test counts
- Update total count

Update the "Features with NO Test Coverage" table:
- Remove features that now have test coverage
- Mark remaining untested features

### Step 3: Update Test Dependency Report (`documents/guides/test_dependency_report.md`)

Add a new section for JS test files:
- `app.test.js` — list any dependency violations
- Updated `session-manager.test.js` and `stream-handler.test.js` entries

---

## Agent Dependency Map

```
Agent A (refactor + keyboard + slash)
  ↓ (provides init() and test file foundation)
Agents B, C, D, E (parallel — extend app.test.js)
  ↓ (all write to app.test.js, but different test blocks)
Agent F (session-manager.js — independent)
Agent G (stream-handler.js — independent)
  ↓ (all complete)
Documentation Sweep (final step)
```

**Note:** Agents B–E must coordinate on `app.test.js` to avoid merge conflicts. Each agent adds tests in its own `describe()` block:
- Agent A: `describe('Keyboard Shortcuts')`, `describe('Slash Command Menu')`
- Agent B: `describe('Input Area')`, `describe('Options Toggles')`, `describe('Max Turns Slider')`
- Agent C: `describe('Mode Pill')`, `describe('Permission Dropdown')`, `describe('Model Dropdown')`
- Agent D: `describe('Sidebar Toggle')`, `describe('Collapsible Sections')`, `describe('Right Panel Tabs')`
- Agent E: `describe('New Session Button')`

---

## Summary

| Agent | Features | Unit Tests | Integration Tests | Files Modified |
|-------|----------|------------|-------------------|----------------|
| A | Refactor + 1.1–1.3, 3.1–3.3 | ~16 | ~6 | app.js, app.test.js (new) |
| B | 2.1–2.4, 10.1, 14.1–14.3 | ~18 | ~7 | app.test.js (extend) |
| C | 4.1–4.3, 5.1, 6.1 | ~16 | ~7 | app.test.js (extend) |
| D | 7.1, 8.1–8.3, 9.1 | ~16 | ~7 | app.test.js (extend) |
| E | 13.1 | ~5 | ~3 | app.test.js (extend) |
| F | 11.1 | ~5 | ~3 | session-manager.test.js (extend) |
| G | 12.1 | ~6 | ~3 | stream-handler.test.js (extend) |
| **Total** | **14 features** | **~82** | **~36** | **4 files** |
