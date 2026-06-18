# Test Dependency Violation Report

This report audits every **unit test** (not integration tests) for violations of the isolation principle: unit tests must not interact with real dependencies (LLM, database, filesystem, subprocess, network).

**Scope:** `server/tests/test_*.py` files only. Integration tests in `tests/integration/` excluded.

---

## Executive Summary

| Severity | Count | Description |
|----------|-------|-------------|
| CRITICAL | 6 | Real subprocess execution (Bash commands) |
| HIGH | 28 | Real production SQLite database access |
| HIGH | 22 | Real filesystem read (`system_prompt.md`) |
| MEDIUM | 10 | Environment variable mutation without restore |
| LOW | 4 | Dead code / duplicate fixtures |

**Most pervasive issue:** `Session.__init__` → `_load_system_prompt()` reads `server/system_prompt.md` from disk. This affects every test that creates a `Session` object (22+ tests across all files).

---

## Systemic Issues (Affect Multiple Files)

### 1. `Session._load_system_prompt()` — Real Filesystem Read

**Location:** `sessions.py:107-116`
```python
def _load_system_prompt(self) -> str:
    prompt_path = Path(__file__).parent.parent / "system_prompt.md"
    content = ""
    if prompt_path.exists():
        content = prompt_path.read_text(encoding="utf-8")
```

**Impact:** Every test that instantiates `Session(...)` reads `server/system_prompt.md` from the real filesystem. This is outside any temp directory.

**Affected tests:** ~22 tests across 6 files.

**Fix:** Mock `_load_system_prompt` or accept a `system_prompt` kwarg in tests:
```python
with patch("app.sessions.Session._load_system_prompt", return_value=""):
    session = Session(session_id="test", cwd=tmpdir)
```

### 2. `db.DB_PATH` Unredirected in Multiple Fixtures

**Impact:** Several test fixtures pass the real `app.database` module to `ViewDataGenerator` or call `get_db()` without redirecting `db.DB_PATH` to a temp directory. This causes writes to the production `server/data/sessions.db`.

**Affected fixtures:**
- `test_main.py:async_client` — no DB redirect
- `test_view_endpoint.py:async_client` — no DB redirect
- `test_custom_client.py:setup_db` — calls `get_db()` on production path

---

## File-by-File Findings

### `test_sessions.py` — 7 violations, 7 clean

| Test | Real File Read | Real DB | Real Subprocess | Real HTTP | Verdict |
|------|:-:|:-:|:-:|:-:|---------|
| `test_sdk_availability` | - | - | - | - | CLEAN |
| `test_session_initialization` | YES | - | - | - | MINOR |
| `test_session_with_none_tools` | YES | - | - | - | MINOR |
| `test_session_with_tool_lists` | YES | - | - | - | MINOR |
| `test_session_connect_and_close` | YES | - | - | - | MINOR |
| `test_session_manager_create` | YES | - | - | - | MINOR |
| `test_session_manager_get_or_create` | YES | - | - | - | MINOR |
| `test_session_manager_close_all` | YES | - | - | - | MINOR |
| `test_pending_permission` | - | - | - | - | CLEAN |
| `test_default_auto_allow_tools` | - | - | - | - | CLEAN |
| `test_default_tool_rules_populated` | - | - | - | - | CLEAN |
| `test_db_session_crud` | - | temp | - | - | CLEAN (acceptable) |
| `test_db_message_crud` | - | temp | - | - | CLEAN (acceptable) |
| `test_db_get_nonexistent` | - | temp | - | - | CLEAN (acceptable) |

---

### `test_permissions.py` — 12 violations, 4 clean

| Test | Real File Read | Real DB | Real Subprocess | Real HTTP | Mock LLM | Verdict |
|------|:-:|:-:|:-:|:-:|:-:|---------|
| `test_default_tool_rules_defined` | - | - | - | - | N/A | CLEAN |
| `test_session_seeded_with_default_rules` | YES | - | - | - | N/A | MINOR |
| `test_session_get_tool_rules` | YES | - | - | - | N/A | MINOR |
| `test_set_tool_rule_updates_internal_state` | YES | - | - | - | N/A | MINOR |
| `test_check_permission_default_ask_triggers_permission` | YES | YES* | - | - | N/A | VIOLATION |
| `test_check_permission_allow_auto_approves` | YES | - | - | - | N/A | MINOR |
| `test_check_permission_deny_blocks` | YES | - | - | - | N/A | MINOR |
| `test_check_permission_read_auto_allows` | YES | - | - | - | N/A | MINOR |
| `test_check_permission_ask_overrides_auto_allow` | YES | YES* | - | - | N/A | VIOLATION |
| `test_case_insensitive_tool_rules` | YES | - | - | - | N/A | MINOR |
| `test_mock_tool_permission_request` | YES | YES | **YES** | - | YES | **CRITICAL** |
| `test_mock_tool_deny_prevents_execution` | YES | YES | - | - | YES | VIOLATION |
| `test_mock_tool_allow_runs_without_prompt` | YES | YES | **YES** | - | YES | **CRITICAL** |
| `test_http_tool_defaults` | - | YES | - | - | N/A | VIOLATION |
| `test_http_session_tool_rules` | YES | YES | - | - | N/A | VIOLATION |
| `test_http_resolve_permission` | YES | YES | **YES** | - | YES | **CRITICAL** |

