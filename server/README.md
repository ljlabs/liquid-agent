# Claude Agent SDK Wrapper

A FastAPI service that wraps the [Claude Agent SDK](https://docs.claude.com/en/docs/agent-sdk/python)
and serves a VS-Code-extension-style web UI for it.

## Layout

```
server/
├── app/
│   ├── main.py        FastAPI app, routes, SSE streaming
│   ├── sessions.py     Session manager wrapping ClaudeSDKClient
│   ├── models.py       Pydantic request/response models
│   └── static/
│       └── index.html  The chat UI (served at /)
└── requirements.txt
```

## Setup

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# The Agent SDK shells out to the Claude Code CLI. Either let the SDK
# manage its own binary, or install the CLI yourself:
curl -fsSL https://claude.ai/install.sh | bash

# Authenticate (one of):
export ANTHROPIC_API_KEY=sk-ant-...
# or run `claude` once interactively to log in with your Claude account
```

## Run

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8787 --reload
```

Open `http://localhost:8787` — the UI is served directly by FastAPI's
static file handler. In the sidebar, "Wrapper endpoint" should point at
this same address (defaults to `http://localhost:8787`).

## How the UI talks to the server

| UI action                              | Endpoint                                    |
|-----------------------------------------|----------------------------------------------|
| Send a message                           | `POST /v1/sessions/stream` (SSE response)   |
| Stop / interrupt                         | `POST /v1/sessions/{id}/interrupt`          |
| Change permission mode dropdown          | `POST /v1/sessions/{id}/permission-mode`    |
| Change model dropdown                    | `POST /v1/sessions/{id}/model`              |
| Click a tool permission badge            | `POST /v1/sessions/{id}/tool-rule`          |
| Click Allow/Always Allow/Deny on a card  | `POST /v1/permissions/respond`              |
| List / close sessions                    | `GET /v1/sessions`, `DELETE /v1/sessions/{id}` |
| Health check                             | `GET /v1/health`                            |

### Streaming protocol

`POST /v1/sessions/stream` accepts:

```json
{
  "message": "Fix the JWT validation bug",
  "session_id": "sess_abc123",      // null to start a new session
  "model": "claude-sonnet-4-6",
  "planning_mode": false,           // true = plan-mode pill active
  "auto_approve": false,            // true = auto-accept-edits pill active
  "permission_mode": "default",
  "cwd": "/path/to/project"
}
```

and responds with `text/event-stream`, one JSON object per `data:` line.
Event types emitted (all consumed by `index.html`'s `handleStreamEvent`):

- `session` — `{session_id, cwd, model, permission_mode}` (first event, lets a brand-new session register itself with the UI)
- `text` — `{data: "..."}` incremental assistant text
- `thinking` — `{data: "...", done: bool}` extended-thinking deltas
- `tool_use` — `{tool_id, name, input}` a tool call started
- `tool_result` — `{tool_id, output}` tool finished successfully
- `tool_error` — `{tool_id, error}` tool finished with an error
- `permission_request` — `{request_id, tool, input}` blocks until resolved via `/v1/permissions/respond`
- `planning_complete` — emitted at the end of a plan-mode turn
- `result` — final `{usage, cost_usd, duration_ms, num_turns, stop_reason}`
- `error` — `{message}` fatal error for this turn
- `done` — stream finished

### Permission flow

When `can_use_tool` is invoked by the SDK for a tool that isn't
auto-allowed (`Read`, `Glob`, `Grep`, `WebFetch`, `WebSearch`, `TodoWrite`),
the session emits a `permission_request` event and **blocks the turn**
until the UI calls:

```json
POST /v1/permissions/respond
{ "request_id": "...", "approved": true, "always": false }
```

`always: true` adds a persistent per-session rule (mirrors the sidebar's
allow/ask/deny badges), equivalent to clicking a permission badge.

### Plan mode

When `planning_mode: true`, the wrapper prefixes the user's message with
an instruction to produce a read-only plan first (only `Read`/`Glob`/
`Grep`/`WebFetch`/`WebSearch`/`TodoWrite` are permitted during this turn —
everything else is denied via `can_use_tool`). After the turn completes,
a `planning_complete` event is sent so the UI can show the "Proceed with
plan" / "Ask to revise" card. Clicking "Proceed" should simply send a
follow-up message (e.g. "Proceed with the plan") in `default` or
`acceptEdits` mode.

## Notes / extension points

- **Persistence**: sessions are in-memory only (`SessionManager`). For
  multi-instance deployments, swap this for a Redis-backed store and
  persist transcripts separately.
- **MCP servers**: pass `mcp_servers` in `SessionCreateRequest` /
  `StreamRequest` using the same shape as `ClaudeAgentOptions.mcp_servers`.
- **Auth**: add an auth dependency to the routes in `main.py` before
  exposing this beyond localhost — it executes arbitrary Bash/file
  operations on the host running the server.
