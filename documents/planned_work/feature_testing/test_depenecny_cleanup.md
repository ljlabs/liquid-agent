# Unit Test Dependency Cleanup Plan

**Goal**: Every unit test is self-contained — no real LLM calls, no real subprocess execution, no real production database access, no real filesystem reads outside temp directories.

**Execution model**: One agent per work unit. Each agent owns exactly one file. No agent touches another agent's file. Agents 2-7 depend on Agent 1 completing first; Agents 2-7 can run in parallel.

---

## Agent 1: Create `tests/conftest.py`

**Owns**: `tests/conftest.py` (full rewrite)
**Depends on**: Nothing
**Blocks**: Agents 2-7

Create the shared test infrastructure that all other test files depend on.

### 1.1 InMemoryDB class

A dict-backed replacement for `app.database`. Stores sessions, messages, pending permissions in plain Python dicts. Implements every method that `app.database` exports:

- `create_session(*, session_id, title, cwd, model, permission_mode, tool_rules)`
- `get_session(session_id)`
- `update_session(session_id, **fields)`
- `list_sessions(limit=50)`
- `delete_session(session_id)`
- `add_message(*, session_id, role, type, content, tool_name, tool_id, tool_input, pending_request_id)`
- `get_messages(session_id)`
- `get_message_count(session_id)`
- `store_pending_permission(*, session_id, request_id, tool_name, tool_id, tool_input)`
- `remove_pending_permission(session_id, request_id)`
- `get_pending_permissions(session_id)`
- `log_permission(*, session_id, request_id, tool_name, tool_input, approved, always)`

### 1.2 `mock_database` fixture (autouse)

Patches `app.main.db` and `app.sessions.db` with a `MagicMock` wired to the `InMemoryDB` instance. Every `db.*` call in production code routes to the in-memory stub.

```python
@pytest.fixture(autouse=True)
def mock_database():
    db = InMemoryDB()
    mock_db = MagicMock()
    for method_name in ["create_session", "get_session", "update_session",
                        "list_sessions", "delete_session", "add_message",
                        "get_messages", "get_message_count",
                        "store_pending_permission", "remove_pending_permission",
                        "get_pending_permissions", "log_permission"]:
        setattr(mock_db, method_name, getattr(db, method_name))

    with patch("app.main.db", mock_db), \
         patch("app.sessions.db", mock_db):
        yield db
```

### 1.3 `mock_system_prompt` fixture (autouse)

Patches `Session._load_system_prompt` to return `""`, preventing the real `system_prompt.md` file read.

```python
@pytest.fixture(autouse=True)
def mock_system_prompt():
    with patch("app.sessions.Session._load_system_prompt", return_value=""):
        yield
```

### 1.4 `mock_execute_tool` fixture (opt-in)

Mocks `app.sessions.execute_tool` to return `ToolResult(output="mock tool output")`. Only used by tests that approve permissions and need the agent loop to continue without running real subprocesses.

```python
@pytest.fixture
def mock_execute_tool():
    from app.tools import ToolResult
    with patch("app.sessions.execute_tool", new_callable=AsyncMock) as mock:
        mock.return_value = ToolResult(output="mock tool output")
        yield mock
```

### 1.5 `isolate_env` fixture (autouse)

Uses `monkeypatch` to set env vars for every test, preventing leakage between tests.

```python
@pytest.fixture(autouse=True)
def isolate_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MODEL", "mock-model")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-no-key-needed")
```

### 1.6 Remove old `mock_llm_server` fixture

The session-scoped `mock_llm_server` fixture that starts a real uvicorn server is for integration tests only. Remove it from this conftest. Integration tests have their own conftest at `tests/integration/feature_completion_tests/conftest.py`.

---

## Agent 2: Fix `tests/test_sessions.py`

**Owns**: `tests/test_sessions.py`
**Depends on**: Agent 1 (conftest fixtures apply automatically)
**Does not touch**: Any other file

### Changes needed

The `mock_database`, `mock_system_prompt`, and `isolate_env` autouse fixtures from conftest handle all violations automatically. This file needs minimal changes:

1. **Remove the duplicate `async_client_with_db` fixture** — this file doesn't have one, but verify no conflicts.
2. **Verify `test_db_*` tests still work** — they use `tempfile` + direct `test_db.DB_PATH` override. These are acceptable (testing the database module itself with isolated temp DB). No changes needed.
3. **No other changes** — the autouse fixtures from conftest handle the `system_prompt.md` read and env vars.

### Verification

Run: `python -m pytest tests/test_sessions.py -v`
All 14 tests should pass. No real DB files should appear outside temp dirs.

---

## Agent 3: Fix `tests/test_permissions.py`

**Owns**: `tests/test_permissions.py`
**Depends on**: Agent 1 (conftest fixtures apply automatically)
**Does not touch**: Any other file

### Changes needed

1. **Remove `temp_db` fixture** — the `mock_database` autouse fixture from conftest replaces it entirely. Delete the fixture and all references to it.

2. **Update `test_app_client` fixture** — remove `temp_db` dependency:

```python
@pytest.fixture
async def test_app_client():
    import app.main as main
    main.manager = SessionManager()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    await main.manager.close_all()
```

3. **Add `mock_execute_tool` to 3 tests** that approve permissions:

| Test | Line | Fix |
|------|------|-----|
| `test_mock_tool_permission_request` | 201 | Add `mock_execute_tool` param |
| `test_mock_tool_allow_runs_without_prompt` | 280 | Add `mock_execute_tool` param |
| `test_http_resolve_permission` | 361 | Add `mock_execute_tool` param |

Example:
```python
@pytest.mark.asyncio
async def test_mock_tool_permission_request(mock_execute_tool):
    # ... existing test body unchanged
```

4. **No other changes** — the autouse fixtures handle `system_prompt.md`, DB, and env vars.

### Verification

Run: `python -m pytest tests/test_permissions.py -v`
All 16 tests should pass. No real subprocesses, no real DB files, no real file reads.

---

## Agent 4: Fix `tests/test_main.py`

**Owns**: `tests/test_main.py`
**Depends on**: Agent 1 (conftest fixtures apply automatically)
**Does not touch**: Any other file

### Changes needed

1. **Delete duplicate `async_client_with_db` fixture** (first definition, lines 202-216). Keep only the second definition.

2. **Delete duplicate test functions** (lines 290-320). These are exact copies of tests on lines 220-250.

3. **Update `async_client` fixture** — remove manual DB path manipulation and env var mutation (handled by conftest):

```python
@pytest.fixture
async def async_client():
    from app.main import app
    from app.sessions import SessionManager
    from app.view_data import ViewDataGenerator
    from tests.conftest import InMemoryDB
    import app.main as main

    main.manager = SessionManager()
    main.view_generator = ViewDataGenerator(main.manager, InMemoryDB())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    await main.manager.close_all()
```

4. **Update `async_client_with_db` fixture** (second definition) — same pattern, use `InMemoryDB()` instead of redirecting `db.DB_PATH`:

```python
@pytest.fixture
async def async_client_with_db():
    from app.main import app
    from app.sessions import SessionManager
    from app.view_data import ViewDataGenerator
    from tests.conftest import InMemoryDB
    import app.main as main

    main.manager = SessionManager()
    main.view_generator = ViewDataGenerator(main.manager, InMemoryDB())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    await main.manager.close_all()
```

### Verification

Run: `python -m pytest tests/test_main.py -v`
All tests should pass. No `server/data/sessions.db` modifications. No env var leakage.

---

## Agent 5: Fix `tests/test_view_endpoint.py`

**Owns**: `tests/test_view_endpoint.py`
**Depends on**: Agent 1 (conftest fixtures apply automatically)
**Does not touch**: Any other file

### Changes needed

1. **Update `async_client` fixture** — use `InMemoryDB()` instead of real `app.database`:

```python
@pytest.fixture
async def async_client():
    from app.main import app
    from app.sessions import SessionManager
    from app.view_data import ViewDataGenerator
    from tests.conftest import InMemoryDB
    import app.main as main

    main.manager = SessionManager()
    main.view_generator = ViewDataGenerator(main.manager, InMemoryDB())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    await main.manager.close_all()
```

