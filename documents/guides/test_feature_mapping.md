# Test-to-Feature Mapping

This document maps every test in the codebase to the features it covers. Tests can cover multiple features, and features can be covered by multiple tests.

**Legend:**
- ✅ = Test covers this feature
- 🔵 = Unit test (isolated, no real LLM)
- 🟢 = Integration test (uses mock LLM server or MockLLMClient)
- 🟡 = E2E test (full flow with mock LLM)

---

## Test Inventory Summary

| Test File | Type | Test Count |
|-----------|------|------------|
| `tests/test_main.py` | 🔵 Unit | 12 |
| `tests/test_sessions.py` | 🔵 Unit | 10 |
| `tests/test_permissions.py` | 🔵 Unit | 14 |
| `tests/test_view_endpoint.py` | 🟢 Integration | 5 |
| `tests/test_tool_use_feature.py` | 🟢 Integration | 2 |
| `tests/test_turn_counting.py` | 🔵 Unit | 2 |
| `tests/test_permission_refresh.py` | 🟢 Integration | 2 |
| `tests/test_integration_permission.py` | 🟢 Integration | 1 |
| `tests/test_custom_client.py` | 🔵 Unit | 6 |
| `tests/test_e2e_bash_pwd.py` | 🟡 E2E | 1 |
| `tests/integration/.../test_session_management.py` | 🟢 Integration | 12 |
| `tests/integration/.../test_permissions.py` | 🟢 Integration | 10 |
| `tests/integration/.../test_view_data_structure.py` | 🟢 Integration | 12 |
| `tests/integration/.../test_agent_conversation.py` | 🟢 Integration | 8 |
| `tests/integration/.../test_view_stream.py` | 🟢 Integration | 5 |
| `tests/integration/.../test_database_persistence.py` | 🟢 Integration | 8 |
| `tests/integration/.../test_error_handling.py` | 🟢 Integration | 6 |
| `tests/integration/.../test_interrupt.py` | 🟢 Integration | 2 |
| `tests/integration/.../test_page_refresh.py` | 🟢 Integration | 3 |
| `tests/integration/.../test_right_drawer.py` | 🟢 Integration | 11 |
| `tests/integration/.../test_legacy_endpoints.py` | 🟢 Integration | 7 |
| `app/static/js/__tests__/renderer.test.js` | 🔵 Unit (JS) | 13 |
| **Total** | | **123** |

---

## Feature Coverage Matrix

### 1. Backend API & Communication

#### 1.1 View Endpoint (`POST /v1/view`)
| Test | File | Covers |
|------|------|--------|
| `test_view_crud` | `test_view_endpoint.py` | ✅ All CRUD actions (get_view, create, set_mode, update_tool_rule, delete) |
| `test_send_message` | `test_view_endpoint.py` | ✅ send_message action, ViewData response |
| `test_model_propagation` | `test_view_endpoint.py` | ✅ set_model action, model persistence |
| `test_send_message_returns_view_data` | `test_agent_conversation.py` | ✅ send_message returns ViewData |
| `test_send_message_creates_user_message_in_db` | `test_agent_conversation.py` | ✅ send_message persists user message |
| `test_invalid_action_returns_422` | `test_error_handling.py` | ✅ Invalid action validation |
| `test_missing_action_returns_422` | `test_error_handling.py` | ✅ Missing action validation |
| `test_empty_body_returns_422` | `test_error_handling.py` | ✅ Empty body validation |

#### 1.2 View SSE Stream (`GET /v1/view/stream`)
| Test | File | Covers |
|------|------|--------|
| `test_view_stream_sse` | `test_view_endpoint.py` | ✅ SSE content type, ViewData format |
| `test_view_stream_no_session` | `test_view_endpoint.py` | ✅ Stream without session_id |
| `test_view_stream_switch_session` | `test_view_endpoint.py` | ✅ Session switching via stream |
| `test_stream_returns_sse` | `test_view_stream.py` | ✅ SSE content type |
| `test_stream_first_event_is_view` | `test_view_stream.py` | ✅ First event is ViewData |
| `test_stream_no_session` | `test_view_stream.py` | ✅ No session returns null active_session |
| `test_stream_sends_done_when_idle` | `test_view_stream.py` | ✅ Done event on idle |
| `test_stream_view_data_has_all_fields` | `test_view_stream.py` | ✅ ViewData field completeness |
| `test_available_models_in_sse_stream` | `test_view_data_structure.py` | ✅ available_models in SSE |

