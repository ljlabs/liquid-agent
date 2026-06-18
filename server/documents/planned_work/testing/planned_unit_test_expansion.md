# Planned Unit Test Expansion

This document outlines the proposed expansion of the unit test suite to ensure full coverage of the core features implemented in the backend. All tests described here are **unit tests**, meaning they must be isolated, fast, and must **never** call real LLM APIs, databases, or external tools.

## Testing Principles
- **Isolation**: Every test must mock its dependencies (e.g., `CustomLLMWrapper`, `database`, `execute_tool`).
- **Determinism**: Tests must not rely on real-world state (e.g., actual files on disk unless using a temporary directory).
- **Speed**: Tests should execute in milliseconds.

---

## 1. Session & Turn Logic (`app/sessions.py`)

| Test Case | Feature Covered | Reason / Scenario |
|-----------|-----------------|-------------------|
| `test_max_turns_boundary` | Turn Loop | Verify that the `run_turn` loop stops exactly at `max_turns` and does not allow a single additional turn. |
| `test_interrupt_during_turn` | Interrupt Handling | Verify that setting the `_interrupt_flag` immediately halts the `run_turn` loop and returns the session to `idle` status. |
| `test_permission_mode_transitions` | Permission Modes | Verify that switching the `permission_mode` (e.g., from `default` to `plan`) immediately changes the output of `_check_permission`. |
| `test_tool_rule_precedence` | Tool Rules | Verify that a specific tool rule (e.g., `Bash` $\rightarrow$ `deny`) takes precedence over a global permission mode (e.g., `bypassPermissions`). |
| `test_session_status_transitions` | Session Status | Verify the state machine transitions: `idle` $\rightarrow$ `running` $\rightarrow$ `idle` (on completion) and `idle` $\rightarrow$ `running` $\rightarrow$ `idle` (on interrupt). |

## 2. View Data Generation (`app/view_data.py`)

| Test Case | Feature Covered | Reason / Scenario |
|-----------|-----------------|-------------------|
| `test_build_messages_mixed_content` | Message Types | Verify that `_build_messages` correctly handles assistant messages containing a mix of text, thinking, and tool blocks. |
| `test_build_messages_empty_blocks` | Message Types | Verify that `_build_messages` handles empty content strings or empty block lists without crashing. |
| `test_build_usage_token_estimation` | Usage Metrics | Verify the accuracy of the token and cost estimation logic across different message roles and lengths. |
| `test_build_files_deduplication` | File Tracking | Verify that `_build_files` correctly deduplicates file paths and ensures the most recently touched file is listed first. |
| `test_build_tool_call_log_targets` | Tool Call Log | Verify that the "target" string (e.g., path or command excerpt) is correctly extracted from various `tool_input` formats. |
| `test_build_session_log_formatting` | Session Log | Verify that backend log entries are correctly formatted and filtered into the `SessionLogEntry` view objects. |

## 3. Tool Implementation (`app/tools.py`)

| Test Case | Feature Covered | Reason / Scenario |
|-----------|-----------------|-------------------|
| `test_read_tool_invalid_path` | Tool Execution | Verify that `ReadTool` returns a `ToolResult` with `is_error=True` when given a non-existent path. |
| `test_replace_tool_no_match` | Tool Execution | Verify that `ReplaceTool` returns a specific error when the `old_string` is not found in the target file. |
| `test_bash_tool_timeout` | Tool Execution | Verify that `BashTool` handles command timeouts gracefully using a mocked subprocess. |
| `test_web_fetch_timeout` | Tool Execution | Verify that `WebFetchTool` handles network timeouts using a mocked HTTP client. |
| `test_glob_tool_no_results` | Tool Execution | Verify that `GlobTool` returns an empty string (not an error) when no files match the pattern. |

## 4. API & Request Handling (`app/main.py`)

| Test Case | Feature Covered | Reason / Scenario |
|-----------|-----------------|-------------------|
| `test_view_endpoint_validation` | Backend API Contract | Verify that `POST /v1/view` returns a `422 Unprocessable Entity` error for missing required fields in various actions. |
| `test_set_model_api_persistence` | Backend API Contract | Verify that the `set_model` action correctly updates the session's model in both memory and the database. |
| `test_interrupt_api_handling` | Interrupt Handling | Verify that the `interrupt` action correctly triggers the session's interrupt flag. |