`YES*` = hits production DB path (no `temp_db` fixture but `resolve_permission` fires DB call via `asyncio.create_task`)

---

### `test_main.py` — 10 violations, 8 clean (4 duplicates)

| Test | Real File Read | Real DB | Real Subprocess | Real HTTP | Verdict |
|------|:-:|:-:|:-:|:-:|---------|
| `test_health_endpoint` | - | - | - | - | CLEAN |
| `test_list_sessions_empty` | - | temp | - | - | CLEAN |
| `test_create_session` | YES | **PROD** | - | - | **VIOLATION** |
| `test_create_session_with_none_tools` | YES | **PROD** | - | - | **VIOLATION** |
| `test_create_session_minimal` | YES | **PROD** | - | - | **VIOLATION** |
| `test_close_session` | YES | **PROD** | - | - | **VIOLATION** |
| `test_close_nonexistent_session` | - | **PROD** | - | - | **VIOLATION** |
| `test_interrupt_nonexistent_session` | - | **PROD** | - | - | **VIOLATION** |
| `test_set_permission_mode_nonexistent_session` | - | **PROD** | - | - | **VIOLATION** |
| `test_set_model_nonexistent_session` | - | **PROD** | - | - | **VIOLATION** |
| `test_set_tool_rule_nonexistent_session` | - | **PROD** | - | - | **VIOLATION** |
| `test_resolve_permission_nonexistent_request` | - | **PROD** | - | - | **VIOLATION** |
| `test_db_list_sessions_empty` | - | temp | - | - | CLEAN |
| `test_db_session_not_found` | - | temp | - | - | CLEAN |
| `test_db_messages_not_found` | - | temp | - | - | CLEAN |
| `test_db_delete_session_not_found` | - | temp | - | - | CLEAN |

`PROD` = writes to `server/data/sessions.db` (production path, no temp redirect)

**Additional issue:** `async_client` fixture sets `ANTHROPIC_MODEL` and `ANTHROPIC_BASE_URL` env vars without restoring originals (environment pollution).

**Additional issue:** `async_client_with_db` is defined twice (lines 202 and 258). First definition is dead code (shadowed by second).

**Additional issue:** Tests on lines 290-320 are exact duplicates of tests on lines 220-250.

---

### `test_custom_client.py` — 2 violations, 5 clean

| Test | Real File Read | Real DB | Real Subprocess | Real HTTP | Verdict |
|------|:-:|:-:|:-:|:-:|---------|
| `setup_db` (autouse) | - | **PROD** | - | - | **VIOLATION** |
| `test_session_tool_call_flow` | YES | **PROD** | **YES** | - | **CRITICAL** |
| `test_tool_read_file_range` | tmp | - | - | - | CLEAN (acceptable) |
| `test_tool_replace_file` | tmp | - | - | - | CLEAN (acceptable) |
| `test_tool_bash` | - | - | **YES** | - | **VIOLATION** |
| `test_tool_web_fetch` | - | - | - | - | CLEAN (mocked) |
| `test_delegation_tool` | - | - | - | - | CLEAN (stub) |

**Critical detail:** `setup_db` is `autouse=True` — it runs for EVERY test in the file. It calls `get_db()` which opens the production `server/data/sessions.db`. This means `test_tool_read_file_range`, `test_tool_replace_file`, `test_tool_web_fetch`, and `test_delegation_tool` all indirectly hit the production database during fixture setup, even though the test body itself doesn't.

---

### `test_turn_counting.py` — 2 minor violations