#### 1.3 Health Endpoint (`GET /v1/health`)
| Test | File | Covers |
|------|------|--------|
| `test_health_endpoint` | `test_main.py` | ✅ Status ok, sdk_available, active_sessions |
| `test_health_endpoint` | `test_error_handling.py` | ✅ Status ok, sdk_available, active_sessions |

#### 1.4 SSE Event Format
| Test | File | Covers |
|------|------|--------|
| `test_tool_use_appears_in_view_data` | `test_tool_use_feature.py` | ✅ tool_use events in ViewData |
| `test_tool_use_bubble_after_permission_granted` | `test_tool_use_feature.py` | ✅ tool_result events |
| `test_mock_tool_permission_request` | `test_permissions.py` | ✅ permission_request events |
| `test_mock_tool_deny_prevents_execution` | `test_permissions.py` | ✅ tool_error events |

---

### 2. Session Management

#### 2.1 Session Creation
| Test | File | Covers |
|------|------|--------|
| `test_create_session` | `test_main.py` | ✅ API creation, cwd, model |
| `test_create_session_with_none_tools` | `test_main.py` | ✅ None tool lists |
| `test_create_session_minimal` | `test_main.py` | ✅ Minimal parameters |
| `test_session_manager_create` | `test_sessions.py` | ✅ SessionManager.create, ID format |
| `test_create_session_returns_active_session` | `test_session_management.py` | ✅ ViewData active_session fields |
| `test_create_session_has_tool_rules` | `test_session_management.py` | ✅ Default tool rules on creation |
| `test_legacy_create_session` | `test_legacy_endpoints.py` | ✅ Legacy endpoint compatibility |

#### 2.2 Session Listing
| Test | File | Covers |
|------|------|--------|
| `test_list_sessions_empty` | `test_main.py` | ✅ Empty list initially |
| `test_session_list_empty_initially` | `test_session_management.py` | ✅ Empty list initially |
| `test_session_list_after_create` | `test_session_management.py` | ✅ Session appears in list |
| `test_session_list_multiple` | `test_session_management.py` | ✅ Multiple sessions |
| `test_session_list_after_delete` | `test_session_management.py` | ✅ Deleted session removed |
| `test_legacy_list_sessions` | `test_legacy_endpoints.py` | ✅ Legacy endpoint |

#### 2.3 Session Deletion
| Test | File | Covers |
|------|------|--------|
| `test_close_session` | `test_main.py` | ✅ Delete removes from list |
| `test_close_nonexistent_session` | `test_main.py` | ✅ Non-existent session handling |
| `test_delete_session` | `test_session_management.py` | ✅ Delete removes active_session |
| `test_delete_nonexistent_session_is_idempotent` | `test_session_management.py` | ✅ Idempotent delete |
| `test_legacy_close_session` | `test_legacy_endpoints.py` | ✅ Legacy endpoint |
| `test_legacy_close_nonexistent` | `test_legacy_endpoints.py` | ✅ Legacy 404 handling |

#### 2.4 Session Get-or-Create / Switching
| Test | File | Covers |
|------|------|--------|
| `test_session_manager_get_or_create` | `test_sessions.py` | ✅ Get existing, create new |
| `test_switch_session` | `test_session_management.py` | ✅ Switch restores session |
| `test_get_view_with_session` | `test_session_management.py` | ✅ Get view for specific session |
| `test_get_view_nonexistent_session` | `test_session_management.py` | ✅ Non-existent session returns null |