2. **No other changes** — the autouse fixtures handle `system_prompt.md`, DB module, and env vars.

### Verification

Run: `python -m pytest tests/test_view_endpoint.py -v`
All 5 tests should pass. No real DB files, no real file reads.

---

## Agent 6: Fix `tests/test_custom_client.py`

**Owns**: `tests/test_custom_client.py`
**Depends on**: Agent 1 (conftest fixtures apply automatically)
**Does not touch**: Any other file

### Changes needed

1. **Delete `setup_db` autouse fixture** — the `mock_database` autouse fixture from conftest handles this. Remove the fixture and the `autouse=True` marker.

2. **Fix `test_session_tool_call_flow`** — add `mock_execute_tool` param:

```python
@pytest.mark.asyncio
async def test_session_tool_call_flow(mock_execute_tool):
    # ... existing body unchanged
```

3. **Fix `test_tool_bash`** — mock `subprocess.run` to prevent real shell execution:

```python
@pytest.mark.asyncio
async def test_tool_bash():
    with mock.patch("app.tools.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="test bash\n", stderr=""
        )
        res = await execute_tool("Bash", {"command": "echo 'test bash'"})
        assert "test bash" in res.output.strip()
        mock_run.assert_called_once()
```

4. **No changes to** `test_tool_read_file_range`, `test_tool_replace_file`, `test_tool_web_fetch`, `test_delegation_tool` — these are already clean (use `tmp_path` or proper mocks).

### Verification

Run: `python -m pytest tests/test_custom_client.py -v`
All 6 tests should pass. No real subprocesses, no real DB files.

---

## Agent 7: Fix `tests/test_e2e_bash_pwd.py`

**Owns**: `tests/test_e2e_bash_pwd.py`
**Depends on**: Agent 1 (conftest fixtures apply automatically)
**Does not touch**: Any other file

### Changes needed

1. **Add `mock_execute_tool` param** to the test:

```python
@pytest.mark.asyncio
async def test_e2e_bash_pwd_permission_flow(mock_execute_tool):
    with mock.patch("app.sessions.CustomLLMWrapper", MockLLMPwd):
        session = Session(session_id="test_e2e", cwd="/tmp", permission_mode="default")
        session._llm = MockLLMPwd()
        # ... rest unchanged
```

2. **No other changes** — the autouse fixtures handle `system_prompt.md`, DB, and env vars.

### Verification

Run: `python -m pytest tests/test_e2e_bash_pwd.py -v`
The test should pass. No real subprocess, no real DB, no real file read.

---

## Agent 8: Verify `tests/test_turn_counting.py`

**Owns**: `tests/test_turn_counting.py`
**Depends on**: Agent 1 (conftest fixtures apply automatically)
**Does not touch**: Any other file

### Changes needed

1. **Remove unused import** — delete `from app import database` on line 7 (dead import).

2. **No other changes** — both tests are already well-isolated. The autouse fixtures handle the remaining `system_prompt.md` read.

### Verification

Run: `python -m pytest tests/test_turn_counting.py -v`
Both tests should pass.

---

## Execution Order

```
Agent 1 (conftest.py)
    ├── Agent 2 (test_sessions.py)      ─┐
    ├── Agent 3 (test_permissions.py)    │
    ├── Agent 4 (test_main.py)           ├── can run in parallel
    ├── Agent 5 (test_view_endpoint.py)  │
    ├── Agent 6 (test_custom_client.py)  │
    ├── Agent 7 (test_e2e_bash_pwd.py)   │
    └── Agent 8 (test_turn_counting.py) ─┘
```

## Final Verification (after all agents complete)

Run the full test suite:
```bash
cd server
python -m pytest tests/ -v --tb=short
```

Check:
1. All tests pass
2. No `server/data/sessions.db` modifications
3. No real subprocesses spawned
4. No real file reads outside temp dirs
5. No env var leakage between tests