| Test | Real File Read | Real DB | Real Subprocess | Real HTTP | Verdict |
|------|:-:|:-:|:-:|:-:|---------|
| `test_session_turn_count_calculation` | YES | - | - | - | MINOR |
| `test_max_turns_limit` | YES | - | - | - | MINOR |

Both tests properly mock the database (via `AsyncMock` passed to `ViewDataGenerator`) and mock `CustomLLMWrapper` + `execute_tool` in `test_max_turns_limit`. The only real dependency is the `system_prompt.md` read.

**Additional issue:** Dead import `from app import database` (line 7) — never used.

---

### `test_view_endpoint.py` — 6 violations

| Test | Real File Read | Real DB | Real Subprocess | Real HTTP | Mock LLM | Verdict |
|------|:-:|:-:|:-:|:-:|:-:|---------|
| `test_view_crud` | YES | **PROD** | - | - | N/A | **VIOLATION** |
| `test_view_stream_sse` | YES | **PROD** | - | - | N/A | **VIOLATION** |
| `test_view_stream_no_session` | - | **PROD** | - | - | N/A | **VIOLATION** |
| `test_view_stream_switch_session` | YES | **PROD** | - | - | N/A | **VIOLATION** |
| `test_send_message` | YES | **PROD** | - | - | YES | **VIOLATION** |
| `test_model_propagation` | YES | **PROD** | - | - | YES | **VIOLATION** |

All 6 tests hit the real `server/data/sessions.db`. The `async_client` fixture passes the real `app.database` module unredirected.

LLM is properly mocked via `@patch("app.sessions.CustomLLMWrapper.chat_completion", _mock_chat_completion)` in `test_send_message` and `test_model_propagation`.

---

### `test_e2e_bash_pwd.py` — 1 test, 3 violations

| Test | Real File Read | Real DB | Real Subprocess | Real HTTP | Mock LLM | Verdict |
|------|:-:|:-:|:-:|:-:|:-:|---------|
| `test_e2e_bash_pwd_permission_flow` | YES | YES | **YES** | - | YES | **CRITICAL** |

The LLM is properly mocked via `mock.patch("app.sessions.CustomLLMWrapper", MockLLMPwd)`. However:
- `execute_tool("Bash", {"command": "pwd"})` runs a real subprocess
- `db.add_message()`, `db.store_pending_permission()`, `db.remove_pending_permission()` hit real SQLite
- `_load_system_prompt()` reads real `system_prompt.md`
- `session._llm = MockLLMPwd()` on line 38 makes the `mock.patch` on line 36 redundant

---

## Summary of Required Fixes

### CRITICAL (real subprocess execution)

| File | Tests | Fix |
|------|-------|-----|
| `test_permissions.py` | `test_mock_tool_permission_request`, `test_mock_tool_allow_runs_without_prompt`, `test_http_resolve_permission` | `mock.patch("app.sessions.execute_tool")` returning `ToolResult(output="mock output")` |
| `test_custom_client.py` | `test_session_tool_call_flow`, `test_tool_bash` | Mock `execute_tool` or mark as integration test |
| `test_e2e_bash_pwd.py` | `test_e2e_bash_pwd_permission_flow` | Mock `execute_tool` returning `ToolResult(output="/tmp\n")` |

### HIGH (real production database)

| File | Tests | Fix |
|------|-------|-----|
| `test_main.py` | 10 tests using `async_client` | Redirect `db.DB_PATH` to temp dir in fixture |
| `test_view_endpoint.py` | All 6 tests | Same — redirect `db.DB_PATH` |
| `test_custom_client.py` | All 6 tests (autouse `setup_db`) | Mock `get_db()`/`close_db()` or use temp DB |
| `test_permissions.py` | 2 tests without `temp_db` | Add `temp_db` fixture or mock DB |

### HIGH (real file read — system_prompt.md)

| File | Tests | Fix |
|------|-------|-----|
| All files | ~22 tests creating `Session` | `mock.patch("app.sessions.Session._load_system_prompt", return_value="")` in shared fixture |

### MEDIUM (environment variable pollution)

| File | Tests | Fix |
|------|-------|-----|
| `test_main.py` | `async_client` fixture | Use `monkeypatch.setenv()` or save/restore originals |

### LOW (code quality)

| File | Issue | Fix |
|------|-------|-----|
| `test_main.py` | Duplicate `async_client_with_db` fixture (lines 202, 258) | Remove first definition |
| `test_main.py` | Duplicate tests (lines 220-250 vs 290-320) | Remove duplicates |
| `test_turn_counting.py` | Dead import `from app import database` | Remove import |