#### 2.5 Session Status States
| Test | File | Covers |
|------|------|--------|
| `test_session_initialization` | `test_sessions.py` | ✅ Initial status is "idle" |
| `test_session_connect_and_close` | `test_sessions.py` | ✅ idle → closed transition |
| `test_create_session_returns_active_session` | `test_session_management.py` | ✅ Status field in ViewData |
| `test_run_pwd_approve_flow` | `test_agent_conversation.py` | ✅ idle → running → idle |
| `test_run_pwd_deny_flow` | `test_agent_conversation.py` | ✅ idle after deny |

#### 2.6 Session Title Auto-Renaming
| Test | File | Covers |
|------|------|--------|
| *(none)* | | ❌ Not tested |

---

### 3. Database Persistence (SQLite)

#### 3.4 Session CRUD
| Test | File | Covers |
|------|------|--------|
| `test_db_session_crud` | `test_sessions.py` | ✅ create, get, update, list, delete |
| `test_db_get_nonexistent` | `test_sessions.py` | ✅ get returns None |

#### 3.5 Message CRUD
| Test | File | Covers |
|------|------|--------|
| `test_db_message_crud` | `test_sessions.py` | ✅ add_message, get_messages, get_message_count |

#### 3.6 Permission Persistence
| Test | File | Covers |
|------|------|--------|
| `test_permission_survives_page_refresh` | `test_permission_refresh.py` | ✅ store/remove pending permissions |
| `test_pending_permission_survives_session_removal` | `test_page_refresh.py` | ✅ Pending permission in DB |
| `test_approve_after_refresh_resumes_agent` | `test_page_refresh.py` | ✅ Restore session from DB |
| `test_deny_after_refresh_stops_agent` | `test_page_refresh.py` | ✅ Deny after refresh |

#### 3.7 Database Session Endpoints
| Test | File | Covers |
|------|------|--------|
| `test_db_list_sessions_empty` | `test_main.py` | ✅ GET /v1/db/sessions empty |
| `test_db_session_not_found` | `test_main.py` | ✅ GET /v1/db/sessions/{id} 404 |
| `test_db_messages_not_found` | `test_main.py` | ✅ GET /v1/db/sessions/{id}/messages 404 |
| `test_db_delete_session_not_found` | `test_main.py` | ✅ DELETE /v1/db/sessions/{id} 404 |
| `test_session_created_in_db` | `test_database_persistence.py` | ✅ Session in DB after creation |
| `test_session_deleted_from_db` | `test_database_persistence.py` | ✅ Session removed from DB |
| `test_user_message_persisted` | `test_database_persistence.py` | ✅ User message in DB |
| `test_tool_rule_persisted` | `test_database_persistence.py` | ✅ Tool rule in DB |
| `test_permission_mode_persisted` | `test_database_persistence.py` | ✅ Permission mode in DB |
| `test_db_session_not_found` | `test_database_persistence.py` | ✅ 404 for nonexistent |
| `test_db_messages_not_found` | `test_database_persistence.py` | ✅ 404 for nonexistent |
| `test_db_delete_not_found` | `test_database_persistence.py` | ✅ 404 for nonexistent |

---

### 4. LLM Integration

#### 4.1 Custom LLM Wrapper
| Test | File | Covers |
|------|------|--------|
| `test_sdk_availability` | `test_sessions.py` | ✅ SDK_AVAILABLE = True |
| `test_mock_llm_text_response` | `test_agent_conversation.py` | ✅ Text response from mock LLM |
| `test_mock_tool_permission_request` | `test_permissions.py` | ✅ MockLLM with tool_use response |
| `test_mock_tool_allow_runs_without_prompt` | `test_permissions.py` | ✅ MockLLM bypass mode |

#### 4.2 System Prompt Loading
| Test | File | Covers |
|------|------|--------|
| *(none)* | | ❌ Not tested |

#### 4.3 Available Models
| Test | File | Covers |
|------|------|--------|
| `test_available_models_in_get_view` | `test_view_data_structure.py` | ✅ Models list present |
| `test_available_models_includes_mock_model` | `test_view_data_structure.py` | ✅ mock-model included |
| `test_available_models_includes_standard_models` | `test_view_data_structure.py` | ✅ Claude/GPT models |
| `test_available_models_after_create_session` | `test_view_data_structure.py` | ✅ Models persist after session |

