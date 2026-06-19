# Project Structure

## Directory Layout

```
model_containment/
├── server/                                  # Main FastAPI application
│   ├── app/
│   │   ├── main.py                         # FastAPI app, routes, SSE streaming
│   │   ├── sessions.py                     # Session manager, SDK client wrapper
│   │   ├── models.py                       # Pydantic request/response models
│   │   ├── database.py                     # SQLite persistence layer
│   │   ├── llm.py                          # Claude SDK integration (if separate)
│   │   ├── tools.py                        # Tool definitions and callbacks
│   │   ├── run.py                          # Session/turn execution logic
│   │   ├── view_data.py                    # Frontend ViewData generation
│   │   └── static/
│   │       ├── index.html                  # Single-page UI entry point
│   │       └── js/
│   │           ├── app.js                  # Main app initialization
│   │           ├── api.js                  # API client for backend communication
│   │           ├── session-manager.js      # Session lifecycle management
│   │           ├── stream-handler.js       # SSE event stream handling
│   │           ├── renderer.js             # DOM rendering logic
│   │           ├── permission-manager.js   # Permission UI & logic
│   │           ├── state.js                # Frontend state management
│   │           └── package.json            # Frontend test dependencies
│   ├── tests/
│   │   ├── test_sessions.py                # Unit tests for session manager
│   │   ├── test_streams.py                 # Integration tests for SSE/streaming
│   │   ├── mock_llm_server.py              # Mock Claude SDK for testing
│   │   └── ...
│   ├── data/                               # SQLite database (created at runtime)
│   │   └── sessions.db
│   ├── documents/                          # Development documentation
│   ├── venv/                               # Python virtual environment
│   ├── requirements.txt                    # Production backend dependencies
│   ├── requirements-dev.txt                # Development/test dependencies
│   ├── pytest.ini                          # Pytest configuration
│   ├── system_prompt.md                    # System prompt for Claude
│   └── README.md
│
├── documents/                              # Project-level documentation
│   ├── guides/
│   │   ├── feature_walkthrough.md          # Feature descriptions
│   │   ├── test_feature_mapping.md         # Test-to-feature mapping
│   │   ├── test_dependency_report.md       # Dependency analysis
│   │   └── ...
│   ├── planned_work/                       # Feature planning docs
│   └── research/                           # Research & analysis
│
├── .kiro/                                  # Kiro configuration
│   ├── steering/                           # Steering rules for AI assistants
│   │   ├── product.md                      # Product overview
│   │   ├── tech.md                         # Tech stack and build commands
│   │   └── structure.md                    # This file
│   └── specs/                              # Feature specifications
│
├── .claude/                                # Claude.ai/code workspace config
│   ├── agents/
│   ├── plans/
│   └── settings.local.json
│
├── .git/                                   # Git repository
├── .gitignore                              # Git ignore rules
└── CLAUDE.md                               # Project overview for Claude Code

```

## Key Files Overview

### Backend Entry Points
- **`app/main.py`**: Defines FastAPI routes:
  - Session lifecycle: `POST /v1/sessions`, `GET /v1/sessions`, `DELETE /v1/sessions/{id}`
  - Streaming chat: `POST /v1/sessions/stream` (returns SSE stream)
  - Permissions: `POST /v1/permissions/respond`, `GET /v1/tool-defaults`
  - Persistent DB: `GET /v1/db/sessions`, message retrieval

### Core Application Files
- **`app/sessions.py`**: 
  - `Session` class: Wraps Claude SDK client, manages permissions, emits events
  - `SessionManager`: In-memory session registry
  - Permission checking logic (`_check_permission`)
  
- **`app/models.py`**: Pydantic schemas for all API requests/responses
  
- **`app/database.py`**: Async SQLite wrapper for session/message persistence

- **`app/system_prompt.md`**: System prompt sent to Claude for each session

### Frontend Files
- **`static/index.html`**: Single-page app (no build required)
- **`static/js/app.js`**: Initializes UI, manages global state
- **`static/js/stream-handler.js`**: Consumes SSE events from backend
- **`static/js/permission-manager.js`**: Permission request UI & approval flow

### Testing
- **`tests/`**: Pytest test suite
  - Unit tests use mocks to isolate components
  - Integration tests may use `mock-model` for testing without real APIs
  - All real tools must be mocked unless testing the tool itself

### Documentation
- **`CLAUDE.md`**: Project overview & quick start guide
- **`server/README.md`**: Backend-specific documentation
- **`documents/guides/`**: Feature documentation that must stay in sync with code

## Architectural Patterns

### Session Lifecycle
1. Frontend creates session via `POST /v1/sessions`
2. `SessionManager` creates a `Session` object wrapping a Claude SDK client
3. Session establishes connection to Claude Agent SDK
4. User sends message → `run_turn()` processes with permission checks
5. Events stream via SSE (text, tool_use, permission_request, result)
6. Session persisted in SQLite for history & restoration

### Permission Framework
- **Permission modes** define defaults: `default` (ask), `acceptEdits`, `bypassPermissions`, `plan`
- **Tool rules** override defaults per tool: `allow`, `ask`, `deny`
- **Permission requests** block turn execution until user responds
- **"Always" approval** updates session's persistent tool rules

### Event Streaming
- SSE stream yields JSON events: `{type, data, ...}`
- Event types: `session`, `text`, `thinking`, `tool_use`, `tool_result`, `tool_error`, `permission_request`, `planning_complete`, `result`, `error`, `done`
- Frontend consumes via `EventSource` or fetch with ReadableStream

## Modification Guidelines

### Adding a New API Route
1. Add Pydantic model in `models.py`
2. Implement route in `app/main.py`
3. Update frontend `api.js` to call new endpoint
4. Add tests in `tests/`
5. Update `documents/guides/feature_walkthrough.md`

### Adding a Tool or Permission
1. Register tool in `sessions.py` (`DEFAULT_TOOL_RULES`)
2. Implement permission check in `_can_use_tool()` callback
3. Update permission UI in `permission-manager.js`
4. Update documentation as per CLAUDE.md requirements

### Modifying the Permission Model
1. Update `PermissionMode` type in `models.py`
2. Update permission logic in `sessions.py`
3. Update frontend permission mode selector
4. Add integration tests for new behavior
5. Update `documents/guides/` (feature_walkthrough, test_feature_mapping, test_dependency_report)

## Conventions

### Code Style
- **Backend**: PEP 8, type hints required, docstrings for public APIs
- **Frontend**: ES module style, no transpilation, vanilla JS conventions
- **SQL**: Use async/await with aiosqlite, parameterized queries for safety

### Testing
- **Unit tests**: Mock all external dependencies (SDK, database, HTTP)
- **Integration tests**: Use `mock-model` identifier, no real API calls
- **Test naming**: `test_<feature>_<condition>_<expected>`

### Commit Message Format
- Prefix with feature area: `[backend]`, `[frontend]`, `[docs]`, `[test]`
- Example: `[backend] add permission override endpoint`

### Documentation Updates
**MANDATORY**: When adding/modifying features, update:
- `documents/guides/feature_walkthrough.md` (feature description)
- `documents/guides/test_feature_mapping.md` (test coverage)
- `documents/guides/test_dependency_report.md` (dependency mapping)
