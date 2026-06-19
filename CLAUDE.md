# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A FastAPI wrapper around the [Claude Agent SDK](https://docs.claude.com/en/docs/agent-sdk/python) that serves a VS Code extension-style web UI. Users interact with Claude through a browser-based chat interface that streams responses via SSE.

## Setup

```bash
cd server
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt

# The Agent SDK shells out to the Claude Code CLI — either let the SDK
# manage its own binary, or install the CLI yourself.
# Authenticate via:
#   export ANTHROPIC_API_KEY=sk-ant-...
# or run `claude` once interactively to log in with your Claude account
```

## Run

```bash
cd server
# On Windows, run via python to ensure the ProactorEventLoopPolicy is applied:
python app/main.py
```

Open `http://localhost:8787`. The UI is served directly by FastAPI's static file handler.

## Architecture

```
server/
├── app/
│   ├── main.py        FastAPI app, routes, SSE streaming
│   ├── sessions.py    Session manager wrapping ClaudeSDKClient
│   ├── models.py      Pydantic request/response models
│   └── static/
│       └── index.html The chat UI (served at /)
└── requirements.txt
```

The frontend is a single `index.html` file — no build step. The UI sends messages to `POST /v1/sessions/stream` (SSE) and handles events like `text`, `tool_use`, `tool_result`, `permission_request`, and `result`.

**Key concepts:**
- **Sessions**: In-memory (`SessionManager`) — each wraps a `ClaudeSDKClient` connection. No persistence.
- **Permissions**: Tools like `Read`, `Glob`, `Grep`, `WebFetch`, `WebSearch`, `TodoWrite` are auto-allowed. Others trigger `permission_request` SSE events that block the turn until the UI responds via `POST /v1/permissions/respond`.
- **Plan mode**: Prefixes the user message with read-only instructions; only auto-allowed tools run during plan mode.
- **Streaming**: `POST /v1/sessions/stream` returns `text/event-stream`. Events: `session`, `text`, `thinking`, `tool_use`, `tool_result`, `tool_error`, `permission_request`, `planning_complete`, `result`, `error`, `done`.

## Dependencies

- `fastapi`, `uvicorn[standard]`, `pydantic` — standard FastAPI stack


## Testing Guidelines

- **Unit Tests**: Must be isolated and fast. 
  - NEVER call real LLM APIs, databases, or external dependencies.
  - Real tools must NEVER be triggered unless the tool itself is the unit under test.
  - Use `unittest.mock` or `pytest-mock` to isolate the unit under test.
- **Integration Tests**: Used for end-to-end verification. These may hit mock servers or test databases.
  - **MANDATORY**: All integration tests must use the model ID `mock-model`.
- **Turn Counting**: A "turn" is defined as a single LLM response. Total session turns are the sum of all agent responses.

## Documentation Maintenance

Whenever a feature is added, modified, or removed, the following guides MUST be updated to ensure the documentation stays in sync with the implementation:
- `documents/guides/feature_walkthrough.md`: Update the feature description and expected behavior.
- `documents/guides/test_dependency_report.md`: Update the dependency mapping and impact analysis.
- `documents/guides/test_feature_mapping.md`: Update the test-to-feature mapping matrix.