---

### 5. Agent Turn Execution

#### 5.1 Turn Loop
| Test | File | Covers |
|------|------|--------|
| `test_max_turns_limit` | `test_turn_counting.py` | ✅ max_turns respected |
| `test_run_pwd_approve_flow` | `test_agent_conversation.py` | ✅ Full two-turn loop |
| `test_run_pwd_deny_flow` | `test_agent_conversation.py` | ✅ Loop exits after deny |
| `test_run_pwd_auto_allow` | `test_agent_conversation.py` | ✅ Loop with auto-allow |
| `test_echo_keyword_flow` | `test_agent_conversation.py` | ✅ Keyword-based loop |
| `test_run_ls_deny_flow` | `test_agent_conversation.py` | ✅ Deny exits loop |
| `test_deny_halts_agent_loop_no_extra_llm_call` | `test_permissions.py` | 🔵 ✅ Deny halts loop, no extra LLM call |
| `test_deny_halts_resume_after_permission` | `test_permissions.py` | 🔵 ✅ Deny halts _resume_after_permission path |
| `test_deny_halts_agent_loop_integration` | `test_agent_conversation.py` | 🟢 ✅ Deny halts loop end-to-end |

#### 5.2 Message History
| Test | File | Covers |
|------|------|--------|
| `test_send_message_creates_user_message_in_db` | `test_agent_conversation.py` | ✅ User message persisted |
| `test_mock_llm_text_response` | `test_agent_conversation.py` | ✅ Assistant message in ViewData |
| `test_run_pwd_approve_flow` | `test_agent_conversation.py` | ✅ Tool result messages |

#### 5.3 Text Streaming
| Test | File | Covers |
|------|------|--------|
| `test_send_message` | `test_view_endpoint.py` | ✅ Message appears after send |
| `test_mock_llm_text_response` | `test_agent_conversation.py` | ✅ Text content in messages |

#### 5.4 Thinking/Extended Thinking
| Test | File | Covers |
|------|------|--------|
| *(none)* | | ❌ Not tested |

#### 5.5 Interrupt Handling
| Test | File | Covers |
|------|------|--------|
| `test_interrupt_stops_running_session` | `test_interrupt.py` | ✅ Interrupt sets idle |
| `test_interrupt_nonexistent_session` | `test_interrupt.py` | ✅ Non-existent session handling |
| `test_interrupt_nonexistent_session` | `test_main.py` | ✅ Non-existent session handling |

---

### 6. Tool System

#### 6.1 Available Tools
| Test | File | Covers |
|------|------|--------|
| `test_http_tool_defaults` | `test_permissions.py` | ✅ Canonical tool list |
| `test_tool_defaults_endpoint` | `test_error_handling.py` | ✅ Tool defaults endpoint |
| `test_legacy_tool_defaults` | `test_legacy_endpoints.py` | ✅ Legacy endpoint |

#### 6.2 Tool Execution
| Test | File | Covers |
|------|------|--------|
| `test_tool_read_file_range` | `test_custom_client.py` | ✅ Read with line range |
| `test_tool_replace_file` | `test_custom_client.py` | ✅ Replace tool |
| `test_tool_bash` | `test_custom_client.py` | ✅ Bash tool |
| `test_tool_web_fetch` | `test_custom_client.py` | ✅ WebFetch with mock |
| `test_delegation_tool` | `test_custom_client.py` | ✅ Delegate tool |

#### 6.3 Tool Events
| Test | File | Covers |
|------|------|--------|
| `test_tool_use_appears_in_view_data` | `test_tool_use_feature.py` | ✅ tool_use in ViewData |
| `test_tool_use_bubble_after_permission_granted` | `test_tool_use_feature.py` | ✅ tool_result in ViewData |
| `test_session_tool_call_flow` | `test_custom_client.py` | ✅ Full tool call event sequence |

