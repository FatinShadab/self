# Document 08: Events Catalog

**Git Commit:** `14ffa606468920a97c672b39fbf3a43fccc52bdf`  
**Date:** 2026-10-17  
**Status:** Read-only architecture documentation

---

## 1. Overview

All events in SELF are emitted via `EventLogger.log(event_type, **kwargs)` and appended as newline-delimited JSON (JSONL) records to `workspace/logs/actions.jsonl` `[read] agent/infra/event_log.py:90-115`. Every record automatically includes an ISO 8601 UTC timestamp `ts` and the event identifier `event`.

This catalog documents all **101** unique event types statically found across the codebase.

---

## 2. Event Catalog

| Event Name | Primary Emitters (File:Line) | Payload Fields | Meaning & Context |
| :--- | :--- | :--- | :--- |
| `about_human_line_deleted` | `[read] agent/identity/identity.py:571` | `line_number`, `removed_chars` | A line of volunteered human preferences was deleted by human command. |
| `about_human_recorded` | `[read] agent/identity/identity.py:542` | `chars`, `session_id` | Volunteered information about the human was saved to state/about_human.md. |
| `agent_step` | `[read] agent/runtime/loop.py:303` | `message` | A text message chunk emitted by the agent model during a cycle. |
| `assumed_output_ceiling` | `[read] agent/llm/model_registry.py:296` | `ceiling`, `model`, `reason` | Logged when using fallback maximum output ceiling for an unconfigured model. |
| `capability_requested` | `[read] agent/infra/hardening.py:45` | `env_names`, `kind`, `official_page`, `provider` | A human request for external capability expansion was written to state/capability_requests.md. |
| `code_version` | `[read] agent/ui/version_check.py:44` | `plan_store_present`, `source_hash` | Harness code SHA-256 and plan store presence logged on boot. |
| `command_finished` | `[read] agent/tools/base_tools.py:457` | `exit_code`, `output_bytes`, `stream_id`, `timed_out`, `truncated` | A subprocess shell command finished with exit code, timing, and byte metrics. |
| `command_output` | `[read] agent/tools/base_tools.py:453` | `output`, `stream_id` | Streamed chunk of stdout/stderr from a running shell command. |
| `command_started` | `[read] agent/tools/base_tools.py:450` | `command`, `stream_id`, `timeout` | A shell command execution started with stream id and timeout. |
| `context_retrieval` | `[read] agent/runtime/loop.py:156` | `files_scanned`, `files_selected`, `query` | Diagnostic details on files scanned and selected for cycle memory context. |
| `conversation_thread_completed` | `[read] agent/session/conversation.py:109` | `chars`, `thread_id` | An independent conversation thread completed generating its response. |
| `conversation_thread_failed` | `[read] agent/session/conversation.py:66` | `error_type`, `thread_id` | An independent conversation thread failed with an exception. |
| `conversation_thread_started` | `[read] agent/session/conversation.py:57` | `chars`, `thread_id` | An independent conversation thread began processing user input. |
| `core_patch_proposed` | `[read] agent/identity/identity.py:706` | `diff_chars`, `name`, `path` | A proposed patch diff for /opt/agent/core was saved for human review. |
| `curriculum_proposed` | `[read] agent/learning/learning.py:294` | `difficulty`, `task` | A curriculum practice task was selected based on recent successes. |
| `custom_tool_executed` | `[read] agent/tools/tool_registry.py:441` | `exit_code`, `name`, `timed_out`, `version` | An agent-created custom tool was executed via tool_worker. |
| `cycle_completed` | `[read] agent/runtime/loop.py:630` | `actions`, `cycle`, `report`, `tokens_used` | An autonomous exploration cycle finished with report, actions, and spend. |
| `daily_budget_human_request_created` | `[read] agent/runtime/loop.py:273` | `path` | A HUMAN_REQUEST.md was created asking operator to resolve budget pause. |
| `daily_token_budget_blocked` | `[read] agent/infra/hardening.py:86` | `cap`, `requested`, `reserved`, `used` | A model call was blocked because it would exceed the daily token limit. |
| `daily_token_budget_updated` | `[read] agent/infra/hardening.py:108` | `cap`, `reserved`, `used` | The daily token budget recorded updated token spending and reservations. |
| `daily_token_limit_paused` | `[read] agent/runtime/loop.py:279` | `session_id` | The autonomous loop paused waiting for the daily token budget to reset. |
| `daily_token_limit_resumed` | `[read] agent/runtime/loop.py:283` | `session_id` | The autonomous loop resumed after daily token budget became available. |
| `editable_self_layer_initialized` | `[read] agent/identity/identity.py:222` | `path` | The writable extension layer /home/entity/self was initialized. |
| `environment_map_initialized` | `[read] agent/learning/learning.py:79` | `entries` | The verified environment map state/map.json was initialized with base facts. |
| `environment_map_updated` | `[read] agent/learning/learning.py:156` | `keys`, `source` | New verified environment facts were written to state/map.json. |
| `first_awakening_stage_completed` | `[read] agent/identity/identity.py:235` | `session_id`, `stage` | One of the five first-awakening initialization stages finished. |
| `handoff_compacted` | `[read] agent/session/session.py:198` | `overflow_path` | A handoff dictionary exceeding 6,000 characters was truncated with overflow archived. |
| `handoff_recovered_from_backup` | `[read] agent/session/session.py:103` | *none* | A corrupt handoff.json was safely restored from handoff_last_good.json. |
| `human_input_decision` | `[read] agent/learning/plan.py:474` | `cycle`, `decision`, `goal_id`, `input`, `priority`, `reason` | The agent recorded an explicit arbitration decision on human input. |
| `human_input_received` | `[read] agent/session/session.py:45` | `chars`, `kind` | A human input was received and queued into state/human_input.jsonl. |
| `human_name_saved` | `[read] agent/identity/identity.py:447` | `previous`, `session_id` | The human user's name was saved into identity state. |
| `identity_changed` | `[read] agent/identity/identity.py:132` | `change`, `session_id` | An identity change was recorded in state/identity_log.md. |
| `identity_context_fallback` | `[read] agent/runtime/loop.py:337` | `error_type` | Fallback identity context was used because identity state failed to load. |
| `identity_initialized` | `[read] agent/identity/identity.py:206` | `session_id` | Default identity.json was initialized for a new entity. |
| `llm_call_attempt` | `[read] agent/llm/llm.py:291` | `model`, `provider`, `provider_call_number` | An LLM API request was attempted with retry counter and provider details. |
| `llm_call_completed` | `[read] agent/llm/llm.py:353` | `effective_cap`, `input_tokens`, `latency_ms`, `max_output_tokens`, `model`, `output_tokens`, `provider`, `stop_reason`, `total_tokens`, `truncated` | An LLM API request finished successfully with measured tokens and latency. |
| `llm_call_failed` | `[read] agent/llm/llm.py:309` | `effective_cap`, `error`, `error_type`, `model`, `provider`, `retry_attempt`, `retryable` | An LLM API request failed with error type and retryability classification. |
| `llm_call_started` | `[read] agent/llm/llm.py:276` | `effective_cap`, `max_output_tokens`, `message_count`, `model`, `provider`, `tool_count` | An LLM API request was initiated with message counts and output caps. |
| `llm_key_rotated` | `[read] agent/llm/llm.py:238` | `key_count`, `key_index`, `provider`, `reason` | A provider API key was rotated after an authentication or rate limit failure. |
| `local_ollama_probed` | `[read] agent/llm/brain_router.py:195` | `model_count`, `ram_bytes`, `reachable` | Results of probing local container Ollama service availability. |
| `memory_recorded` | `[read] agent/learning/learning.py:187` | `outcome`, `tags` | A durable memory was appended to state/memory.jsonl with tags and outcome. |
| `memory_retrieval` | `[read] agent/learning/learning.py:219` | `query`, `selected`, `total` | Diagnostics on memory search query matching and ranking. |
| `model_assessment_recorded` | `[read] agent/llm/model_registry.py:371` | `evidence`, `name` | The agent recorded an evidence-backed assessment of a helper model. |
| `model_facts_recorded` | `[read] agent/llm/model_registry.py:565` | `count`, `name`, `origin` | Model facts extracted from web documentation or knowledge were saved. |
| `model_probe_case` | `[read] agent/helper_models/model_probe.py:238`<br>`[read] agent/helper_models/model_probe.py:194`<br>`[read] agent/helper_models/model_probe.py:214` | `name`, `probe_id` | Results of one specific probe case executed against a helper model. |
| `model_probe_completed` | `[read] agent/helper_models/model_probe.py:259` | `completed_cases`, `failed`, `inconclusive`, `name`, `probe_id` | A 4-case capability probe run against a helper model finished. |
| `model_probe_started` | `[read] agent/llm/model_registry.py:495` | `name`, `probe_id`, `session_id` | A capability probe run against a helper model started. |
| `model_research_recorded` | `[read] agent/llm/model_registry.py:610` | `fact_count`, `name`, `source_url`, `status`, `urls_tried` | Documentation facts researched for a helper model were recorded. |
| `name_context_resolved` | `[read] agent/identity/identity.py:527` | `name`, `source`, `status` | A name was classified into mythological, fictional, or style context. |
| `narration` | `[read] agent/infra/event_log.py:107` | `message` | A plain-language narration message emitted by the agent. |
| `network_request` | `[read] agent/helper_models/model_probe.py:129`<br>`[read] agent/helper_models/model_probe.py:124`<br>`[read] agent/llm/brain_router.py:175`<br>*(+6 more)* | `host`, `method`, `path`, `purpose` | An HTTP request was initiated with host and path logged (query stripped). |
| `plan_hygiene_applied` | `[read] agent/learning/plan.py:574` | `cycle`, `diff`, `plan_version` | Completed and dropped goals were cleaned from state/plan.json. |
| `plan_unchanged` | `[read] agent/learning/plan.py:444`<br>`[read] agent/learning/plan.py:300` | `cycle`, `diff`, `evidence`, `plan_version`, `reason`, `source` | The agent (source='agent') or harness fallback (source='harness_auto') affirmed that the existing plan remains valid. |
| `plan_updated` | `[read] agent/learning/plan.py:381` | `cycle`, `diff`, `evidence`, `plan_version`, `reason` | The agent modified state/plan.json citing evidence and reasons. |
| `plugin_command_error` | `[read] agent/plugins/manager.py:539` | `command`, `error`, `plugin` | An error occurred while executing a plugin-registered slash command. |
| `plugin_critic_failed` | `[read] agent/plugins/self_dev.py:653` | `error`, `name` | Plugin critic review LLM call failed or could not parse JSON. |
| `plugin_disabled` | `[read] agent/plugins/manager.py:441` | `plugin` | A plugin was deactivated at a cycle boundary. |
| `plugin_enabled` | `[read] agent/plugins/manager.py:417` | `hash`, `plugin`, `version` | A plugin was activated and dynamic tools registered at a cycle boundary. |
| `plugin_hash_mismatch` | `[read] agent/plugins/manager.py:524` | `actual`, `expected`, `plugin` | An enabled plugin was refused because its disk hash diverged from the pinned hash. |
| `plugin_load_failed` | `[read] agent/plugins/manager.py:249`<br>`[read] agent/plugins/manager.py:288` | `error`, `plugin` | A plugin failed schema parsing, core compatibility, or dynamic loading. |
| `plugin_project_review` | `[read] agent/runtime/loop.py:792`<br>`[read] agent/tools/base_tools.py:708` | `cycles`, `decision`, `name`, `reason`, `threshold`, `tokens` | Stop-loss review checkpoint triggered or continue/reduce_scope/abandon decision recorded. |
| `plugin_promoted` | `[read] agent/plugins/self_dev.py:757` | `name`, `source`, `target` | Human operator promoted a plugin draft from plugin_dev to workspace/plugins as disabled. |
| `plugin_proposed` | `[read] agent/plugins/self_dev.py:229` | `expected_benefit`, `name` | A new plugin proposal was submitted and stored in state/plugin_proposals.jsonl. |
| `plugin_removed` | `[read] agent/plugins/manager.py:465` | `archive_path`, `mode`, `plugin` | A plugin was removed and archived or purged by operator command. |
| `plugin_review_completed` | `[read] agent/plugins/self_dev.py:670` | `approved`, `name`, `score`, `tokens`, `wall_clock_seconds` | Stricter plugin critic review completed with score and metrics. |
| `plugin_scaffolded` | `[read] agent/plugins/self_dev.py:299` | `kind`, `name`, `path` | Plugin scaffold initialized in workspace/plugin_dev/<name>/. |
| `plugin_tested` | `[read] agent/plugins/self_dev.py:553` | `name`, `passed`, `test_type`, `tests_run` | Isolated plugin test execution completed with results. |
| `plugin_validated` | `[read] agent/plugins/self_dev.py:483` | `error_count`, `name`, `valid`, `warning_count` | Plugin static validation (manifest, permissions, secrets, injections) completed. |
| `provider_backoff` | `[read] agent/llm/brain_router.py:155` | `detail`, `provider`, `seconds` | The brain router applied exponential backoff after a provider rate limit. |
| `provider_benchmark_completed` | `[read] agent/tools/benchmark.py:37` | `cases_per_provider`, `providers` | A local benchmark run across configured providers completed. |
| `provider_call_attempt` | `[read] agent/llm/brain_router.py:125` | `model`, `provider`, `provider_call_number` | A supplementary provider API call was initiated via the brain router. |
| `provider_call_cap_reached` | `[read] agent/infra/provider_calls.py:26` | `limit` | The process-level provider call ceiling was reached. |
| `provider_call_completed` | `[read] agent/llm/brain_router.py:146` | `input_tokens`, `latency_ms`, `model`, `output_tokens`, `provider` | A supplementary provider API call finished successfully. |
| `provider_call_failed` | `[read] agent/llm/brain_router.py:140` | `error`, `error_type`, `provider` | A supplementary provider API call failed with an exception. |
| `provider_call_unavailable` | `[read] agent/llm/brain_router.py:136` | `error`, `provider` | A supplementary provider was unavailable or skipped. |
| `provider_docs_fetched` | `[read] agent/llm/providers/registry.py:138` | `content_type`, `provider`, `source_url`, `status` | Official documentation was retrieved for a provider. |
| `provider_key_requested` | `[read] agent/llm/providers/registry.py:188` | `env_names`, `provider`, `signup_url` | A request for a missing provider API key was written for human review. |
| `provider_registry_initialized` | `[read] agent/llm/providers/registry.py:79` | `providers` | The provider registry state/providers.json was loaded or initialized. |
| `provider_verified` | `[read] agent/llm/providers/registry.py:159` | `limits`, `provider`, `source_url` | Verified free-tier provider limits were saved to state/providers.json. |
| `reflection_coalesced` | `[read] agent/session/reflection.py:135` | `cycle`, `triggers` | Multiple reflection triggers were combined into a single reflection candidate. |
| `reflection_declined` | `[read] agent/session/reflection.py:288` | `cycle` | A reflection candidate was declined because no actionable trigger was present. |
| `reflection_failed` | `[read] agent/session/reflection.py:155` | `cycle`, `error_type` | A background reflection LLM call failed with an error. |
| `reflection_posted` | `[read] agent/session/reflection.py:332` | `cycle`, `has_question`, `thread_id` | A background reflection was posted to chat or log. |
| `reflection_reply_received` | `[read] agent/session/reflection.py:352` | `chars`, `thread_id` | The human replied to an open background reflection question. |
| `reflection_skipped` | `[read] agent/session/reflection.py:186`<br>`[read] agent/session/reflection.py:206`<br>`[read] agent/session/reflection.py:284`<br>*(+11 more)* | `cycle`, `reason` | A background reflection was skipped due to limits, cooldown, or stop flags. |
| `repeated_tool_action_blocked` | `[read] agent/runtime/loop.py:588` | `tool` | An identical (tool, arguments) action was blocked to prevent loops. |
| `report_generated` | `[read] agent/reporting/report.py:224` | `memories`, `since` | A markdown activity summary report was generated. |
| `run_completed` | `[read] agent/runtime/loop.py:661` | `iterations`, `reason`, `tokens_used` | An autonomous loop run finished with completed iterations and stop reason. |
| `run_failed` | `[read] agent/runtime/loop.py:748`<br>`[read] agent/runtime/loop.py:554` | `error`, `error_type`, `provider_error` | An autonomous loop run failed with an unhandled exception. |
| `run_started` | `[read] agent/runtime/loop.py:400` | `curriculum`, `daily_token_budget`, `goal`, `max_iterations`, `max_wall_clock_seconds`, `resumed_from_checkpoint`, `task`, `token_budget` | An autonomous loop run started with goal and limits. |
| `run_stopped` | `[read] agent/runtime/loop.py:233`<br>`[read] agent/runtime/loop.py:744`<br>`[read] agent/runtime/loop.py:435` | `reason` | An autonomous loop run stopped due to signal, STOP file, or human request. |
| `self_notes_rewritten` | `[read] agent/learning/learning.py:268` | `chars` | Working notes in state/self_notes.md were updated. |
| `session_crash_recovered` | `[read] agent/session/session.py:119` | `session_id` | A prior crashed session was detected and reconstructed from checkpoint. |
| `session_finished` | `[read] agent/session/session.py:142` | `end_reason`, `iteration_count`, `session_id` | A wake session finished and archived state to state/sessions.jsonl. |
| `session_handoff_checkpoint` | `[read] agent/session/session.py:133` | `iteration_count`, `session_id` | A periodic session checkpoint saved handoff state. |
| `session_reflection_completed` | `[read] agent/ui/wake.py:1176` | `purpose`, `tokens_used` | A wake-up or shutdown session reflection completed. |
| `session_reflection_fallback` | `[read] agent/ui/wake.py:1179` | `error_type`, `purpose` | A deterministic fallback reflection was used after an error. |
| `session_started` | `[read] agent/session/session.py:124` | `recovered_crash`, `recovered_handoff_backup`, `session_id` | A new wake session started with unique session id. |
| `session_summary` | `[read] agent/ui/wake.py:1484` | `message` | Summary text of session achievements emitted at session finish. |
| `session_unexpected_exception` | `[read] agent/ui/wake.py:1499` | *none* | An unexpected exception crashed the wake session. |
| `stale_budget_plan_recovered` | `[read] agent/ui/wake.py:1266` | `available_daily_tokens` | Stale token budget blocker items were cleared from the plan. |
| `stale_image_suspected` | `[read] agent/ui/version_check.py:50` | `expected_hash`, `image_hash` | Warning that runtime harness hash does not match expected image hash. |
| `token_spend` | `[read] agent/llm/llm.py:114`<br>`[read] agent/llm/llm.py:104`<br>`[read] agent/llm/llm.py:94`<br>*(+1 more)* | `call_input_tokens`, `call_output_tokens`, `daily_token_budget`, `max_output_tokens`, `reason`, `reserved_tokens`, `tokens_released`, `tokens_used`, `usage_known` | Token usage and reservation settlement details logged for an LLM call. |
| `tool_call` | `[read] agent/tests/identity/test_identity.py:66`<br>`[read] agent/tools/base_tools.py:363` | `arguments`, `tool` | A tool invocation started with tool name and arguments. |
| `tool_creation_failed` | `[read] agent/tools/tool_registry.py:412` | `attempt`, `name`, `traceback` | An attempt to create a custom tool failed with traceback. |
| `tool_critic` | `[read] agent/tools/tool_registry.py:346` | `attempt`, `name`, `verdict` | A candidate tool critic review completed with verdict. |
| `tool_failure_lesson` | `[read] agent/tools/tool_registry.py:419` | *none* | A failure lesson was saved after 3 consecutive tool creation attempts failed. |
| `tool_load_rejected` | `[read] agent/tools/tool_registry.py:188` | `error`, `how_to_clear`, `name` | A custom tool was rejected during loading due to schema or hash mismatch. |
| `tool_loaded` | `[read] agent/tools/tool_registry.py:193` | `name`, `version` | A registered custom tool was successfully loaded from disk. |
| `tool_registered` | `[read] agent/tests/reporting/test_report.py:22`<br>`[read] agent/tools/tool_registry.py:399` | `input_schema`, `name`, `version` | A new custom tool was approved, tested, and registered. |
| `tool_result` | `[read] agent/tests/identity/test_identity.py:67`<br>`[read] agent/tools/base_tools.py:435` | `duration_ms`, `ok`, `preview`, `result_chars`, `result_sha256`, `tool` | A tool execution finished with duration, byte size, and preview. |
| `tool_retrieval` | `[read] agent/tools/tool_registry.py:199` | `query`, `selected`, `top_k` | Custom tools retrieved by keyword search for the current step. |
| `tool_test` | `[read] agent/tools/tool_registry.py:365` | `attempt`, `name`, `result` | Unittest execution completed for a candidate custom tool. |
| `tool_test_compat_alias` | `[read] agent/tools/tool_registry.py:357` | `name`, `path` | Temporary alias created for a legacy tool import pattern. |
| `zero_cycle_session_preserved` | `[read] agent/ui/wake.py:1451` | `end_reason`, `session_id` | A session with 0 cycles preserved prior handoff without overwriting. |

---

## 3. Log Redaction & Integrity

- `[read] agent/infra/event_log.py:38-42`: All string values in event payloads are processed by `EventLogger.redactor.text()` to mask known credentials and tokens with `[REDACTED_SECRET]` before disk serialization.
- `[read] agent/infra/event_log.py:100`: Log writes use append mode (`'a'`) with UTF-8 encoding and flush immediately after writing each record.