#### 6.4 Tool Output Truncation
| Test | File | Covers |
|------|------|--------|
| *(none)* | | ❌ Not tested |

#### 6.5 Bash Tool - Windows Compatibility
| Test | File | Covers |
|------|------|--------|
| `test_tool_bash` | `test_custom_client.py` | ✅ Bash execution |

#### 6.6 Replace Tool - Match Validation
| Test | File | Covers |
|------|------|--------|
| `test_tool_replace_file` | `test_custom_client.py` | ✅ Replace success |

---

### 7. Permission System

#### 7.1 Permission Modes
| Test | File | Covers |
|------|------|--------|
| `test_set_mode_accept_edits` | `test_permissions.py` (integration) | ✅ acceptEdits mode |
| `test_set_mode_plan` | `test_permissions.py` (integration) | ✅ plan mode |
| `test_set_mode_bypass` | `test_permissions.py` (integration) | ✅ bypassPermissions mode |
| `test_set_mode_back_to_default` | `test_permissions.py` (integration) | ✅ Cycle back to default |
| `test_set_permission_mode_nonexistent_session` | `test_main.py` | ✅ Non-existent session |

#### 7.2 Tool Rules
| Test | File | Covers |
|------|------|--------|
| `test_default_tool_rules_defined` | `test_permissions.py` (unit) | ✅ DEFAULT_TOOL_RULES |
| `test_session_seeded_with_default_rules` | `test_permissions.py` (unit) | ✅ Session seeding |
| `test_session_get_tool_rules` | `test_permissions.py` (unit) | ✅ get_tool_rules() |
| `test_set_tool_rule_updates_internal_state` | `test_permissions.py` (unit) | ✅ set_tool_rule() |
| `test_default_tool_rules` | `test_permissions.py` (integration) | ✅ Default rules via API |
| `test_update_tool_rule_allow` | `test_permissions.py` (integration) | ✅ Rule → allow |
| `test_update_tool_rule_deny` | `test_permissions.py` (integration) | ✅ Rule → deny |
| `test_update_tool_rule_back_to_ask` | `test_permissions.py` (integration) | ✅ Rule → ask |
| `test_update_tool_rule_persists_in_db` | `test_permissions.py` (integration) | ✅ Rule persistence |
| `test_http_session_tool_rules` | `test_permissions.py` (unit) | ✅ Session tool rules endpoint |
| `test_set_tool_rule_nonexistent_session` | `test_main.py` | ✅ Non-existent session |

#### 7.3 Permission Request Flow
| Test | File | Covers |
|------|------|--------|
| `test_check_permission_default_ask_triggers_permission` | `test_permissions.py` (unit) | ✅ ask triggers pending |
| `test_check_permission_allow_auto_approves` | `test_permissions.py` (unit) | ✅ allow skips prompt |
| `test_check_permission_deny_blocks` | `test_permissions.py` (unit) | ✅ deny blocks immediately |
| `test_check_permission_read_auto_allows` | `test_permissions.py` (unit) | ✅ Read auto-allows |
| `test_check_permission_ask_overrides_auto_allow` | `test_permissions.py` (unit) | ✅ ask overrides auto-allow |
| `test_case_insensitive_tool_rules` | `test_permissions.py` (unit) | ✅ Case-insensitive lookup |
| `test_mock_tool_permission_request` | `test_permissions.py` (unit) | ✅ Mock tool triggers permission |
| `test_mock_tool_deny_prevents_execution` | `test_permissions.py` (unit) | ✅ Deny prevents execution |
| `test_mock_tool_allow_runs_without_prompt` | `test_permissions.py` (unit) | ✅ Allow skips prompt |
| `test_e2e_bash_pwd_permission_flow` | `test_e2e_bash_pwd.py` | ✅ Full Bash permission flow |
| `test_real_sdk_permission_callback` | `test_integration_permission.py` | ✅ Permission callback triggered |
| `test_tool_use_appears_in_view_data` | `test_tool_use_feature.py` | ✅ Permission status in ViewData |
| `test_run_pwd_approve_flow` | `test_agent_conversation.py` | ✅ Approve flow |
| `test_run_pwd_deny_flow` | `test_agent_conversation.py` | ✅ Deny flow |
| `test_run_pwd_auto_allow` | `test_agent_conversation.py` | ✅ Auto-allow flow |
| `test_echo_keyword_flow` | `test_agent_conversation.py` | ✅ Echo permission flow |
| `test_run_ls_deny_flow` | `test_agent_conversation.py` | ✅ LS deny flow |

#### 7.4 Permission Response
| Test | File | Covers |
|------|------|--------|
| `test_http_resolve_permission` | `test_permissions.py` (unit) | ✅ HTTP resolve endpoint |
| `test_resolve_permission_nonexistent_request` | `test_main.py` | ✅ Non-existent request |
| `test_respond_permission_invalid_request_id` | `test_error_handling.py` | ✅ Invalid request ID |
| `test_legacy_pending_permissions` | `test_legacy_endpoints.py` | ✅ Legacy endpoint |

#### 7.5 Pending Permission Recovery
| Test | File | Covers |
|------|------|--------|
| `test_permission_survives_page_refresh` | `test_permission_refresh.py` | ✅ Permission survives refresh |
| `test_deny_stops_agent` | `test_permission_refresh.py` | ✅ Deny after refresh |
| `test_pending_permission_survives_session_removal` | `test_page_refresh.py` | ✅ Pending in DB |
| `test_approve_after_refresh_resumes_agent` | `test_page_refresh.py` | ✅ Approve resumes |
| `test_deny_after_refresh_stops_agent` | `test_page_refresh.py` | ✅ Deny stops |

#### 7.6 Auto-Approve Mode
| Test | File | Covers |
|------|------|--------|
| `test_mock_tool_allow_runs_without_prompt` | `test_permissions.py` (unit) | ✅ Auto-allow |
| `test_run_pwd_auto_allow` | `test_agent_conversation.py` | ✅ Auto-allow via API |

---

### 8. View Data Generation

#### 8.1 ViewData Structure
| Test | File | Covers |
|------|------|--------|
| `test_view_data_top_level_fields` | `test_view_data_structure.py` | ✅ All top-level fields |
| `test_ui_state_structure` | `test_view_data_structure.py` | ✅ UIState fields |
| `test_session_view_structure` | `test_view_data_structure.py` | ✅ SessionView fields |
| `test_session_list_item_structure` | `test_view_data_structure.py` | ✅ SessionListItem fields |
| `test_tool_rule_view_structure` | `test_view_data_structure.py` | ✅ ToolRuleView fields |
| `test_files_structure` | `test_view_data_structure.py` | ✅ Files structure |
| `test_usage_structure` | `test_view_data_structure.py` | ✅ UsageData fields |
| `test_tool_call_log_structure` | `test_view_data_structure.py` | ✅ Tool call log structure |
| `test_session_log_structure` | `test_view_data_structure.py` | ✅ Session log structure |

#### 8.2 Session List Building
| Test | File | Covers |
|------|------|--------|
| `test_session_list_empty_initially` | `test_session_management.py` | ✅ Empty list |
| `test_session_list_after_create` | `test_session_management.py` | ✅ After creation |
| `test_session_list_multiple` | `test_session_management.py` | ✅ Multiple sessions |
| `test_session_list_after_delete` | `test_session_management.py` | ✅ After deletion |

#### 8.3 Message Building
| Test | File | Covers |
|------|------|--------|
| `test_mock_llm_text_response` | `test_agent_conversation.py` | ✅ Text messages |
| `test_run_pwd_approve_flow` | `test_agent_conversation.py` | ✅ Tool use + result messages |
| `test_session_turn_count_calculation` | `test_turn_counting.py` | ✅ Turn counting from messages |

#### 8.4 File Tracking
| Test | File | Covers |
|------|------|--------|
| `test_files_empty_for_new_session` | `test_right_drawer.py` | ✅ Empty files initially |
| `test_files_changed_after_write_tool` | `test_right_drawer.py` | ✅ Write → changed |
| `test_files_changed_after_edit_tool` | `test_right_drawer.py` | ✅ Replace → changed |
| `test_files_recently_read_after_read_tool` | `test_right_drawer.py` | ✅ Read → recently_read |

#### 8.5 Usage Metrics
| Test | File | Covers |
|------|------|--------|
| `test_usage_zero_for_new_session` | `test_right_drawer.py` | ✅ Zero usage initially |
| `test_usage_positive_after_message` | `test_right_drawer.py` | ✅ Tokens after message |
| `test_usage_wall_time_positive` | `test_right_drawer.py` | ✅ Wall time tracking |
| `test_context_window_has_valid_max` | `test_right_drawer.py` | ✅ Context window |

#### 8.6 Tool Call Log
| Test | File | Covers |
|------|------|--------|
| `test_tool_call_log_empty_for_new_session` | `test_right_drawer.py` | ✅ Empty initially |
| `test_tool_call_log_after_tool_use` | `test_right_drawer.py` | ✅ Populated after tool |
| `test_tool_call_log_chronological` | `test_right_drawer.py` | ✅ Chronological order |

#### 8.7 Session Log
| Test | File | Covers |
|------|------|--------|
| `test_session_log_empty_for_new_session` | `test_right_drawer.py` | ✅ Empty initially |
| `test_session_log_structure` | `test_right_drawer.py` | ✅ Entry structure |

---

### 9. Frontend UI
*(No frontend unit tests exist — all UI testing is manual or via integration)*

---

### 10. Streaming & Real-Time Updates

#### 10.1 View Stream Connection
| Test | File | Covers |
|------|------|--------|
| `test_stream_returns_sse` | `test_view_stream.py` | ✅ SSE connection |
| `test_stream_first_event_is_view` | `test_view_stream.py` | ✅ Initial ViewData |
| `test_stream_sends_done_when_idle` | `test_view_stream.py` | ✅ Done event |

#### 10.2 Action Dispatch
| Test | File | Covers |
|------|------|--------|
| `test_view_crud` | `test_view_endpoint.py` | ✅ All actions via sendAction |
| `test_send_message` | `test_view_endpoint.py` | ✅ send_message dispatch |

#### 10.3 Stream Event Handling
| Test | File | Covers |
|------|------|--------|
| `test_tool_use_appears_in_view_data` | `test_tool_use_feature.py` | ✅ tool_use rendering |
| `test_tool_use_bubble_after_permission_granted` | `test_tool_use_feature.py` | ✅ tool_result rendering |
| `test_run_pwd_approve_flow` | `test_agent_conversation.py` | ✅ Full event sequence |

---

### 11. Permission UI Components
*(No frontend unit tests exist)*

---

### 12. Session Switching & Restoration

#### 12.1 Session Switching
| Test | File | Covers |
|------|------|--------|
| `test_switch_session` | `test_session_management.py` | ✅ Switch restores session |
| `test_view_stream_switch_session` | `test_view_endpoint.py` | ✅ Switch via stream |
| `test_switch_session_returns_complete_view_data` | `test_session_management.py` | 🟢 ✅ Switch returns all ViewData fields for target session |
| `test sets activeSessionId before renderSessionList` | `renderer.test.js` | 🔵 ✅ Session highlight uses correct ID (Bug 1 fix) |

#### 12.2 Message Restoration
| Test | File | Covers |
|------|------|--------|
| *(none)* | | ❌ Not tested (would need DB message reconstruction) |

#### 12.3 Page Refresh Resumption
| Test | File | Covers |
|------|------|--------|
| `test_permission_survives_page_refresh` | `test_permission_refresh.py` | ✅ Permission survives refresh |
| `test_pending_permission_survives_session_removal` | `test_page_refresh.py` | ✅ Pending in DB |
| `test_approve_after_refresh_resumes_agent` | `test_page_refresh.py` | ✅ Approve resumes |
| `test_deny_after_refresh_stops_agent` | `test_page_refresh.py` | ✅ Deny stops |

---

### 13. Collapsible UI Sections
*(No frontend unit tests exist)*

---

### 14. Responsive Design
*(No frontend unit tests exist)*

---

### 15. CSS & Styling
*(No frontend unit tests exist)*

---

### 16. Error Handling

#### 16.1 Backend Error Events
| Test | File | Covers |
|------|------|--------|
| `test_mock_tool_deny_prevents_execution` | `test_permissions.py` (unit) | ✅ tool_error on deny |
| `test_deny_halts_agent_loop_no_extra_llm_call` | `test_permissions.py` (unit) | 🔵 ✅ Deny halts loop, no extra LLM call |
| `test_deny_halts_resume_after_permission` | `test_permissions.py` (unit) | 🔵 ✅ Deny halts _resume_after_permission |
| `test_run_pwd_deny_flow` | `test_agent_conversation.py` | ✅ tool_error message |
| `test_run_ls_deny_flow` | `test_agent_conversation.py` | ✅ tool_error message |
| `test_deny_halts_agent_loop_integration` | `test_agent_conversation.py` | 🟢 ✅ Deny halts loop end-to-end |

#### 16.2 Frontend Error Display
*(No frontend unit tests exist)*

#### 16.3 Tool Error Handling
| Test | File | Covers |
|------|------|--------|
| `test_mock_tool_deny_prevents_execution` | `test_permissions.py` (unit) | ✅ tool_error event |
| `test_deny_halts_agent_loop_no_extra_llm_call` | `test_permissions.py` (unit) | 🔵 ✅ tool_error + loop halt |
| `test_run_pwd_deny_flow` | `test_agent_conversation.py` | ✅ tool_error in messages |
| `test_deny_halts_agent_loop_integration` | `test_agent_conversation.py` | 🟢 ✅ tool_error + loop halt (E2E) |

---

### 17. Data Flow Summary
| Test | File | Covers |
|------|------|--------|
| `test_run_pwd_approve_flow` | `test_agent_conversation.py` | ✅ Full send → process → render flow |
| `test_tool_use_appears_in_view_data` | `test_tool_use_feature.py` | ✅ Full flow with tool |

---

### 18. Configuration & Environment

#### 18.1 Server Configuration
| Test | File | Covers |
|------|------|--------|
| `test_health_endpoint` | `test_main.py` | ✅ Server responds |

#### 18.2 Environment Variables
| Test | File | Covers |
|------|------|--------|
| `test_sdk_availability` | `test_sessions.py` | ✅ SDK available |

---

## Features with NO Test Coverage

The following features from the feature walkthrough have **no corresponding tests**:

| Feature | Section | Priority |
|---------|---------|----------|
| Session title auto-renaming | 2.6 | Medium |
| System prompt loading | 4.2 | Low |
| Thinking/extended thinking blocks | 5.4 | High |
| Tool output truncation (500 char) | 6.4 | Medium |
| Slash commands (/clear, /compact, etc.) | Frontend | Low |
| Keyboard shortcuts (Enter, Shift+Enter, Esc) | Frontend | Low |
| Sidebar collapsible sections | 13 | Low |
| Responsive design breakpoints | 14 | Low |
| CSS theme/styling | 15 | Low |
| Frontend session list rendering | Frontend | Medium |
| Frontend permission card UI | Frontend | Medium |
| Frontend tool block rendering | Frontend | Medium |
| Frontend thinking block rendering | Frontend | Medium |
| Frontend mode pill cycling | Frontend | Low |
| Frontend slash menu | Frontend | Low |
| Frontend right panel tabs | Frontend | Low |
| Frontend auto-scroll | Frontend | Low |
| Frontend message hash dedup | Frontend | Low |
| Frontend localStorage persistence | Frontend | Medium |
| Frontend SSE reconnection | Frontend | Medium |
| Frontend streaming cursor | Frontend | Low |
| Message restoration from DB on session switch | 12.2 | High |
| Session log entries after tool execution | 8.7 | Medium |
| Available models dropdown | Frontend | Low |
| Working directory input | Frontend | Low |
| Connection status indicator | Frontend | Low |
